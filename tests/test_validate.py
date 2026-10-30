"""Pre-run rejection (AC-3, AC-4, AC-5): exit 2, no engine call, no results directory."""
import os
import re
from pathlib import Path

import pytest
from hypothesis import given, strategies as st

from chaos import yamlload
from chaos.cli import main
from chaos.validate import Rejected, check_id, schema_errors, validate
from conftest import FakeEngine, ROOT

P = Path("problems/external-api")
IMPL = P / "impls/naive/impl.yaml"
SCEN = P / "scenarios/api-slow/scenario.yaml"
PROB = P / "problem.yaml"


def edit(path, old, new):
    t = path.read_text(encoding="utf-8")
    assert old in t, f"{old!r} not in {path}"
    path.write_text(t.replace(old, new, 1), encoding="utf-8")


def rejected(capsys, *argv, why):
    assert main(["run", *argv]) == 2
    err = capsys.readouterr().err
    assert re.search(why, err), err
    assert FakeEngine.instances == []  # the engine boundary is never created, so no call can happen
    assert not Path("results").exists()


def test_valid_closure_passes(repo):
    spec = validate(repo, "external-api/api-slow", "naive")
    assert spec["prices"]["p-001"] == 1500


CASES = [
    # (description, mutation, argv, expected reason)
    ("unknown problem", None, ["nope/api-slow", "--impl", "naive"], "unknown problem"),
    ("unknown scenario", None, ["external-api/nope", "--impl", "naive"], "unknown scenario"),
    ("unknown impl", None, ["external-api/api-slow", "--impl", "nope"], "unknown impl"),
    ("bad target", None, ["external-api", "--impl", "naive"], "expected <problem>/<scenario>"),
    ("schema", (SCEN, "rate: 50", "rate: fast"), None, "schema violation"),
    ("contract version", (SCEN, "contract_version: 1", "contract_version: 2"), None, "schema violation"),
    ("action", (SCEN, "action: latency", "action: corrupt"), None, "schema violation"),
    ("dependency kind", (PROB, "kind: postgres", "kind: mysql"), None, "schema violation"),
    ("missing asset", (SCEN, "script: ../../k6/orders.js", "script: ../../k6/missing.js"), None, "missing asset"),
    ("case mismatch", (SCEN, "script: ../../k6/orders.js", "script: ../../k6/Orders.js"), None, "missing asset"),
    ("backslash", (SCEN, "script: ../../k6/orders.js", 'script: "..\\\\..\\\\k6\\\\orders.js"'), None, "bad asset reference|schema violation"),
    ("absolute", (SCEN, "script: ../../k6/orders.js", "script: /etc/passwd"), None, "bad asset reference"),
    ("outside problem", (SCEN, "script: ../../k6/orders.js", "script: ../../../../chaos-contract.yaml"), None, "outside the problem"),
    ("leading zero", (SCEN, "seed: 42", "seed: 042"), None, "forbidden YAML"),
    ("anchor", (SCEN, "rate: 50", "rate: &r 50"), None, "forbidden YAML"),
    ("duplicate key", (SCEN, "rate: 50", "rate: 50\n  rate: 60"), None, "forbidden YAML"),
    ("tag", (SCEN, "rate: 50", "rate: !!int 50"), None, "forbidden YAML"),
    ("unknown field", (PROB, "invariants:", "x_flag: no\ninvariants:"), None, "schema violation"),
    ("id/dir mismatch", (IMPL, "id: naive", "id: timeout"), None, "does not match directory"),
    ("reserved dependency", (PROB, "name: lookup", "name: toxiproxy"), None, "reserved"),
    ("reserved prefix", (PROB, "name: lookup", "name: chaos-lookup"), None, "reserved"),
    ("windows device", (PROB, "name: lookup", "name: aux"), None, "reserved Windows"),
    ("unknown reference", (IMPL, "${chaos.run_id}", "${chaos.secret}"), None, "unknown runtime reference"),
    ("unknown dep reference", (IMPL, "${chaos.dep.db.user}", "${chaos.dep.cache.user}"), None, "unknown dependency"),
    ("fault target", (SCEN, "target: lookup", "target: cache"), None, "not a dependency"),
    ("proxy bypass", (IMPL, "http://${chaos.dep.lookup.host}:${chaos.dep.lookup.port}", "http://lookup:8080"), None, "bypasses Toxiproxy"),
    ("budget cap", (PROB, "budget: {cpus: 0.5, memory_mib: 512}", "budget: {cpus: 0.9, memory_mib: 512}"), None, "exceed the cap"),
    ("openapi error", (P / "lookup-openapi.yaml", "openapi: 3.1.0", "openapi: 9.9.9"), None, "OpenAPI error"),
    ("stub contract", (P / "stubs/products.json", '"price": 1500', '"price": "1500"'), None, "violates the contract"),
    ("stub path", (P / "stubs/products.json", '"/products/p-001"', '"/items/p-001"'), None, "not in the OpenAPI"),
]


@pytest.mark.parametrize("name,mutation,argv,why", CASES, ids=[c[0] for c in CASES])
def test_rejections(repo, capsys, name, mutation, argv, why):
    if mutation:
        edit(*mutation)
    rejected(capsys, *(argv or ["external-api/api-slow", "--impl", "naive"]), why=why)


def test_symlinked_asset(repo, capsys):
    (P / "k6/link.js").symlink_to("orders.js")
    edit(SCEN, "script: ../../k6/orders.js", "script: ../../k6/link.js")
    rejected(capsys, "external-api/api-slow", "--impl", "naive", why="symlinked asset")


def test_unreadable_predict(repo, capsys):
    rejected(capsys, "external-api/api-slow", "--impl", "naive", "--predict", "nope.md", why="cannot read --predict")


def test_bad_id_on_command_line(repo, capsys):
    rejected(capsys, "external-api/Api-Slow", "--impl", "naive", why="invalid scenario id")


def test_broken_sibling_problem_does_not_block(repo):
    """AC-4: only the selected closure is validated."""
    bad = Path("problems/broken")
    bad.mkdir()
    (bad / "problem.yaml").write_text("contract_version: 9\nid: [oops\n")
    sib = P / "scenarios/wip"
    sib.mkdir()
    (sib / "scenario.yaml").write_text("this: is: not valid\n")
    assert validate(repo, "external-api/api-slow", "naive")["scenario"]["id"] == "api-slow"


def test_sibling_directory_name_is_checked(repo):
    sib = P / "scenarios/Bad_Name"
    sib.mkdir()
    (sib / "scenario.yaml").write_text("x: 1\n")
    with pytest.raises(Rejected, match="invalid scenario id"):
        validate(repo, "external-api/api-slow", "naive")


EXAMPLES = sorted((ROOT / "schemas/examples").glob("*/*/*.yaml"))


@pytest.mark.parametrize("path", EXAMPLES, ids=[f"{p.parts[-3]}/{p.parts[-2]}/{p.name}" for p in EXAMPLES])
def test_schema_examples(path):
    """AC-5: every committed example is judged as its folder says, by YAML rules plus the schema alone."""
    schema_name, expect = path.parts[-3], path.parts[-2]
    try:
        ok = not schema_errors(schema_name, yamlload.load(path))
    except yamlload.YamlError:
        ok = False
    assert ok == (expect == "valid")


def test_example_set_covers_required_cases():
    names = {f"{p.parts[-3]}/{p.parts[-2]}/{p.name}" for p in EXAMPLES}
    assert {"contract/invalid/leading-zero.yaml", "run/invalid/dirty-no.yaml", "run/invalid/dirty-off.yaml",
            "impl/valid/id-no.yaml", "impl/invalid/id-trailing-newline.yaml"} <= names
    assert {p.parts[-3] for p in EXAMPLES} == {p.name.split(".")[0] for p in (ROOT / "schemas").glob("*.schema.json")}


ID_SCHEMA_PROBE = {"contract_version": 1, "id": None, "problem": "p", "workload": {"script": "a.js", "rate": 1, "warmup_s": 1,
                   "measured_s": 1, "graceful_stop_s": 1, "timeout_s": 1, "seed": 0}, "faults": [],
                   "phase_timeouts_s": dict.fromkeys(["prepare", "warmup", "measured", "recovery", "collect", "cleanup"], 1)}


@given(st.text(max_size=45))
def test_id_rule_property(s):
    """Schema pattern (ECMA semantics) and the harness id check agree; trailing newline and control chars never pass."""
    probe = dict(ID_SCHEMA_PROBE, id=s)
    schema_ok = not schema_errors("scenario", probe)
    expect = bool(re.fullmatch(r"[a-z][a-z0-9-]*", s)) and len(s) <= 40
    assert schema_ok == expect
    try:
        check_id(s, "x")
        harness_ok = True
    except Rejected:
        harness_ok = False
    assert harness_ok == (expect and s not in {"con", "prn", "aux", "nul"} and not re.fullmatch(r"(com|lpt)[1-9]", s))


@given(st.from_regex(r"[a-z][a-z0-9-]{0,10}", fullmatch=True).map(lambda s: s + "\n"))
def test_trailing_newline_ids_rejected(s):
    assert schema_errors("scenario", dict(ID_SCHEMA_PROBE, id=s))


@given(st.from_regex(r"[-+]?0[0-9]{1,6}", fullmatch=True))
def test_leading_zero_ints_rejected(s):
    with pytest.raises(yamlload.YamlError):
        yamlload.loads(f"a: {s}")


@given(st.sampled_from(["no", "off", "yes", "on", "y", "n", "NO", "Off"]))
def test_yaml11_booleans_stay_strings(s):
    assert yamlload.loads(f"a: {s}") == {"a": s}
