"""Report (AC-35, AC-39, AC-40, AC-41) and clean argument handling (AC-12)."""
import copy
import json
import shutil

import pytest

from chaos.cli import main
from chaos.report import render_runs

BASE_RUN = {
    "schema_version": 1, "run_id": "20261031-000000-external-api-api-slow-naive-aaaaaa", "problem": "external-api", "scenario": "api-slow",
    "impl": "naive", "impl_description": "waits long", "impl_extra_dependencies": [], "exit_code": 0, "error": None,
    "repeats": [{"n": i, "completion": "complete", "validity": "valid", "correctness": "pass", "slo": "missed", "exclusion": []} for i in range(1, 6)],
    "aggregate": {"planned": 5, "executed": 5, "complete": 5, "valid": 5, "not_full_five": False, "excluded": [],
                  "metrics": {"p99_201_ms": {"label": "median of per-repeat 201 p99 (ms)", "median": 812.0, "cv": 0.2, "n": 5, "investigate": True}}},
    "identity": {"engine": {"product": "OrbStack", "server_version": "29", "os_type": "linux", "architecture": "aarch64", "cpus": 10, "memory_bytes": 8 << 30},
                 "comparison": {"scenario_sha256": "s", "problem_sha256": "p", "workload": {"rate": 50}, "seed": 42, "contract": {"version": 1, "sha256": "c"}},
                 "harness": {"commit": "abc", "dirty": True}},
    "live_status": "ok", "live_reasons": [], "cleanup": {"ok": True, "left": []}, "predict": None,
}


def make_run(root, run_id=None, impl="naive", **changes):
    run = copy.deepcopy(BASE_RUN)
    run.update(changes)
    run["impl"] = impl
    run["run_id"] = run_id or run["run_id"].replace("naive", impl)
    d = root / "results" / run["run_id"]
    (d / "repeats/1").mkdir(parents=True)
    (d / "run.json").write_text(json.dumps(run))
    (d / "repeats/1/repeat.json").write_text(json.dumps({"schema_version": 1, "n": 1, "phases": [], "verdicts": {
        k: {"value": v, "reasons": []} for k, v in (("completion", "complete"), ("validity", "valid"), ("correctness", "pass"), ("slo", "missed"))},
        "recovery": {"applicable": True, "time_to_recovery_ms": 994}, "observability_usage": {"alloy": {"cpu_mean_pct": 3.0}}}))
    return d


def test_report_reproduces_run_report_and_leaves_results_alone(repo, capsys):
    d = make_run(repo)
    (d / "report.html").write_text(render_runs([d]), encoding="utf-8")
    before = {p: p.read_bytes() for p in d.rglob("*") if p.is_file()}
    assert main(["report", str(d.relative_to(repo))]) == 0
    out = capsys.readouterr().out.strip()
    assert out.startswith("reports/") and out.endswith(".html")
    assert (repo / out).read_bytes() == (d / "report.html").read_bytes()
    assert {p: p.read_bytes() for p in d.rglob("*") if p.is_file()} == before
    assert main(["report", str(d)]) == 0
    assert len(list((repo / "reports").iterdir())) == 2  # never overwritten


def test_report_contents(repo):
    d = make_run(repo, aggregate=dict(BASE_RUN["aggregate"], valid=3, not_full_five=True,
                                      excluded=[{"n": 4, "reasons": ["dropped_iterations=3"]}]),
                 impl_extra_dependencies=[{"name": "cache", "budget": {"cpus": 0.5, "memory_mib": 256}}])
    (d / "inputs/predict").mkdir(parents=True)
    (d / "inputs/predict/p.md").write_text("threads will run out")
    run = json.loads((d / "run.json").read_text())
    run["predict"] = "inputs/predict/p.md"
    (d / "run.json").write_text(json.dumps(run))
    html = render_runs([d])
    for s in ("완전한 5회 결과 아님", "조사 신호", "threads will run out", "waits long", "cache (0.5 CPU / 256 MiB)",
              "observability stack stays up", "uv run chaos run external-api/api-slow --impl naive", "(dirty)", "not applicable"):
        assert s in html, s
    assert "/Users/" not in html and str(repo) not in html


def test_same_layout_for_partial_runs(repo):
    d = make_run(repo, exit_code=3, error="interrupted",
                 repeats=[{"n": 1, "completion": "incomplete", "validity": "unknown", "exclusion": ["run stopped"]}] +
                         [{"n": i, "completion": "not-run", "validity": "unknown", "exclusion": ["not run"]} for i in range(2, 6)])
    html = render_runs([d])
    assert "not-run" in html and "interrupted" in html


def test_compare_same_identity(repo, capsys):
    a, b = make_run(repo), make_run(repo, impl="timeout")
    assert main(["report", str(a), str(b)]) == 0
    html = (repo / capsys.readouterr().out.strip()).read_text()
    assert "Comparison" in html and html.count("<h2>") >= 3


def test_compare_refuses_different_identity(repo, capsys):
    a = make_run(repo)
    ident = copy.deepcopy(BASE_RUN["identity"])
    ident["comparison"]["seed"] = 7
    b = make_run(repo, impl="timeout", identity=ident)
    assert main(["report", str(a), str(b)]) == 2
    assert "comparison identity" in capsys.readouterr().err
    assert main(["report", str(a), str(b), "--allow-cross-env"]) == 2


def test_cross_env_only_with_flag_and_never_ranked(repo, capsys):
    a = make_run(repo)
    ident = copy.deepcopy(BASE_RUN["identity"])
    ident["engine"]["product"] = "Docker Desktop"
    b = make_run(repo, impl="timeout", identity=ident)
    assert main(["report", str(a), str(b)]) == 2
    capsys.readouterr()
    assert main(["report", str(a), str(b), "--allow-cross-env"]) == 0
    html = (repo / capsys.readouterr().out.strip()).read_text()
    assert "No winner or ranking" in html and "<h2>Comparison</h2>" not in html


def test_report_errors(repo):
    assert main(["report", "results/nope"]) == 2
    d = make_run(repo)
    bad = json.loads((d / "run.json").read_text())
    bad["schema_version"] = 99
    (d / "run.json").write_text(json.dumps(bad))
    assert main(["report", str(d)]) == 2
    bad["schema_version"] = 1
    bad["exit_code"] = "zero"
    (d / "run.json").write_text(json.dumps(bad))
    assert main(["report", str(d)]) == 2


def test_clean_rejects_malformed_run_id(repo, capsys):
    assert main(["clean", "--run", "../../etc"]) == 2
    assert "malformed run id" in capsys.readouterr().err
