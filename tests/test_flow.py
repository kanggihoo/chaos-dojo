"""Run order, exit codes, cleanup and lock (AC-2, AC-6, AC-7, AC-9, AC-11, AC-15, AC-16, AC-18, AC-21, AC-38).

The engine boundary is a fake that records every call in order. Repeat phases that talk HTTP/DB are scripted.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from chaos import runner
from chaos.cli import main
from chaos.engine import EngineError
from conftest import ROOT


class FlowEngine:
    def __init__(self, ncpu=10, mem=8 << 30, leftovers=None, lock=None, fail=None):
        self.calls, self.host, self.secrets = [], None, {}
        self.ncpu, self.mem = ncpu, mem
        self.leftovers = leftovers or {}   # repeat n -> names still present after its cleanup
        self.lock = lock                   # labels of an existing lock
        self.fail = fail or (lambda args: False)
        self.down = set()

    def resolve(self):
        self.calls.append(("resolve",))
        self.host = "unix:///fake.sock"
        return self.host

    def json(self, *args):
        self.calls.append(("json", *args))
        return {"NCPU": self.ncpu, "MemTotal": self.mem, "OperatingSystem": "FakeOS", "ServerVersion": "1", "OSType": "linux",
                "Architecture": "aarch64", "Name": "secret-host"}

    def docker(self, *args, check=True, timeout=None):
        self.calls.append(("docker", *args))
        if self.fail(args):
            if check:
                raise EngineError(f"fake failure: {args[:3]}")
            return subprocess.CompletedProcess(args, 1, b"", b"fail")
        if args[0] == "create" and args[2] == runner.LOCK:
            if self.lock is not None:
                return subprocess.CompletedProcess(args, 1, b"", b"Conflict. The container name is already in use")
            labels = dict(a.split("=", 1) for a in args[3::2] if "=" in a)
            self.lock = labels
        if args[:2] == ("rm", runner.LOCK):
            self.lock = None
        if args[:2] == ("container", "inspect"):
            if self.lock is None:
                return subprocess.CompletedProcess(args, 1, b"", b"")
            return subprocess.CompletedProcess(args, 0, json.dumps([{"Config": {"Labels": self.lock}}]).encode(), b"")
        return subprocess.CompletedProcess(args, 0, b"", b"")

    def text(self, *args, **kw):
        self.calls.append(("text", *args))
        if args[0] in ("ps", "network", "volume") and any("chaos-lab.run-id=" in a for a in args):
            rep = next((a.rsplit("=", 1)[1] for a in args if a.startswith("label=chaos-lab.repeat=")), None)
            if rep is not None:
                return "\n".join(self.leftovers.get(int(rep), [])) if args[0] == "ps" else ""
            return "\n".join(x for v in self.leftovers.values() for x in v) if args[0] == "ps" else ""
        return ""

    def compose(self, project_dir, project, file, *args, check=True, timeout=None):
        self.calls.append(("compose", project, *args))
        if "down" in args:
            self.down.add(project)
        return subprocess.CompletedProcess(args, 0, b"", b"")

    def popen(self, *args):
        raise AssertionError("no streaming in flow tests")

    def env(self):
        return {"PATH": "/usr/bin", "DOCKER_HOST": self.host}


def scripted(monkeypatch, plan=None, verdicts=None):
    """plan: {(n, phase): exception}; verdicts: {n: (completion, validity, correctness, slo)}."""
    plan, verdicts = plan or {}, verdicts or {}
    order = []

    def fake_prepare_images(self):
        self.events.add("images-ready", duration_ms=1)
        self.identity["images"] = {}
        self.app_image, self.image_volumes = "sha256:app", {}

    def fake_start_obs(self):
        self.creds = {"CHAOS_DB_USER": "chaos", "CHAOS_DB_PASSWORD": "pw-123456789", "CHAOS_WM_AUTH": "chaos:wm-123456789",
                      "CHAOS_GF_PASSWORD": "gf-123456789"}
        self.run_ctx = {"run_id": self.run_id, "prefix": self.prefix, "run_network": "net", "app_image": "x", "k6_script": "k6/orders.js"}
        self.obs_project, self.obs_up = f"{self.prefix}-obs", True
        self.events.add("obs-ready")

    def phase_fn(name):
        def fn(self, deadline):
            order.append((self.n, name))
            self.events.add(f"did-{name}")
            exc = plan.get((self.n, name))
            if exc:
                raise exc
            if name == "prepare":
                (self.rd / "compose.yaml").write_text("services: {}\n")
        return fn

    def fake_finish(self):
        c, v, cor, slo = verdicts.get(self.n, ("complete", "valid", "pass", "met"))
        if self.incomplete:
            c, v, cor, slo = "incomplete", "unknown", "unknown", "unknown"
        runner.write_json(self.rd / "repeat.json", {"schema_version": 1, "n": self.n, "phases": self.phases, "verdicts": {
            k: {"value": x, "reasons": []} for k, x in (("completion", c), ("validity", v), ("correctness", cor), ("slo", slo))}})
        return {"n": self.n, "completion": c, "validity": v, "correctness": cor, "slo": slo,
                "exclusion": [] if (c, v) == ("complete", "valid") else [self.incomplete or "invalid"], "values": {"p99_201_ms": 10.0 * self.n}}

    monkeypatch.setattr(runner.Run, "prepare_images", fake_prepare_images)
    monkeypatch.setattr(runner.Run, "start_obs", fake_start_obs)
    monkeypatch.setattr(runner.Run, "tool_versions", lambda self: {})
    for name in ("prepare", "warmup", "measured", "recovery", "collect"):
        monkeypatch.setattr(runner.Repeat, name, phase_fn(name))
    monkeypatch.setattr(runner.Repeat, "finish", fake_finish)
    monkeypatch.setattr(runner.Repeat, "salvage_logs", lambda self: None)
    monkeypatch.setattr(runner.Repeat, "stop_stats", lambda self: None)
    monkeypatch.setattr(runner, "machine_id", lambda: "machine-a")
    return order


def start(monkeypatch, repo, eng, *extra):
    monkeypatch.setattr("chaos.engine.Engine", lambda: eng)
    return main(["run", "external-api/api-slow", "--impl", "naive", *extra])


def the_run(repo):
    runs = list((repo / "results").iterdir())
    assert len(runs) == 1
    return runs[0], json.loads((runs[0] / "run.json").read_text())


@pytest.mark.parametrize("verdicts,code", [
    ({}, 0),
    ({2: ("complete", "valid", "fail", "met")}, 0),       # invariant fail does not change the exit code
    ({3: ("complete", "valid", "pass", "missed")}, 0),    # SLO miss neither
    ({1: ("complete", "valid", "unknown", "unknown")}, 0),
    ({4: ("complete", "invalid", "pass", "met")}, 1),
])
def test_exit_codes(repo, monkeypatch, verdicts, code):
    scripted(monkeypatch, verdicts=verdicts)
    eng = FlowEngine()
    assert start(monkeypatch, repo, eng) == code
    d, run = the_run(repo)
    assert run["exit_code"] == code and eng.lock is None and (d / "report.html").exists()
    assert run["identity"]["conditions"]["subprocess_env_names"] == ["CHAOS_DB_PASSWORD", "CHAOS_DB_USER", "CHAOS_GF_PASSWORD",
                                                                     "CHAOS_WM_AUTH", "DOCKER_HOST", "PATH"]
    assert "secret-host" not in (d / "run.json").read_text()  # docker info Name is never recorded


def test_invalid_and_incomplete_is_3_and_run_continues(repo, monkeypatch):
    order = scripted(monkeypatch, plan={(2, "measured"): runner.Incomplete("measured load exceeded its phase timeout")},
                     verdicts={4: ("complete", "invalid", "pass", "met")})
    eng = FlowEngine()
    assert start(monkeypatch, repo, eng) == 3
    _, run = the_run(repo)
    assert [r["completion"] for r in run["repeats"]] == ["complete", "incomplete", "complete", "complete", "complete"]
    assert run["repeats"][1]["validity"] == "unknown"
    assert (2, "recovery") not in order and (3, "prepare") in order  # cleaned up, then the next repeat ran
    assert f"{eng.lock}" == "None"


def test_phase_order_and_not_applicable_reason(repo, monkeypatch):
    order = scripted(monkeypatch)
    start(monkeypatch, repo, FlowEngine())
    d, _ = the_run(repo)
    assert [p for n, p in order if n == 1] == ["prepare", "warmup", "measured", "recovery", "collect"]
    rep = json.loads((d / "repeats/1/repeat.json").read_text())
    assert [p["name"] for p in rep["phases"]] == runner.PHASES
    assert rep["phases"][4]["not_applicable"].startswith("not applicable")
    assert all(p["timeout_s"] for p in rep["phases"] if p["name"] != "convergence")
    run_events = [json.loads(l)["kind"] for l in (d / "events.jsonl").read_text().splitlines()]
    assert run_events.index("images-ready") < run_events.index("obs-ready")


def test_each_repeat_gets_its_own_project_and_creation_waits_for_cleanup(repo, monkeypatch):
    scripted(monkeypatch)
    eng = FlowEngine()
    start(monkeypatch, repo, eng)
    downs = [c[1] for c in eng.calls if c[0] == "compose" and "down" in c]
    projects = [p for p in downs if not p.endswith("-obs")]
    assert len(set(projects[:5])) == 5 and all(p.endswith(f"-r{i}") for i, p in enumerate(projects[:5], 1))
    # repeat n's cleanup check (ps with its repeat label) comes before repeat n+1 starts its phases
    idx = [i for i, c in enumerate(eng.calls) if c[0] == "text" and "label=chaos-lab.repeat=1" in c]
    assert idx


def test_cleanup_failure_stops_run_keeps_lock_and_blocks_next_run(repo, monkeypatch):
    order = scripted(monkeypatch)
    eng = FlowEngine(leftovers={2: ["chaos-x-r2-db-1"]})
    assert start(monkeypatch, repo, eng) == 3
    _, run = the_run(repo)
    assert (3, "prepare") not in order
    assert [r["completion"] for r in run["repeats"]][2:] == ["not-run"] * 3
    assert eng.lock is not None and not run["cleanup"]["ok"]
    # the next run sees a leftover lock whose process is this (live) one -> refused before anything else
    eng2 = FlowEngine(lock=dict(eng.lock, **{"chaos-lab.pid": "999999999"}))
    assert start(monkeypatch, repo, eng2) == 3
    assert not any(c[0] == "compose" for c in eng2.calls)
    assert len(list((repo / "results").iterdir())) == 1


def test_capacity_shortfall_releases_lock_and_creates_nothing(repo, monkeypatch, capsys):
    scripted(monkeypatch)
    eng = FlowEngine(ncpu=4)
    assert start(monkeypatch, repo, eng) == 3
    assert "budgets are never shrunk" in capsys.readouterr().err
    assert eng.lock is None and not (repo / "results").exists()
    kinds = [c[1] for c in eng.calls if c[0] == "docker"]
    assert kinds == ["create", "rm"]


def test_engine_error_on_create_aborts(repo, monkeypatch):
    order = scripted(monkeypatch, plan={(1, "prepare"): EngineError("docker compose up: Error response from daemon")})
    eng = FlowEngine()
    assert start(monkeypatch, repo, eng) == 3
    _, run = the_run(repo)
    assert [r["completion"] for r in run["repeats"]] == ["incomplete"] + ["not-run"] * 4
    assert order == [(1, "prepare")] and eng.lock is None


@pytest.mark.parametrize("exc", [KeyboardInterrupt(), runner.Abort("fault apply on lookup failed: refused")])
def test_interrupt_or_fault_failure_records_partial_results(repo, monkeypatch, exc):
    scripted(monkeypatch, plan={(2, "measured"): exc})
    eng = FlowEngine()
    assert start(monkeypatch, repo, eng) == 3
    d, run = the_run(repo)
    assert [r["completion"] for r in run["repeats"]] == ["complete", "incomplete", "not-run", "not-run", "not-run"]
    assert all(r["exclusion"] for r in run["repeats"][1:])
    assert (d / "report.html").exists() and "incomplete" in (d / "report.html").read_text()
    downs = [c[1] for c in eng.calls if c[0] == "compose" and "down" in c]
    assert downs[-1].endswith("-obs")  # observability stack removed last, after repeat leftovers
    assert eng.lock is None


def test_run_json_is_finalized_after_cleanup(repo, monkeypatch):
    scripted(monkeypatch)
    eng = FlowEngine()
    seen = {}
    orig = runner.Run.write_run_json

    def spy(self, *a):
        seen["obs_down_before"] = any(c[0] == "compose" and c[1].endswith("-obs") and "down" in c for c in eng.calls)
        orig(self, *a)
    monkeypatch.setattr(runner.Run, "write_run_json", spy)
    start(monkeypatch, repo, eng)
    assert seen["obs_down_before"]


def test_prediction_copied_hashed_first_and_not_reread(repo, monkeypatch):
    scripted(monkeypatch)
    pred = repo / "notes.md"
    pred.write_text("naive will exhaust threads")
    orig_validate = runner.Run.make_dir

    def change_then_make_dir(self):
        pred.write_text("CHANGED AFTER VALIDATION")
        orig_validate(self)
    monkeypatch.setattr(runner.Run, "make_dir", change_then_make_dir)
    assert start(monkeypatch, repo, FlowEngine(), "--predict", str(pred)) == 0
    d, run = the_run(repo)
    assert (d / "inputs/predict/notes.md").read_text() == "naive will exhaust threads"
    ev = [json.loads(l) for l in (d / "events.jsonl").read_text().splitlines()]
    assert ev[0]["kind"] == "predict-copied" and len(ev[0]["sha256"]) == 64
    assert "naive will exhaust threads" in (d / "report.html").read_text()


def test_validity_does_not_depend_on_prediction(repo, monkeypatch):
    scripted(monkeypatch, verdicts={2: ("complete", "invalid", "pass", "met")})
    (repo / "p.md").write_text("x")
    a = start(monkeypatch, repo, FlowEngine(), "--predict", str(repo / "p.md"))
    b = start(monkeypatch, repo, FlowEngine())
    runs = sorted((repo / "results").iterdir())
    va = [r["validity"] for r in json.loads((runs[0] / "run.json").read_text())["repeats"]]
    vb = [r["validity"] for r in json.loads((runs[1] / "run.json").read_text())["repeats"]]
    assert a == b == 1 and va == vb


def test_results_dir_name_collision_gets_new_suffix(repo, monkeypatch):
    scripted(monkeypatch)
    ids = iter(["20261031-000000-external-api-api-slow-naive-aaaaaa", "20261031-000000-external-api-api-slow-naive-aaaaaa",
                "20261031-000000-external-api-api-slow-naive-bbbbbb"])
    monkeypatch.setattr(runner.Run, "new_run_id", lambda self: next(ids))
    orig = runner.Run.make_dir

    def collide(self):
        (self.root / "results" / "20261031-000000-external-api-api-slow-naive-aaaaaa").mkdir(parents=True)
        orig(self)
    monkeypatch.setattr(runner.Run, "make_dir", collide)
    eng = FlowEngine()
    assert start(monkeypatch, repo, eng) == 0
    assert (repo / "results/20261031-000000-external-api-api-slow-naive-bbbbbb/run.json").exists()
    assert not (repo / "results/20261031-000000-external-api-api-slow-naive-aaaaaa/run.json").exists()


def test_stdin_closed(repo):
    r = subprocess.run([sys.executable, "-c", "import sys; from chaos.cli import main; sys.exit(main(['run','nope/x','--impl','naive']))"],
                       cwd=repo, stdin=subprocess.DEVNULL, capture_output=True, env={"PYTHONPATH": str(ROOT), "PATH": "/usr/bin:/bin"})
    assert r.returncode == 2 and b"unknown problem" in r.stderr
