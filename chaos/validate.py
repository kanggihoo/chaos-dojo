"""Pre-run validation. Everything here runs before any engine call; failures exit 2."""
import json
import re
from pathlib import Path

from jsonschema import Draft202012Validator, validators
from jsonschema.exceptions import ValidationError
from openapi_spec_validator import validate as validate_openapi

from . import yamlload

ROOT_SCHEMAS = Path(__file__).resolve().parent.parent / "schemas"
ID_RE = re.compile(r"[a-z][a-z0-9-]*")
WINDOWS_RESERVED = {"con", "prn", "aux", "nul"} | {f"com{i}" for i in range(1, 10)} | {f"lpt{i}" for i in range(1, 10)}
RESERVED = {"alloy", "lgtm", "toxiproxy", "k6"}
REF_RE = re.compile(r"\$\{([^}]*)\}")
DEP_REF = re.compile(r"chaos\.dep\.([a-z][a-z0-9-]*)\.(host|port|user|password)")
OTHER_REFS = {"chaos.otlp.endpoint", "chaos.run_id", "chaos.repeat"}


class Rejected(Exception):
    """Input rejected before the run starts (exit 2)."""


def _ecma_pattern(validator, pattern, instance, schema):
    # ECMA-262 without the multiline flag: `$` matches only at the end of input, unlike Python's re.
    if isinstance(instance, str) and not re.search(re.sub(r"(?<!\\)\$", r"\\Z", pattern), instance):
        yield ValidationError(f"{instance!r} does not match {pattern!r}")


Validator = validators.extend(Draft202012Validator, {"pattern": _ecma_pattern})


def schema(name):
    return json.loads((ROOT_SCHEMAS / f"{name}.schema.json").read_text(encoding="utf-8"))


def schema_errors(name, data):
    return [f"{'/'.join(map(str, e.absolute_path)) or '(root)'}: {e.message}" for e in Validator(schema(name)).iter_errors(data)]


def check_id(value, what):
    if not isinstance(value, str) or not ID_RE.fullmatch(value) or len(value) > 40:
        raise Rejected(f"invalid {what} id {value!r}: must match ^[a-z][a-z0-9-]*$, at most 40 chars")
    if value in WINDOWS_RESERVED:
        raise Rejected(f"{what} id {value!r} is a reserved Windows device name")


def check_not_reserved(value, what):
    if value in RESERVED or value.startswith("chaos-"):
        raise Rejected(f"{what} name {value!r} is reserved for the harness")


def load_manifest(path, schema_name):
    if not path.is_file():
        raise Rejected(f"missing {path.as_posix()}")
    try:
        data = yamlload.load(path)
    except (yamlload.YamlError, UnicodeDecodeError) as e:
        raise Rejected(f"{path.as_posix()}: forbidden YAML: {e}") from None
    errs = schema_errors(schema_name, data)
    if errs:
        raise Rejected(f"{path.as_posix()}: schema violation: " + "; ".join(errs))
    return data


def asset(problem_dir, manifest_path, ref):
    """Resolve an asset reference: relative, `/` only, inside the problem dir, ASCII, exact case, no symlinks."""
    if "\\" in ref or ref.startswith("/") or re.match(r"^[A-Za-z]:", ref) or not ref.isascii():
        raise Rejected(f"{manifest_path.as_posix()}: bad asset reference {ref!r}")
    p = manifest_path.parent
    for part in ref.split("/"):
        if part in ("", "."):
            raise Rejected(f"{manifest_path.as_posix()}: bad asset reference {ref!r}")
        if part == "..":
            p = p.parent
            continue
        if not p.is_dir() or part not in {c.name for c in p.iterdir()}:
            raise Rejected(f"{manifest_path.as_posix()}: missing asset {ref!r} (names are case-sensitive)")
        p = p / part
        if p.is_symlink():
            raise Rejected(f"{manifest_path.as_posix()}: symlinked asset {ref!r}")
    root = problem_dir.resolve()
    if p.resolve() != root and root not in p.resolve().parents:
        raise Rejected(f"{manifest_path.as_posix()}: asset {ref!r} is outside the problem directory")
    return p


def check_refs(text, deps, where):
    for ref in REF_RE.findall(text):
        m = DEP_REF.fullmatch(ref)
        if m:
            if m.group(1) not in deps:
                raise Rejected(f"{where}: reference to unknown dependency in ${{{ref}}}")
        elif ref not in OTHER_REFS:
            raise Rejected(f"{where}: unknown runtime reference ${{{ref}}}")
    stripped = REF_RE.sub("", text)
    for d in deps:
        if re.search(rf"(//|@){re.escape(d)}([:/]|$)|(^|[^a-z0-9.-]){re.escape(d)}:[0-9]", stripped):
            raise Rejected(f"{where}: direct address of dependency {d!r} bypasses Toxiproxy; use ${{chaos.dep.{d}.host}}")


def _openapi(problem_dir, manifest_path, ref):
    p = asset(problem_dir, manifest_path, ref)
    try:
        doc = yamlload.load(p)
        validate_openapi(doc)
    except Exception as e:  # noqa: BLE001 - any parse/validation failure is an input rejection
        raise Rejected(f"{p.as_posix()}: OpenAPI error: {e}") from None
    return doc


def _match_path(template, path):
    rx = "^" + re.sub(r"\\\{[^}]+\\\}", "[^/]+", re.escape(template)) + "$"
    return re.match(rx, path)


def check_stubs(stub_dir, openapi):
    for f in sorted(stub_dir.glob("*.json")):
        try:
            mappings = json.loads(f.read_text(encoding="utf-8"))
        except ValueError as e:
            raise Rejected(f"{f.as_posix()}: invalid JSON: {e}") from None
        for m in mappings.get("mappings", [mappings]):
            req, res = m.get("request", {}), m.get("response", {})
            url = req.get("url") or req.get("urlPath")
            method = req.get("method", "GET").lower()
            ops = [ops for tmpl, ops in openapi["paths"].items() if url and _match_path(tmpl, url)]
            if not ops or method not in ops[0]:
                raise Rejected(f"{f.as_posix()}: stub {method.upper()} {url} is not in the OpenAPI contract")
            resp = ops[0][method]["responses"].get(str(res.get("status", 200)))
            if resp is None:
                raise Rejected(f"{f.as_posix()}: stub {url} status {res.get('status')} is not in the OpenAPI contract")
            body_schema = resp.get("content", {}).get("application/json", {}).get("schema")
            if body_schema is not None:
                errs = [e.message for e in Validator(body_schema).iter_errors(res.get("jsonBody"))]
                if errs:
                    raise Rejected(f"{f.as_posix()}: stub {url} response violates the contract: {'; '.join(errs)}")


def stub_prices(stub_dir, key, field):
    prices = {}
    for f in sorted(stub_dir.glob("*.json")):
        for m in json.loads(f.read_text(encoding="utf-8")).get("mappings", []):
            body = m.get("response", {}).get("jsonBody") or {}
            if key in body and field in body:
                prices[body[key]] = body[field]
    return prices


def validate(root, target, impl_id, predict=None):
    """Validate the selected closure and return everything the run needs. Raises Rejected."""
    root = Path(root)
    if "/" not in target:
        raise Rejected(f"expected <problem>/<scenario>, got {target!r}")
    problem_id, scenario_id = target.split("/", 1)
    for v, what in ((problem_id, "problem"), (scenario_id, "scenario"), (impl_id, "impl")):
        check_id(v, what)

    contract = load_manifest(root / "chaos-contract.yaml", "contract")
    pdir = root / "problems" / problem_id
    if not (pdir / "problem.yaml").is_file():
        raise Rejected(f"unknown problem {problem_id!r}")
    problem = load_manifest(pdir / "problem.yaml", "problem")
    if problem["id"] != problem_id:
        raise Rejected(f"problem.yaml id {problem['id']!r} does not match directory {problem_id!r}")

    # Siblings: directory names only (id rule and uniqueness come from the filesystem).
    for kind, manifest in (("scenarios", "scenario.yaml"), ("impls", "impl.yaml")):
        for d in (pdir / kind).iterdir() if (pdir / kind).is_dir() else []:
            if (d / manifest).is_file():
                check_id(d.name, kind[:-1])

    sdir, idir = pdir / "scenarios" / scenario_id, pdir / "impls" / impl_id
    if not (sdir / "scenario.yaml").is_file():
        raise Rejected(f"unknown scenario {target!r}")
    if not (idir / "impl.yaml").is_file():
        raise Rejected(f"unknown impl {impl_id!r} for problem {problem_id!r}")
    scenario = load_manifest(sdir / "scenario.yaml", "scenario")
    impl = load_manifest(idir / "impl.yaml", "impl")
    for m, d, what in ((scenario, sdir, "scenario"), (impl, idir, "impl")):
        if m["id"] != d.name or m["problem"] != problem_id:
            raise Rejected(f"{what}.yaml id/problem ({m['id']}/{m['problem']}) does not match directory {problem_id}/{d.name}")

    deps = problem["dependencies"] + impl["extra_dependencies"]
    names = [d["name"] for d in deps]
    for n in names:
        check_id(n, "dependency")
        check_not_reserved(n, "dependency")
    check_not_reserved(impl_id, "impl")
    if len(set(names)) != len(names):
        raise Rejected(f"duplicate dependency names: {names}")
    if "app" in names:
        raise Rejected("dependency name 'app' is reserved for the impl service")

    ppath = pdir / "problem.yaml"
    assets = {"openapi": _openapi(pdir, ppath, problem["openapi"])}
    for d in problem["dependencies"]:
        if d["kind"] == "postgres":
            asset(pdir, ppath, d["schema"])
        else:
            doc = _openapi(pdir, ppath, d["openapi"])
            stubs = asset(pdir, ppath, d["stubs"])
            if not stubs.is_dir():
                raise Rejected(f"stubs {d['stubs']!r} is not a directory")
            check_stubs(stubs, doc)
    if problem["store"]["dependency"] not in names:
        raise Rejected(f"store dependency {problem['store']['dependency']!r} is not declared")
    lookups = [d for d in problem["dependencies"] if d["kind"] == "http-fake"]
    prices = stub_prices(asset(pdir, ppath, lookups[0]["stubs"]), problem["store"]["price_key"], problem["store"]["price_field"]) if lookups else {}

    budget_cpu = sum(d["budget"]["cpus"] for d in problem["dependencies"]) + problem["proxy_budget"]["cpus"]
    budget_mem = sum(d["budget"]["memory_mib"] for d in problem["dependencies"]) + problem["proxy_budget"]["memory_mib"]
    cap = contract["budgets"]["problem_deps_max"]
    if budget_cpu > cap["cpus"] + 1e-9 or budget_mem > cap["memory_mib"]:
        raise Rejected(f"problem dependency budgets ({budget_cpu} CPU / {budget_mem} MiB) exceed the cap ({cap['cpus']} / {cap['memory_mib']})")

    asset(pdir, sdir / "scenario.yaml", scenario["workload"]["script"])
    w = scenario["workload"]
    for f in scenario["faults"]:
        if f["target"] not in names:
            raise Rejected(f"fault targets {f['target']!r}, which is not a dependency of this problem/impl")
        if not f["apply_at_s"] < f["remove_at_s"] <= w["measured_s"]:
            raise Rejected(f"fault window {f['apply_at_s']}..{f['remove_at_s']} s must be ordered and inside measured load")

    ipath = idir / "impl.yaml"
    if "build" in impl["image"]:
        b = asset(pdir, ipath, impl["image"]["build"])
        if not (b / "Dockerfile").is_file():
            raise Rejected(f"{ipath.as_posix()}: build context {impl['image']['build']!r} has no Dockerfile")
    asset(pdir, ipath, impl["provenance"])
    for k, v in impl["env"].items():
        check_refs(v, names, f"{ipath.as_posix()} env {k}")
    if impl["ports"]["business"] == impl["ports"]["management"]:
        raise Rejected("business and management ports must differ")

    predict_bytes = None
    if predict is not None:
        try:
            predict_bytes = Path(predict).read_bytes()
        except OSError as e:
            raise Rejected(f"cannot read --predict file: {e.strerror}") from None

    return {
        "root": root, "contract": contract, "problem": problem, "scenario": scenario, "impl": impl,
        "problem_dir": pdir, "scenario_dir": sdir, "impl_dir": idir, "deps": deps, "prices": prices,
        "predict": predict_bytes, "predict_name": Path(predict).name if predict else None, **assets,
    }
