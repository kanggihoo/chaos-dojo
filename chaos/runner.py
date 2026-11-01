"""`chaos run`: the fixed run order (spec: Interfaces, `run` 실행 순서) and the repeat phases."""
import base64
import hashlib
import json
import queue
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import platformdirs
import psutil
import psycopg

from . import compose, verdict
from .engine import EngineError

LOCK = "chaos-lab-lock"
SCHEMA_VERSION = 1
PHASES = ["prepare", "warmup", "measured", "recovery", "convergence", "collect", "cleanup"]
EXCLUDE_DIRS = {"build", ".gradle", "node_modules", "__pycache__"}


class Abort(Exception):
    """Stops the run: no new load, no further repeats, exit 3."""


class Incomplete(Exception):
    """The repeat cannot finish its phases; it is cleaned up and the run continues."""


class CleanupFailed(Abort):
    pass


def now():
    return time.time() * 1000


def iso(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=False) + "\n", encoding="utf-8")


class Events:
    def __init__(self, path):
        self.path, self.seq, self.lock = path, 0, threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()

    def add(self, kind, **kw):
        with self.lock:
            self.seq += 1
            ev = {"seq": self.seq, "kind": kind, "at": iso(now()), **kw}
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(ev, ensure_ascii=False) + "\n")
            return ev


def http(method, url, body=None, auth=None, token=None, timeout=5, ok=(200, 201, 204)):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    if auth:
        req.add_header("Authorization", "Basic " + base64.b64encode(auth.encode()).decode())
    if token:
        req.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        if r.status not in ok:
            raise urllib.error.HTTPError(url, r.status, raw[:200].decode("utf-8", "replace"), r.headers, None)
        return json.loads(raw) if raw[:1] in (b"{", b"[") else raw.decode("utf-8", "replace")


def wait_until(deadline, check, interval=0.5):
    while True:
        try:
            v = check()
            if v:
                return v
        except Exception:  # noqa: BLE001 - not ready yet
            pass
        if now() >= deadline:
            return None
        time.sleep(interval)


# ---------------------------------------------------------------- lock

def machine_id():
    d = Path(platformdirs.user_data_dir("chaos-lab", appauthor=False))
    d.mkdir(parents=True, exist_ok=True)
    f = d / "machine-id"
    if not f.exists():
        f.write_text(secrets.token_hex(16))
    return f.read_text().strip()


def lock_alive(labels):
    """A run is live only if its lock names this machine and a process with the same pid and start time exists."""
    if labels.get("chaos-lab.machine") != machine_id():
        return None  # cannot tell from here
    try:
        p = psutil.Process(int(labels.get("chaos-lab.pid", "0")))
        return abs(p.create_time() - float(labels.get("chaos-lab.pid-start", "0"))) < 1
    except (psutil.Error, ValueError):
        return False


def read_lock(eng):
    r = eng.docker("container", "inspect", LOCK, check=False)
    if r.returncode:
        return None
    return json.loads(r.stdout)[0]["Config"]["Labels"]


def take_lock(eng, run_id, image):
    me = psutil.Process()
    labels = {"chaos-lab.run-id": run_id, "chaos-lab.role": "lock", "chaos-lab.machine": machine_id(),
              "chaos-lab.pid": str(me.pid), "chaos-lab.pid-start": str(me.create_time())}
    args = ["create", "--name", LOCK]
    for k, v in labels.items():
        args += ["--label", f"{k}={v}"]
    r = eng.docker(*args, image, check=False)
    if r.returncode == 0:
        return
    held = read_lock(eng)
    if held is None:
        raise Abort(f"could not create the engine lock: {r.stderr.decode('utf-8', 'replace').strip()[:300]}")
    alive = lock_alive(held)
    if alive:
        raise Abort(f"another run is in progress on this engine: {held.get('chaos-lab.run-id')}")
    raise Abort(f"a lock from run {held.get('chaos-lab.run-id')} remains; run `uv run chaos clean`"
                + (" (its process is gone)" if alive is False else " (it belongs to another machine; `chaos clean --run <id>` releases it)"))


def release_lock(eng):
    eng.docker("rm", LOCK, check=False)


def owned(eng, run_id, repeat=None):
    """Containers, networks and volumes carrying this run's labels (lock excluded)."""
    f = ["--filter", f"label=chaos-lab.run-id={run_id}"] + (["--filter", f"label=chaos-lab.repeat={repeat}"] if repeat else [])
    found = [f"container:{n}" for n in eng.text("ps", "-a", *f, "--format", "{{.Names}}").split() if n != LOCK]
    found += [f"network:{n}" for n in eng.text("network", "ls", *f, "--format", "{{.Name}}").split()]
    found += [f"volume:{n}" for n in eng.text("volume", "ls", *f, "--format", "{{.Name}}").split()]
    return found


# ---------------------------------------------------------------- inputs and identity

def copy_tree(src, dst):
    shutil.copytree(src, dst, ignore=lambda d, names: [n for n in names if n in EXCLUDE_DIRS], symlinks=True)


def hash_files(root):
    return {p.relative_to(root).as_posix(): sha256(p.read_bytes()) for p in sorted(root.rglob("*")) if p.is_file()}


def hash_closure(paths):
    h = hashlib.sha256()
    for p in sorted(paths, key=lambda p: p.as_posix()):
        files = sorted(x for x in p.rglob("*") if x.is_file()) if p.is_dir() else [p]
        for f in files:
            h.update(f.as_posix().encode().split(b"/problems/", 1)[-1] + b"\0" + f.read_bytes())
    return h.hexdigest()


def git(root, *args):
    r = subprocess.run(["git", *args], cwd=root, capture_output=True, stdin=subprocess.DEVNULL)
    return r.stdout.decode("utf-8", "replace") if r.returncode == 0 else None


def harness_git(root):
    head = git(root, "rev-parse", "HEAD")
    status = git(root, "status", "--porcelain", "--untracked-files=all")
    if head is None or status is None:
        return {"commit": None, "dirty": True, "reason": "not a git repository"}
    skip = ("problems/", "results/", "reports/", ".wf-grill/")
    changed = [l[3:] for l in status.splitlines() if not l[3:].startswith(skip)]
    return {"commit": head.strip(), "dirty": bool(changed), "changed": changed}


def build_git(root, ctx_rel):
    """Commit, dirty flag and patch for the impl build context (tracked changes + untracked files)."""
    head = git(root, "rev-parse", "HEAD")
    if head is None:
        return {"commit": None, "dirty": True, "patch": None}
    diff = git(root, "diff", "HEAD", "--binary", "--", ctx_rel) or ""
    untracked = (git(root, "ls-files", "--others", "--exclude-standard", "--", ctx_rel) or "").split()
    patch = diff + "".join(f"\n--- untracked {u}\n" + (Path(root) / u).read_text("utf-8", "replace") for u in untracked)
    return {"commit": head.strip(), "dirty": bool(patch.strip()), "patch": patch if patch.strip() else None}


def engine_identity(info):
    return {k: info.get(src) for k, src in (("product", "OperatingSystem"), ("server_version", "ServerVersion"), ("os_type", "OSType"),
                                             ("architecture", "Architecture"), ("cpus", "NCPU"), ("memory_bytes", "MemTotal"))}


def clock_offset(eng):
    """Engine minus host clock in ms, from the engine's own SystemTime; best of three by round trip."""
    best = None
    for _ in range(3):
        t0 = now()
        st = eng.text("info", "--format", "{{.SystemTime}}").strip()
        t1 = now()
        m = re.match(r"(.*T\d\d:\d\d:\d\d)(\.\d+)?(Z|[+-]\d\d:\d\d)$", st)
        frac = (m.group(2) or ".0")[:7]
        engine_ms = datetime.fromisoformat(m.group(1) + frac + m.group(3).replace("Z", "+00:00")).timestamp() * 1000
        sample = (t1 - t0, engine_ms - (t0 + t1) / 2)
        best = sample if best is None or sample[0] < best[0] else best
    return {"offset_ms": round(best[1], 1), "rtt_ms": round(best[0], 1)}


# ---------------------------------------------------------------- logs

def redactor(secrets_):
    """Generated credentials, the user's home path and the host name never reach result files (AC-37)."""
    import os
    import socket
    words = {os.path.expanduser("~"): "~", socket.gethostname(): "<host>"} | {v: "<secret>" for v in secrets_ if len(v) >= 8}
    pats = [(re.escape(k).encode(), v.encode()) for k, v in words.items() if k and k not in ("~", "/")]

    def redact(data):
        count = 0
        for pat, rep in pats:
            data, k = re.subn(pat, rep, data)
            count += k
        return data, count
    return redact


def cap_log(data, total, head):
    """Keep the first `head` and last `total - head` bytes, cut on UTF-8 boundaries, marking the cut."""
    if len(data) <= total:
        return data, None
    h = head
    while h > 0 and (data[h] & 0xC0) == 0x80:
        h -= 1
    t = len(data) - (total - head)
    while t < len(data) and (data[t] & 0xC0) == 0x80:
        t += 1
    marker = f"\n[chaos-lab: {t - h} bytes truncated]\n".encode()
    return data[:h] + marker + data[t:], {"original_bytes": len(data), "kept_head": h, "kept_tail": len(data) - t}


# ---------------------------------------------------------------- the run

class Run:
    def __init__(self, spec, eng):
        self.spec, self.eng = spec, eng
        self.contract, self.problem, self.scenario, self.impl = spec["contract"], spec["problem"], spec["scenario"], spec["impl"]
        self.root = Path(spec["root"])
        self.prefix = "chaos-" + secrets.token_hex(3)
        self.run_id = None
        self.dir = None
        self.events = None
        self.repeats = []
        self.cleanup = {"ok": True, "left": []}
        self.live = {"status": "ok", "reasons": []}
        self.annotations = queue.Queue(maxsize=self.contract["live"]["annotation_queue"])
        self.grafana = None
        self.obs_up = False
        self.prom = None
        self.redact = redactor([])

    # -- helpers
    def new_run_id(self):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        return f"{stamp}-{self.problem['id']}-{self.scenario['id']}-{self.impl['id']}-{secrets.token_hex(3)}"

    def degrade(self, reason):
        self.live["status"] = "degraded"
        if reason not in self.live["reasons"] and len(self.live["reasons"]) < 50:
            self.live["reasons"].append(reason)

    def annotate(self, text, tags, t_ms=None):
        """Recorded in events.jsonl first by the caller; the live copy is best effort and never blocks."""
        try:
            self.annotations.put_nowait({"text": text, "tags": ["chaos-lab", *tags], "time": int(t_ms or now())})
        except queue.Full:
            self.degrade("annotation queue full")

    def annotation_worker(self):
        timeout = self.contract["live"]["annotation_timeout_s"]
        while True:
            a = self.annotations.get()
            if a is None:
                return
            if not self.grafana:
                continue
            try:
                http("POST", f"{self.grafana['url']}/api/annotations", a, token=self.grafana["token"], timeout=timeout)
            except Exception as e:  # noqa: BLE001 - live copy only
                self.degrade(f"annotation failed: {type(e).__name__}")

    def promq(self, path, **params):
        url = f"http://{self.prom}/api/v1/{path}?" + urllib.parse.urlencode(params)
        with urllib.request.urlopen(url, timeout=10) as r:
            d = json.load(r)
        if d.get("status") != "success":
            raise RuntimeError(d)
        return d["data"]["result"]

    def port(self, project, file, service, port):
        out = self.eng.compose(self.dir, project, file, "port", service, str(port)).stdout.decode().strip()
        return out.splitlines()[0] if out else None

    def budgets(self):
        b = self.contract["budgets"]
        parts = {"app": b["app"], "k6": b["k6"], "alloy": b["alloy"], "lgtm": b["lgtm"], "toxiproxy": self.problem["proxy_budget"]}
        parts.update({d["name"]: d["budget"] for d in self.spec["deps"]})
        return parts

    # -- steps
    def main(self):
        eng = self.eng
        try:
            eng.resolve()
            info = eng.json("info", "--format", "{{json .}}")
        except (EngineError, ValueError) as e:
            print(f"error: Docker engine unavailable: {e}", file=sys.stderr)
            return 3
        self.run_id = self.new_run_id()
        while (self.root / "results" / self.run_id).exists():
            self.run_id = self.new_run_id()
        try:
            take_lock(eng, self.run_id, self.contract["images"]["toxiproxy"])
        except (Abort, EngineError) as e:
            print(f"error: {e}", file=sys.stderr)
            return 3
        try:
            need_cpu = sum(v["cpus"] for v in self.budgets().values())
            need_mem = sum(v["memory_mib"] for v in self.budgets().values()) * 1024 * 1024
            if info["NCPU"] < need_cpu or info["MemTotal"] < need_mem:
                release_lock(eng)
                print(f"error: engine has {info['NCPU']} CPU / {info['MemTotal'] // 2**20} MiB; a repeat needs {need_cpu} CPU / "
                      f"{need_mem // 2**20} MiB. Raise the engine's limits; budgets are never shrunk.", file=sys.stderr)
                return 3
            self.make_dir()
        except Exception as e:  # noqa: BLE001 - nothing else exists yet
            release_lock(eng)
            print(f"error: {e}", file=sys.stderr)
            return 3
        return self.execute(info)

    def make_dir(self):
        results = self.root / "results"
        results.mkdir(exist_ok=True)
        while True:
            try:
                (results / self.run_id).mkdir()
                break
            except FileExistsError:
                old = self.run_id
                self.run_id = self.new_run_id()
                release_lock(self.eng)
                take_lock(self.eng, self.run_id, self.contract["images"]["toxiproxy"])
                print(f"note: {old} already existed; using {self.run_id}", file=sys.stderr)
        self.dir = results / self.run_id
        self.events = Events(self.dir / "events.jsonl")
        inputs = self.dir / "inputs"
        inputs.mkdir()
        shutil.copy2(self.root / "chaos-contract.yaml", inputs / "chaos-contract.yaml")
        copy_tree(self.root / "harness", inputs / "harness")
        copy_tree(self.spec["problem_dir"], inputs / "problems" / self.problem["id"])
        if self.spec["predict"] is not None:
            (inputs / "predict").mkdir()
            (inputs / "predict" / self.spec["predict_name"]).write_bytes(self.spec["predict"])
            self.events.add("predict-copied", file=f"inputs/predict/{self.spec['predict_name']}", sha256=sha256(self.spec["predict"]))
        write_json(self.dir / "inputs-sha256.json", hash_files(inputs))

    def execute(self, info):
        eng, exit_code, error = self.eng, None, None
        worker = threading.Thread(target=self.annotation_worker, daemon=True)
        worker.start()
        self.identity = self.base_identity(info)
        try:
            self.prepare_images()
            self.start_obs()
            for n in range(1, self.contract["repeats"] + 1):
                self.repeats.append(self.run_repeat(n))
        except KeyboardInterrupt:
            error = "interrupted"
        except (Abort, EngineError) as e:
            error = str(e)
        except Exception as e:  # noqa: BLE001 - harness bug: still clean up and keep partial results
            error = f"harness error: {type(e).__name__}: {e}"
        if error:
            print(f"error: {error}", file=sys.stderr)
            self.events.add("run-stopped", reason=error)
            done = {r["n"] for r in self.repeats}
            for n in range(1, self.contract["repeats"] + 1):
                if n not in done:
                    self.repeats.append({"n": n, "completion": "not-run", "validity": "unknown", "exclusion": [f"not run: {error}"], "values": {}})
        self.annotations.put(None)
        self.finish_obs()
        if error is None and all(r["completion"] == "complete" for r in self.repeats) and self.cleanup["ok"]:
            exit_code = 0 if all(r["validity"] == "valid" for r in self.repeats) else 1
        else:
            exit_code = 3
        self.write_run_json(exit_code, error)
        try:
            from .report import render_runs
            (self.dir / "report.html").write_text(render_runs([self.dir]), encoding="utf-8")
        except Exception as e:  # noqa: BLE001 - never skip the unlock below
            print(f"error: report.html not written: {e}", file=sys.stderr)
            exit_code = 3
        if self.cleanup["ok"]:
            release_lock(eng)
        else:
            print("error: owned resources remain; the lock is kept. Run `uv run chaos clean`.", file=sys.stderr)
        print(f"results: {self.dir.relative_to(self.root).as_posix()}  exit {exit_code}")
        return exit_code

    def base_identity(self, info):
        sp, pdir = self.spec, self.spec["problem_dir"]
        s, p = self.scenario, self.problem
        scen_assets = [sp["scenario_dir"] / "scenario.yaml", (sp["scenario_dir"] / s["workload"]["script"]).resolve()]
        prob_assets = [pdir / "problem.yaml", pdir / p["openapi"]] + [pdir / d[k] for d in p["dependencies"] for k in ("schema", "openapi", "stubs") if k in d]
        others = self.eng.text("ps", "--format", "{{.Image}}")
        return {
            "engine": engine_identity(info),
            "comparison": {
                "scenario_sha256": hash_closure(scen_assets), "problem_sha256": hash_closure(prob_assets),
                "workload": s["workload"], "seed": s["workload"]["seed"],
                "contract": {"version": self.contract["contract_version"], "sha256": sha256((self.root / "chaos-contract.yaml").read_bytes())},
            },
            "harness": harness_git(self.root),
            "conditions": {"seed": s["workload"]["seed"], "budgets": self.budgets(),
                           "engine_host": "DOCKER_HOST" if self.eng.host else None,
                           "subprocess_env_names": sorted(set(self.eng.env()) | {compose.DB_USER, compose.DB_PASSWORD,
                                                                                  compose.WM_AUTH, compose.GF_PASSWORD}),
                           "tools": self.tool_versions(),
                           "other_containers": {"count": len(others.split()), "images": sorted(set(others.split()))}},
        }

    def tool_versions(self):
        from importlib.metadata import version
        uv = subprocess.run(["uv", "--version"], capture_output=True, text=True, stdin=subprocess.DEVNULL)
        return {"chaos_cli": version("chaos-lab"), "python": sys.version.split()[0], "uv": uv.stdout.strip() or None,
                "docker": self.eng.text("version", "--format", "{{.Client.Version}}").strip(),
                "compose": self.eng.text("compose", "version", "--short").strip(),
                "images": {k: v for k, v in self.contract["images"].items()}}

    def prepare_images(self):
        t0 = now()
        self.events.add("images-start")
        refs = {d["name"]: d["image"] for d in self.spec["deps"]} | {k: v for k, v in self.contract["images"].items()}
        images, self.image_volumes = {}, {}
        for name, ref in refs.items():
            self.eng.docker("pull", "-q", ref, timeout=900)
            img = self.eng.json("image", "inspect", ref)[0]
            plat = f"{img['Os']}/{img['Architecture']}"
            manifest = None
            r = self.eng.docker("manifest", "inspect", ref, check=False, timeout=60)
            if r.returncode == 0:
                for m in json.loads(r.stdout).get("manifests", []):
                    if f"{m['platform']['os']}/{m['platform']['architecture']}" == plat:
                        manifest = m["digest"]
            images[name] = {"ref": ref, "index_digest": ref.split("@")[1], "platform": plat, "platform_manifest_digest": manifest, "image_id": img["Id"]}
            self.image_volumes[ref] = list((img["Config"].get("Volumes") or {}).keys())
        ctx_rel = (self.spec["impl_dir"] / self.impl["image"]["build"]).resolve().relative_to(self.root.resolve()).as_posix()
        ctx_snapshot = self.dir / "inputs" / "problems" / self.problem["id"] / Path(ctx_rel).relative_to(f"problems/{self.problem['id']}")
        # Reproducible build: same sources give the same image ID, so every impl of a problem runs one identical image.
        build_flags = ["--provenance=false", "--sbom=false", "--build-arg", "SOURCE_DATE_EPOCH=0"]
        build_input = hash_closure([ctx_snapshot])
        # Tagged and inspected by tag: with the containerd image store, `build -q` prints the config digest, which may name no stored image,
        # while the stored image's ID is its manifest digest.
        tag = f"chaos-lab/{self.problem['id']}-app:{build_input[:12]}"
        self.eng.docker("build", "-q", *build_flags, "-t", tag, str(ctx_snapshot), timeout=1800)
        img = self.eng.json("image", "inspect", tag)[0]
        app_id = img["Id"]
        bg = build_git(self.root, ctx_rel)
        if bg["patch"]:
            (self.dir / "inputs" / "app-dirty.patch").write_text(bg["patch"], encoding="utf-8")
        images["app"] = {"image_id": app_id, "platform": f"{img['Os']}/{img['Architecture']}", "commit": bg["commit"], "build_flags": build_flags,
                         "dirty": bg["dirty"], "build_input_sha256": build_input,
                         "dirty_patch": "inputs/app-dirty.patch" if bg["patch"] else None}
        self.app_image = app_id
        self.identity["images"] = images
        self.events.add("images-ready", duration_ms=round(now() - t0))

    def start_obs(self):
        self.creds = {compose.DB_USER: "chaos", compose.DB_PASSWORD: secrets.token_urlsafe(18),
                      compose.WM_AUTH: "chaos:" + secrets.token_urlsafe(18), compose.GF_PASSWORD: secrets.token_urlsafe(18)}
        self.eng.secrets = dict(self.creds)
        self.redact = redactor(list(self.creds.values()) + [self.creds[compose.WM_AUTH].split(":", 1)[1]])
        self.run_ctx = {"run_id": self.run_id, "prefix": self.prefix, "run_network": f"{self.prefix}-run",
                        "app_image": self.app_image, "k6_script": self.scenario_script_rel()}
        doc = compose.dump(compose.obs_compose(self.spec, self.run_ctx))
        (self.dir / "run-compose.yaml").write_text(doc, encoding="utf-8")
        self.obs_project = f"{self.prefix}-obs"
        self.events.add("obs-start")
        self.obs_up = True
        self.eng.compose(self.dir, self.obs_project, "run-compose.yaml", "up", "-d", timeout=600)
        g = self.port(self.obs_project, "run-compose.yaml", "lgtm", 3000)
        self.prom = self.port(self.obs_project, "run-compose.yaml", "lgtm", 9090)
        self.tempo = self.port(self.obs_project, "run-compose.yaml", "lgtm", 3200)
        deadline = now() + 300_000
        ok = wait_until(deadline, lambda: http("GET", f"http://{g}/api/health") and http("GET", f"http://{self.prom}/-/ready"), 1)
        if not ok:
            raise Abort("observability stack did not become ready in 300 s")
        admin = f"admin:{self.creds[compose.GF_PASSWORD]}"
        # Grafana answers /api/health before it can serve the admin API; retry inside the same readiness budget.
        sa = wait_until(deadline, lambda: http("POST", f"http://{g}/api/serviceaccounts", {"name": f"chaos-harness-{secrets.token_hex(3)}", "role": "Editor"},
                                               auth=admin, timeout=10), 2)
        tok = sa and wait_until(deadline, lambda: http("POST", f"http://{g}/api/serviceaccounts/{sa['id']}/tokens", {"name": "run"},
                                                       auth=admin, timeout=10), 2)
        if not tok:
            raise Abort("Grafana admin API did not become ready in 300 s")
        self.grafana = {"url": f"http://{g}", "token": tok["key"]}
        self.events.add("obs-ready")
        print(f"Grafana: http://{g}/d/chaos-lab/chaos-lab?var-run_id={self.run_id}&refresh=5s", flush=True)

    def scenario_script_rel(self):
        p = (self.spec["scenario_dir"] / self.scenario["workload"]["script"]).resolve()
        return p.relative_to(self.spec["problem_dir"].resolve()).as_posix()

    def finish_obs(self):
        """Save observability logs, then remove repeat leftovers, the stack and the run network (in that order)."""
        if not self.obs_up:
            return
        logs = self.dir / "logs"
        logs.mkdir(exist_ok=True)
        cap = self.contract["log_cap_bytes"]
        for svc in ("alloy", "lgtm"):
            r = self.eng.docker("logs", f"{self.obs_project}-{svc}-1", check=False)
            data, red = self.redact(r.stdout + r.stderr)
            data, cut = cap_log(data, cap["total"], cap["head"])
            if red:
                self.events.add("log-redacted", file=f"logs/{svc}.log", replacements=red)
            (logs / f"{svc}.log").write_bytes(data)
            if cut:
                self.events.add("log-truncated", file=f"logs/{svc}.log", **cut)
        for leftover in sorted({x.split(":", 1)[1] for x in owned(self.eng, self.run_id) if x.startswith("container:")}):
            self.eng.docker("rm", "-f", "-v", leftover, check=False)
        for r in self.repeats:
            proj = f"{self.prefix}-r{r['n']}"
            if (self.dir / "repeats" / str(r["n"]) / "compose.yaml").exists():
                self.eng.compose(self.dir, proj, f"repeats/{r['n']}/compose.yaml", "--profile", "load", "down", "-v", "--remove-orphans",
                                 check=False, timeout=180)
        self.eng.compose(self.dir, self.obs_project, "run-compose.yaml", "down", "-v", "--remove-orphans", check=False, timeout=180)
        left = owned(self.eng, self.run_id)
        self.cleanup = {"ok": not left, "left": left}
        self.events.add("obs-removed", left=left)

    # -- repeats
    def run_repeat(self, n):
        rd = self.dir / "repeats" / str(n)
        (rd / "k6").mkdir(parents=True)
        (rd / "metrics").mkdir()
        (rd / "logs").mkdir()
        rp = Repeat(self, n, rd)
        try:
            return rp.run()
        except BaseException as e:
            self.repeats.append(rp.stopped(f"run stopped: {str(e) or type(e).__name__}"))
            raise

    def write_run_json(self, exit_code, error):
        reps = sorted(self.repeats, key=lambda r: r["n"])
        doc = {
            "schema_version": SCHEMA_VERSION, "run_id": self.run_id, "problem": self.problem["id"], "scenario": self.scenario["id"],
            "impl": self.impl["id"], "impl_description": self.impl["description"],
            "impl_extra_dependencies": self.impl["extra_dependencies"],
            "exit_code": exit_code, "error": error,
            "repeats": [{"n": r["n"], "completion": r["completion"], "validity": r["validity"],
                         "correctness": r.get("correctness"), "slo": r.get("slo"), "exclusion": r["exclusion"]} for r in reps],
            "aggregate": verdict.aggregate(reps, self.contract["repeats"]),
            "identity": self.identity, "live_status": self.live["status"], "live_reasons": self.live["reasons"],
            "cleanup": self.cleanup, "warmup_policy": "fixed",
            "predict": f"inputs/predict/{self.spec['predict_name']}" if self.spec["predict"] is not None else None,
            "observability_note": "The observability stack stays up for the whole run; its backend state carries over between repeats.",
        }
        write_json(self.dir / "run.json", doc)


class Repeat:
    def __init__(self, run, n, rd):
        self.r, self.n, self.rd, self.eng = run, n, rd, run.eng
        self.project = f"{run.prefix}-r{n}"
        self.file = f"repeats/{n}/compose.yaml"
        self.events = Events(rd / "events.jsonl")
        self.phases = []
        self.invalid, self.incomplete = [], None
        self.evidence_gaps = []
        self.records = []
        self.t0 = None
        self.faults = []
        self.stats = []
        self.stats_proc = None
        self.measured_end = None
        self.boundary = None
        self.values = {}
        self.extra = {}

    def phase(self, name, fn, timeout_s=None):
        start = now()
        ph = {"name": name, "timeout_s": timeout_s, "start": iso(start)}
        self.events.add("phase-start", phase=name, timeout_s=timeout_s)
        try:
            result = fn(start + timeout_s * 1000 if timeout_s else None)
            if isinstance(result, str):
                ph["not_applicable"] = result
        finally:
            ph["end"] = iso(now())
            self.phases.append(ph)
            self.events.add("phase-end", phase=name)

    def run(self):
        tm = self.r.scenario["phase_timeouts_s"]
        try:
            try:
                self.phase("prepare", self.prepare, tm["prepare"])
                self.phase("warmup", self.warmup, tm["warmup"])
                self.phase("measured", self.measured, tm["measured"])
                self.phase("recovery", self.recovery, tm["recovery"])
                self.phase("convergence", lambda d: "not applicable: the problem declares no convergence check")
                self.phase("collect", self.collect, tm["collect"])
            except Incomplete as e:
                self.incomplete = str(e)
                self.events.add("repeat-incomplete", reason=self.incomplete)
                self.stop_k6()
            except BaseException:
                self.stop_k6()
                self.salvage_logs()
                self.cleanup_phase(tm["cleanup"], fatal=False)
                raise
            if self.incomplete:
                self.salvage_logs()
        finally:
            self.stop_stats()
        self.phase("cleanup", lambda d: self.cleanup_phase(tm["cleanup"]), tm["cleanup"])
        return self.finish()

    # -- prepare
    def prepare(self, deadline):
        r, eng = self.r, self.eng
        doc = compose.dump(compose.repeat_compose(r.spec, r.run_ctx, self.n, r.image_volumes))
        (self.rd / "compose.yaml").write_text(doc, encoding="utf-8")
        self.extra["compose_sha256"] = sha256(doc.encode())
        self.extra["clock_start"] = clock_offset(eng)
        self.offset = self.extra["clock_start"]["offset_ms"]
        self.start_stats()
        deps = [d["name"] for d in r.spec["deps"]]
        eng.compose(r.dir, self.project, self.file, "up", "-d", "--no-deps", *deps, "toxiproxy", timeout=max(5, (deadline - now()) / 1000))
        if not wait_until(deadline, lambda: self.toxi("list")):
            raise Incomplete("toxiproxy did not become ready before the prepare timeout")
        self.dep_addr = {}
        for d in r.spec["deps"]:
            check = (lambda a, d=d: self.db_connect(a, d["name"]).close() or True) if d["kind"] == "postgres" else \
                    (lambda a: http("GET", f"http://{a}/__admin/health", auth=r.creds[compose.WM_AUTH], timeout=2))
            self.dep_addr[d["name"]] = self.ready(deadline, d["name"], d["port"], check)
        for d in r.spec["deps"]:
            self.toxi("create", "-l", f"0.0.0.0:{compose.proxy_port(r.spec['deps'], d['name'])}", "-u", f"{d['name']}:{d['port']}", d["name"])
        eng.compose(r.dir, self.project, self.file, "up", "-d", "--no-deps", "app", timeout=max(5, (deadline - now()) / 1000))
        mport = r.impl["ports"]["management"]
        self.mgmt = self.ready(deadline, "app", mport,
                               lambda a: http("GET", f"http://{a}{r.impl['readiness_path']}", timeout=2))
        if not wait_until(deadline, lambda: any(float(x["value"][1]) == 1 for x in r.promq(
                "query", query=f'up{{run_id="{r.run_id}",repeat="{self.n}"}}')), 1):
            raise Incomplete("no successful scrape of the app before the prepare timeout")
        self.events.add("first-scrape-ok")
        self.extra["scrape_targets"] = [{"job": "prometheus.scrape.app", "network": r.run_ctx["run_network"], "port": mport,
                                         "path": r.impl["metrics_path"]}]
        proxies = {}
        for line in self.toxi("list").splitlines():
            f = line.split("\t")
            if len(f) == 5:
                proxies[f[0]] = {"name": f[0], "listen": f[1], "upstream": f[2], "enabled": f[3] == "enabled", "toxics": int(f[4])}
        self.extra["topology"] = {"toxiproxy_version": self.toxi("--version").split()[-1], "api_listen": f"127.0.0.1:{compose.TOXI_API}",
                                  "proxies": proxies,
                                  "api_isolation": self.api_isolation()}
        iso = self.extra["topology"]["api_isolation"]
        if iso["reachable"] or not all(iso["control_ok"].values()):
            self.invalid.append(f"Toxiproxy API isolation not shown: {iso}")
        logs = eng.docker("logs", f"{self.project}-app-1", check=False)
        m = re.search(rb"chaos-resolved-settings (\{.*\})", logs.stdout + logs.stderr)
        self.extra["app"] = {"image_id": r.app_image, "resolved": json.loads(m.group(1)) if m else None}

    def toxi(self, *args):
        """Toxiproxy's API listens on its container's loopback; the harness reaches it only through the bundled CLI (D-10)."""
        return self.eng.text("exec", f"{self.project}-toxiproxy-1", "/toxiproxy-cli", *args, timeout=5)

    def api_isolation(self):
        """AC-20: from inside the app and a k6 container, try every Toxiproxy address on the API port.
        A proxy listener on the same host is the control, so a broken probe cannot pass as isolation."""
        ips = self.eng.text("inspect", "--format", "{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}",
                            f"{self.project}-toxiproxy-1").split()
        hosts = " ".join(["toxiproxy", *ips])
        control = f"toxiproxy {compose.proxy_port(self.r.spec['deps'], self.r.spec['deps'][0]['name'])}"
        app = self.eng.text("exec", f"{self.project}-app-1", "bash", "-c",
                            f'probe() {{ timeout 2 bash -c "</dev/tcp/$1/$2" 2>/dev/null; }}; probe {control} && echo control-ok; '
                            f'for h in {hosts}; do probe $h {compose.TOXI_API} && echo $h; done; true', check=False)
        k6 = self.eng.compose(self.r.dir, self.project, self.file, "run", "--rm", "-T", "--no-deps", "--entrypoint", "sh", "k6", "-c",
                              f"nc -z -w 2 {control} && echo control-ok; for h in {hosts}; do nc -z -w 2 $h {compose.TOXI_API} 2>/dev/null && echo $h; done; true",
                              check=False, timeout=60).stdout.decode("utf-8", "replace")
        out = {"probed": hosts.split(), "port": compose.TOXI_API, "control_ok": {}, "reachable": []}
        for who, text in (("app", app), ("k6", k6)):
            lines = text.split()
            out["control_ok"][who] = "control-ok" in lines
            out["reachable"] += [f"{who}->{h}" for h in lines if h != "control-ok"]
        return out

    def ready(self, deadline, service, port, check):
        def probe():
            st = self.eng.text("inspect", "--format", "{{.State.Status}} {{.State.ExitCode}}", f"{self.project}-{service}-1").split()
            if st and st[0] in ("exited", "dead"):
                raise Incomplete(f"{service} exited abnormally (exit {st[1]}) before it was ready")
            addr = self.r.port(self.project, self.file, service, port)
            return addr if addr and check(addr) else None
        while True:
            try:
                a = probe()
                if a:
                    return a
            except Incomplete:
                raise
            except Exception:  # noqa: BLE001 - not ready yet
                pass
            if now() >= deadline:
                raise Incomplete(f"{service} not ready before the prepare timeout")
            time.sleep(0.5)

    def db_connect(self, addr, dbname):
        host, port = addr.rsplit(":", 1)
        c = self.r.creds
        return psycopg.connect(host=host, port=int(port), dbname=dbname, user=c[compose.DB_USER], password=c[compose.DB_PASSWORD],
                               connect_timeout=3, autocommit=True)

    # -- docker stats
    def start_stats(self):
        self.stats_proc = self.eng.popen("stats", "--format", "{{json .}}")
        names = (self.project, self.r.obs_project)

        def read():
            for line in self.stats_proc.stdout:
                for m in re.finditer(r"\{.*?\}(?=\s*(\x1b|\{|$))", line):
                    try:
                        s = json.loads(m.group(0))
                    except ValueError:
                        continue
                    if s.get("Name", "").startswith(names):
                        self.stats.append({"t": now(), "name": s["Name"], "cpu": float(s["CPUPerc"].rstrip("%") or 0),
                                           "mem": s.get("MemUsage")})
        threading.Thread(target=read, daemon=True).start()

    def stop_stats(self):
        if self.stats_proc and self.stats_proc.poll() is None:
            self.stats_proc.terminate()
            try:
                self.stats_proc.wait(5)
            except subprocess.TimeoutExpired:
                self.stats_proc.kill()

    # -- k6
    def k6_config(self, phase):
        w, c = self.r.scenario["workload"], self.r.contract
        vus = int(w["rate"] * w["timeout_s"] * c["vu_factor"])
        base = {"baseUrl": f"http://app:{self.r.impl['ports']['business']}", "seed": w["seed"], "timeoutS": w["timeout_s"]}
        tags = {"run_id": self.r.run_id, "repeat": str(self.n)}
        car = lambda exe, dur: {"executor": "constant-arrival-rate", "exec": exe, "rate": w["rate"], "timeUnit": "1s",  # noqa: E731
                                "duration": f"{dur}s", "preAllocatedVUs": vus, "maxVUs": vus, "gracefulStop": f"{w['graceful_stop_s']}s"}
        if phase == "warmup":
            scen = {"warmup": car("warmup", w["warmup_s"])}
        else:
            scen = {"measured": car("measured", w["measured_s"])}
            if self.r.scenario["faults"]:
                rc, remove = self.r.problem["recovery"], max(f["remove_at_s"] for f in self.r.scenario["faults"])
                tol = self.r.contract["fault_tolerance_s"]
                count = (rc["max_s"] + tol + 1) // rc["interval_s"]
                scen["probe"] = {"executor": "per-vu-iterations", "exec": "probe", "vus": 1, "iterations": 1,
                                 "startTime": f"{remove}s", "maxDuration": f"{count * rc['interval_s'] + w['timeout_s'] + 5}s",
                                 "gracefulStop": f"{w['graceful_stop_s']}s"}
                base["probe"] = {"intervalMs": rc["interval_s"] * 1000, "count": count, "toleranceMs": tol * 1000,
                                 "consecutive": rc["consecutive"], "budgetMs": self.r.problem["slo"]["budget_ms"]}
        # Each iteration is an independent client: idle keep-alive connections of up to `vus` VUs would otherwise fill
        # Tomcat's max-connections and stall new requests regardless of any fault.
        cfg = {**base, "options": {"scenarios": scen, "tags": tags, "noVUConnectionReuse": True,
                                   "summaryTrendStats": ["min", "med", "p(99)", "max"]}}
        write_json(self.rd / "k6" / f"{phase}.json", cfg)
        return cfg

    def start_k6(self, phase, on_record=None):
        self.k6_config(phase)
        self.k6_log = (self.rd / "logs" / f"k6-{phase}.log").open("wb")
        self.k6_raw = (self.rd / "k6" / f"{phase}.jsonl").open("w", encoding="utf-8")
        self.k6 = self.eng.popen("compose", "--project-directory", str(self.r.dir), "-p", self.project, "-f", str(self.r.dir / self.file),
                                 "run", "--rm", "-T", "-e", f"CHAOS_PHASE={phase}", "k6", "run", "--quiet", "--log-format=raw",
                                 f"--summary-export=/out/{phase}-summary.json", "--out", "experimental-prometheus-rw", "/chaos/wrapper.js")

        def read():
            for line in self.k6.stdout:
                if line.startswith("{"):
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        self.k6_log.write(line.encode("utf-8", "replace"))
                        continue
                    self.k6_raw.write(line)  # record lines live only here; logs/k6-<phase>.log keeps the rest of the stream
                    if rec.get("k") in ("issue", "done"):
                        self.records.append(rec)
                    if on_record:
                        on_record(rec)
                else:
                    self.k6_log.write(line.encode("utf-8", "replace"))
                    if "Failed to send the time series" in line:
                        self.r.degrade("k6 remote-write push failed")
            self.k6_log.close()
            self.k6_raw.close()
        self.k6_reader = threading.Thread(target=read, daemon=True)
        self.k6_reader.start()

    def wait_k6(self, deadline, what):
        while self.k6.poll() is None:
            if now() >= deadline:
                raise Incomplete(f"{what} exceeded its phase timeout")
            time.sleep(0.2)
        self.k6_reader.join(10)
        if self.k6.returncode not in (0, 99):  # 99: thresholds crossed (none are set)
            raise Incomplete(f"k6 exited with {self.k6.returncode} during {what}")

    def stop_k6(self):
        k = getattr(self, "k6", None)
        if k and k.poll() is None:
            k.terminate()
            try:
                k.wait(10)
            except subprocess.TimeoutExpired:
                k.kill()
            self.eng.docker("rm", "-f", *self.eng.text("ps", "-aq", "--filter", f"label=com.docker.compose.project={self.project}",
                                                       "--filter", "label=com.docker.compose.service=k6").split(), check=False)

    # -- phases
    def warmup(self, deadline):
        self.start_k6("warmup")
        self.wait_k6(deadline, "warmup")
        r = self.r
        if not self.quiescent(["warmup"]):
            self.invalid.append("warmup cohort did not reach quiescence within 30 s")
            self.events.add("quiescence", cohorts=["warmup"], ok=False)
        else:
            self.events.add("quiescence", cohorts=["warmup"], ok=True)
        st = r.problem["store"]
        with self.db_connect(self.dep_addr[st["dependency"]], st["dependency"]) as c:
            c.execute(f'DELETE FROM {st["table"]}')
        self.events.add("orders-cleared")
        for d in r.spec["deps"]:
            if d["kind"] == "http-fake":
                http("DELETE", f"http://{self.dep_addr[d['name']]}/__admin/requests", auth=r.creds[compose.WM_AUTH])
        self.events.add("journal-cleared")
        self.boundary = now()
        self.events.add("boundary", at_ms=self.boundary)
        r.annotate(f"repeat {self.n}: warmup/measured boundary", ["boundary", f"repeat-{self.n}"])

    def quiescent(self, cohorts):
        """Two consecutive direct scrapes with zero in-flight for the cohorts and zero busy business threads."""
        p = self.r.problem
        inflight, busy = p["inflight_metric"], p["busy_metric"]
        port = self.r.impl["ports"]["business"]
        deadline, streak = now() + self.r.contract["collect_limits_s"]["quiescence"] * 1000, 0
        while now() < deadline:
            try:
                text = http("GET", f"http://{self.mgmt}{self.r.impl['metrics_path']}", timeout=2)
                vals = dict(re.findall(r'^(\S+?(?:\{[^}]*\})?) (\S+)$', text, re.M))
                fl = sum(float(v) for k, v in vals.items() if k.startswith(inflight + "{") and any(f'cohort="{c}"' in k for c in cohorts))
                bz = sum(float(v) for k, v in vals.items() if k.startswith(busy + "{") and f'"http-nio-{port}"' in k)
                streak = streak + 1 if fl == 0 and bz == 0 else 0
                if streak >= 2:
                    return True
            except Exception:  # noqa: BLE001
                streak = 0
            time.sleep(self.r.contract["intervals_s"]["scrape"])
        return False

    def measured(self, deadline):
        w = self.r.scenario["workload"]
        sched_started = threading.Event()

        def on_record(rec):
            if rec.get("k") == "t0" and self.t0 is None:
                self.t0 = rec["t"] - self.offset
                self.events.add("t0", engine_ms=rec["t"], host_ms=self.t0)
                self.r.annotate(f"repeat {self.n}: measured load start", ["phase", f"repeat-{self.n}"], self.t0)
                sched_started.set()
                threading.Thread(target=self.fault_schedule, daemon=True).start()
        self.measured_start = now()
        self.start_k6("measured", on_record)
        if not wait_until(min(deadline, now() + 60_000), sched_started.is_set, 0.05):
            raise Incomplete("k6 never reported the start of measured load")
        end_planned = self.t0 + w["measured_s"] * 1000
        hard_end = end_planned + w["graceful_stop_s"] * 1000
        while True:
            if self.fault_error:
                raise Abort(self.fault_error)
            t = now()
            if t >= end_planned:
                issued = {x["id"] for x in self.records if x["k"] == "issue" and x["cohort"] == "measured"}
                done = {x["id"] for x in self.records if x["k"] == "done" and x["cohort"] == "measured"}
                if issued <= done or t >= hard_end or self.k6.poll() is not None:
                    self.measured_end = min(t, hard_end)
                    break
            if t >= deadline:
                raise Incomplete("measured load exceeded its phase timeout")
            time.sleep(0.1)
        self.events.add("measured-end", host_ms=self.measured_end)

    fault_error = None

    def fault_schedule(self):
        """Apply and remove every fault at t0 + planned time; the confirmed time is when the control call returned success."""
        acts = []
        for i, f in enumerate(self.r.scenario["faults"]):
            acts += [(f["apply_at_s"], "apply", i, f), (f["remove_at_s"], "remove", i, f)]
        for at, what, i, f in sorted(acts, key=lambda a: a[0]):
            planned = self.t0 + at * 1000
            time.sleep(max(0, planned - now()) / 1000)
            if self.k6.poll() is not None and self.k6.returncode not in (0, 99):
                return
            dispatched = now()
            try:
                name = f"chaos-fault-{i}"
                t = f["target"]
                if f["action"] == "latency":
                    if what == "apply":
                        self.toxi("toxic", "add", "-t", "latency", "-a", f"latency={f['value_ms']}", "-a", "jitter=0", "--upstream", "-n", name, t)
                    else:
                        self.toxi("toxic", "remove", "-n", name, t)
                else:
                    want = "disabled" if what == "apply" else "enabled"
                    out = self.toxi("toggle", t)  # the CLI only toggles, so check it landed in the intended state
                    if f"now {want}" not in out:
                        raise RuntimeError(f"toggle left {t} in an unexpected state: {out.strip()}")
                confirmed = now()
            except Exception as e:  # noqa: BLE001
                self.events.add(f"fault-{what}", target=f["target"], action=f["action"], planned_ms=planned, dispatched_ms=dispatched,
                                result=f"failed: {e}")
                self.fault_error = f"fault {what} on {f['target']} failed: {e}"
                return
            ev = self.events.add(f"fault-{what}", target=f["target"], action=f["action"], value_ms=f.get("value_ms"),
                                 planned_ms=planned, dispatched_ms=dispatched, confirmed_ms=confirmed, result="ok")
            self.faults.append(ev)
            self.r.annotate(f"repeat {self.n}: fault {what} {f['action']} on {f['target']}", ["fault", f"repeat-{self.n}"], confirmed)

    def recovery(self, deadline):
        if not self.r.scenario["faults"]:
            self.wait_k6(deadline, "recovery check")
            return "not applicable: scenario has no fault"
        self.wait_k6(deadline, "recovery check")
        if self.fault_error:
            raise Abort(self.fault_error)

    # -- collect
    def collect(self, deadline):
        r, c = self.r, self.r.contract
        limits = c["collect_limits_s"]
        if not self.quiescent(["measured", "probe"]):
            self.evidence_gaps.append("measured/probe cohorts did not reach quiescence within 30 s")
        self.rows = None
        st = r.problem["store"]
        try:
            with self.db_connect(self.dep_addr[st["dependency"]], st["dependency"]) as conn:
                conn.autocommit = False
                cols = ", ".join([f'{st["request_id"]}::text', st["cohort"]] + list(st["fields"].values()))
                with conn.transaction():
                    conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                    rows = conn.execute(f'SELECT {cols} FROM {st["table"]}').fetchall()
                keys = ["request_id", "cohort"] + list(st["fields"].keys())
                self.rows = [dict(zip(keys, [v.strip() if isinstance(v, str) else v for v in row])) for row in rows]
                write_json(self.rd / "db-snapshot.json", self.rows)
        except Exception as e:  # noqa: BLE001
            self.evidence_gaps.append(f"DB snapshot failed: {e}")

        # arrival: every required metric has a sample after measured end, as stored behind the built-in collector
        mend_engine = (self.measured_end + self.offset) / 1000
        sel = f'run_id="{r.run_id}",repeat="{self.n}"'

        def arrived():
            return all(r.promq("query", query=f"max(timestamp({m}{{{sel}}}))") and
                       float(r.promq("query", query=f"max(timestamp({m}{{{sel}}}))")[0]["value"][1]) > mend_engine
                       for m in r.problem["required_metrics"])
        if not wait_until(now() + limits["arrival"] * 1000, arrived, 1):
            self.invalid.append("arrival check failed: required metrics not stored within 30 s after measured end")

        # export required metrics (raw samples) for the whole repeat
        export_deadline = now() + limits["export"] * 1000
        start_engine = (self.phase_start("prepare") + self.offset) / 1000
        span = max(1, int(time.time() + self.offset / 1000 - start_engine) + 5)
        self.exported = {}
        try:
            for m in ["up", *r.problem["required_metrics"]]:
                if now() > export_deadline:
                    raise TimeoutError
                res = r.promq("query", query=f"{m}{{{sel}}}[{span}s]")
                self.exported[m] = res
                write_json(self.rd / "metrics" / f"{m}.json", res)
        except TimeoutError:
            self.invalid.append("metric export exceeded 120 s")
        except Exception as e:  # noqa: BLE001
            self.invalid.append(f"metric export failed: {e}")

        self.extra["clock_end"] = clock_offset(self.eng)
        self.stop_stats()
        with (self.rd / "metrics" / "docker-stats.jsonl").open("w") as f:
            for s in self.stats:
                f.write(json.dumps(s) + "\n")
        self.collect_logs()
        # diagnostics: absence is recorded, never a verdict input
        try:
            res = http("GET", f"http://{r.tempo}/api/search?" + urllib.parse.urlencode(
                {"q": f'{{resource.chaos.run_id="{r.run_id}" && resource.chaos.repeat="{self.n}"}}', "limit": 100000}), timeout=10)
            write_json(self.rd / "traces" / "summary.json", {"traces": len(res.get("traces", [])),
                                                             "note": "diagnostic only; sampling and buffers make this incomplete"})
        except Exception as e:  # noqa: BLE001
            self.extra["traces_missing"] = str(e)
        try:
            for d in r.spec["deps"]:
                if d["kind"] == "http-fake":
                    j = http("GET", f"http://{self.dep_addr[d['name']]}/__admin/requests", auth=r.creds[compose.WM_AUTH], timeout=30)
                    write_json(self.rd / "wiremock-journal.json", [{"method": e["request"]["method"], "url": e["request"]["url"],
                                                                     "cohort": e["request"]["headers"].get("X-Chaos-Cohort"),
                                                                     "requestId": e["request"]["headers"].get("X-Request-Id"),
                                                                     "loggedDate": e["request"].get("loggedDate")}
                                                                    for e in j.get("requests", [])])
        except Exception as e:  # noqa: BLE001
            self.extra["journal_missing"] = str(e)

    def phase_start(self, name):
        p = next(p for p in self.phases if p["name"] == name) if any(p["name"] == name for p in self.phases) else None
        return datetime.fromisoformat(p["start"].replace("Z", "+00:00")).timestamp() * 1000 if p else now()

    def collect_logs(self):
        cap = self.r.contract["log_cap_bytes"]
        self.rollbacks = set()
        self.extra["log_truncation"] = {}
        names = self.eng.text("ps", "-a", "--filter", f"label=com.docker.compose.project={self.project}", "--format",
                              "{{.Label \"com.docker.compose.service\"}} {{.Names}}").split("\n")
        for line in filter(None, names):
            svc, name = line.split()
            r = self.eng.docker("logs", name, check=False)
            data = r.stdout + r.stderr
            data, red = self.r.redact(data)
            if red:
                self.extra.setdefault("log_redactions", {})[f"{svc}.log"] = red
            if svc == "app":
                self.rollbacks = set(re.findall(rb"chaos-rollback requestId=([0-9a-f-]{36})", data))
                self.rollbacks = {x.decode() for x in self.rollbacks}
            capped, cut = cap_log(data, cap["total"], cap["head"])
            (self.rd / "logs" / f"{svc}.log").write_bytes(capped)
            if cut:
                self.extra["log_truncation"][f"{svc}.log"] = cut
        for f in (self.rd / "logs").glob("k6-*.log"):
            data = f.read_bytes()
            capped, cut = cap_log(data, cap["total"], cap["head"])
            if cut:
                f.write_bytes(capped)
                self.extra["log_truncation"][f.name] = cut

    def salvage_logs(self):
        try:
            if not (self.rd / "logs" / "app.log").exists():
                self.collect_logs()
        except Exception:  # noqa: BLE001 - best effort on the failure path
            pass

    def cleanup_phase(self, timeout_s, fatal=True):
        self.eng.compose(self.r.dir, self.project, self.file, "--profile", "load", "down", "-v", "--remove-orphans", "--timeout", "10",
                         check=False, timeout=timeout_s)
        left = owned(self.eng, self.r.run_id, self.n)
        self.events.add("cleanup", left=left)
        if left and fatal:
            raise CleanupFailed(f"repeat {self.n} resources remain after cleanup: {left}")

    # -- verdicts
    def finish(self):
        r, c = self.r, self.r.contract
        out = {"n": self.n}
        if self.incomplete:
            completion = {"value": "incomplete", "reasons": [self.incomplete]}
            validity = {"value": "unknown", "reasons": ["repeat is incomplete"]}
            correct = {"value": "unknown", "reasons": ["repeat is incomplete"]}
            slo_v = {"value": "unknown", "reasons": ["repeat is incomplete"]}
            rec = {"applicable": bool(r.scenario["faults"]), "recovered": None}
            violations, ambiguous = [], []
        else:
            completion = {"value": "complete", "reasons": []}
            reqs = verdict.requests_from_records(self.records, self.offset)
            have_k6 = bool(reqs) and (self.rd / "k6" / "measured.jsonl").exists()
            removed = max((f["confirmed_ms"] for f in self.faults if f["kind"] == "fault-remove"), default=None)
            applied = min((f["confirmed_ms"] for f in self.faults if f["kind"] == "fault-apply"), default=None)
            budget = r.problem["slo"]["budget_ms"]
            rec = verdict.recovery(reqs, removed, r.problem["recovery"], budget) if r.scenario["faults"] else verdict.recovery(reqs, None, None, budget)
            slo_v = verdict.slo(reqs, r.problem["slo"], (applied, removed) if applied and removed else None, have_k6)
            gaps = list(self.evidence_gaps)
            if not have_k6:
                gaps.append("k6 raw results missing")
            if self.rows is None:
                violations, ambiguous, boundary = [], [], []
                if "DB snapshot" not in " ".join(gaps):
                    gaps.append("DB snapshot missing")
            else:
                violations, ambiguous, boundary = verdict.invariants(reqs, self.rows, r.spec["prices"], self.rollbacks, rec,
                                                                     {"recovery_max_s": r.problem["recovery"]["max_s"]})
                if boundary:
                    self.invalid.append(f"boundary violation: {len(boundary)} warmup orders present at check time")
            correct = verdict.correctness(violations, ambiguous, gaps)
            validity = {"value": "invalid" if self.validity_reasons(reqs) else "valid", "reasons": self.invalid}
            write_json(self.rd / "checks.json", {"invariants": r.problem["invariants"], "result": correct["value"],
                                                 "violations": violations, "ambiguous": ambiguous, "recovery": rec,
                                                 "rollbacks_recorded": sorted(self.rollbacks)})
            m = [q for q in reqs.values() if q["cohort"] == "measured"]
            self.values = {"in_budget_ratio": slo_v.get("in_budget_ratio"), "p99_201_ms": slo_v.get("p99_201_ms"),
                           "p50_201_ms": slo_v.get("p50_201_ms"), "time_to_recovery_ms": rec.get("time_to_recovery_ms"),
                           "ambiguous": len(ambiguous), "violations": len(violations)}
            self.extra["cohorts"] = {k: sum(1 for q in reqs.values() if q["cohort"] == k) for k in ("warmup", "measured", "probe")}
            self.extra["latency"] = verdict.latency_summary(m, budget)
        if self.incomplete:
            self.invalid = []
        exclusion = [] if completion["value"] == "complete" and validity["value"] == "valid" else completion["reasons"] + validity["reasons"]
        obs_usage = {}
        for s in self.stats:
            if s["name"].startswith(r.obs_project):
                u = obs_usage.setdefault(s["name"].removeprefix(r.obs_project + "-").removesuffix("-1"), [])
                u.append(s["cpu"])
        doc = {"schema_version": SCHEMA_VERSION, "n": self.n,
               "verdicts": {"completion": completion, "validity": validity, "correctness": correct, "slo": slo_v},
               "recovery": rec, "phases": self.phases, "warmup_policy": "fixed", "t0_ms": self.t0, "measured_end_ms": self.measured_end,
               "boundary_ms": self.boundary, "faults": self.faults, "values": self.values,
               "observability_usage": {k: {"cpu_mean_pct": round(sum(v) / len(v), 2), "cpu_max_pct": max(v)} for k, v in obs_usage.items()},
               **self.extra}
        write_json(self.rd / "repeat.json", doc)
        return {**out, "completion": completion["value"], "validity": validity["value"], "correctness": correct["value"],
                "slo": slo_v["value"], "exclusion": exclusion, "values": self.values}

    def stopped(self, reason):
        doc = {"schema_version": SCHEMA_VERSION, "n": self.n,
               "verdicts": {"completion": {"value": "incomplete", "reasons": [reason]},
                            "validity": {"value": "unknown", "reasons": ["repeat is incomplete"]},
                            "correctness": {"value": "unknown", "reasons": ["repeat is incomplete"]},
                            "slo": {"value": "unknown", "reasons": ["repeat is incomplete"]}},
               "phases": self.phases, "faults": self.faults, **self.extra}
        write_json(self.rd / "repeat.json", doc)
        return {"n": self.n, "completion": "incomplete", "validity": "unknown", "correctness": "unknown", "slo": "unknown",
                "exclusion": [reason], "values": {}}

    def validity_reasons(self, reqs):
        r, c = self.r, self.r.contract
        inv = self.invalid
        w = r.scenario["workload"]
        summary = self.rd / "k6" / "measured-summary.json"
        try:
            dropped = json.loads(summary.read_text())["metrics"].get("dropped_iterations", {}).get("count", 0)
            if dropped:
                inv.append(f"dropped_iterations={dropped}")
        except (OSError, ValueError):
            inv.append("required file missing: k6/measured-summary.json")
        cut = [q for q in reqs.values() if q["cohort"] == "measured" and q["done"] is None]
        if cut:
            inv.append(f"{len(cut)} measured iterations cut off by gracefulStop")
        window = (self.t0, self.measured_end) if self.t0 is not None and self.measured_end is not None else None
        if window:
            k6_stats = [dict(s, name="k6") for s in self.stats if s["name"].startswith(f"{self.project}-k6-run-")]
            sat = verdict.saturated(k6_stats, "k6", c["budgets"]["k6"]["cpus"], (window[0], window[1]),
                                    c["k6_saturation"]["window_s"], c["k6_saturation"]["max_ratio"])
            if sat is None:
                inv.append("k6 CPU usage unavailable (saturation cannot be ruled out)")
            elif sat:
                inv.append("k6 saturated: a 10 s window above 70% of its CPU budget")
            if hasattr(self, "exported"):
                if verdict.scrape_down(self.exported.get("up", []), window, self.offset):
                    inv.append("required scrape failed (up=0) during measured load")
                inv += verdict.missing_metrics(self.exported, r.problem["required_metrics"], window, c["intervals_s"]["scrape"],
                                               c["metrics_missing"]["min_ratio"], c["metrics_missing"]["max_gap_s"], self.offset)
        cs, ce = self.extra.get("clock_start"), self.extra.get("clock_end")
        if cs and ce:
            lim = c["clock_ms"]
            if max(abs(cs["offset_ms"]), abs(ce["offset_ms"])) > lim["max_offset"]:
                inv.append(f"host/engine clock offset above {lim['max_offset']} ms")
            if abs(ce["offset_ms"] - cs["offset_ms"]) > lim["max_drift"]:
                inv.append(f"clock drift above {lim['max_drift']} ms")
        tol = c["fault_tolerance_s"] * 1000
        for f in self.faults:
            if abs(f["confirmed_ms"] - f["planned_ms"]) > tol:
                inv.append(f"{f['kind']} on {f['target']} confirmed {f['confirmed_ms'] - f['planned_ms']:.0f} ms from plan")
        if r.scenario["faults"] and len(self.faults) < 2 * len(r.scenario["faults"]):
            inv.append("not every planned fault action was confirmed")
        for req in ("compose.yaml", "events.jsonl", "k6/measured.jsonl", "checks.json"):
            if req != "checks.json" and not (self.rd / req).exists():
                inv.append(f"required file missing: {req}")
        return inv


def run(spec, eng):
    return Run(spec, eng).main()

