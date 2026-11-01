"""Checks over real recorded runs in results/ (AC-8, AC-13, AC-15, AC-19, AC-20, AC-25, AC-30, AC-31, AC-33, AC-35..AC-38).

Runs only when results exist; `uv run pytest -m e2e`.
"""
import getpass
import hashlib
import json
import os
import re
import socket
from pathlib import Path

import pytest
import yaml

from chaos.engine import ENV_ALLOW
from chaos.report import render_runs
from conftest import ROOT

pytestmark = pytest.mark.e2e
RUNS = sorted(p for p in (ROOT / "results").glob("*") if (p / "run.json").exists()) if (ROOT / "results").exists() else []


def runs():
    if not RUNS:
        pytest.skip("no recorded runs")
    return RUNS


def j(p):
    return json.loads(Path(p).read_text())


@pytest.mark.parametrize("run", RUNS, ids=[p.name for p in RUNS])
def test_recorded_run(run):
    r = j(run / "run.json")
    ident = r["identity"]
    # AC-38: identity
    assert set(ident["engine"]) == {"product", "server_version", "os_type", "architecture", "cpus", "memory_bytes"}
    assert {"scenario_sha256", "problem_sha256", "workload", "seed", "contract"} <= set(ident["comparison"])
    assert {"commit", "dirty"} <= set(ident["harness"]) and ident["images"]["app"]["image_id"].startswith("sha256:")
    for name, img in ident["images"].items():
        if name != "app":
            assert img["index_digest"].startswith("sha256:") and img["platform"] and img["image_id"]
    # AC-13
    names = ident["conditions"].get("subprocess_env_names")
    if names is not None:
        assert set(names) <= set(ENV_ALLOW) | {"DOCKER_HOST", "CHAOS_DB_USER", "CHAOS_DB_PASSWORD", "CHAOS_WM_AUTH", "CHAOS_GF_PASSWORD"}
    # AC-35: report reproduced from files only
    assert (run / "report.html").read_text() == render_runs([run])
    projects = set()
    for rep in r["repeats"]:
        d = run / "repeats" / str(rep["n"])
        if rep["completion"] == "not-run":
            continue
        doc = j(d / "repeat.json")
        if rep["completion"] != "complete":
            continue
        for f in ("repeat.json", "compose.yaml", "events.jsonl", "checks.json"):
            assert (d / f).exists(), f
        assert any((d / "k6").iterdir()) and any((d / "metrics").iterdir()) and any((d / "logs").iterdir())
        # AC-8
        text = (d / "compose.yaml").read_text()
        assert hashlib.sha256(text.encode()).hexdigest() == doc["compose_sha256"]
        c = yaml.safe_load(text)
        projects.add(c["name"])
        for svc in c["services"].values():
            for v in svc.get("volumes", []):
                src = v.split(":", 1)[0]
                assert not src.startswith("/") or src == "/var/run/docker.sock", v
        # AC-15
        assert [p["name"] for p in doc["phases"]] == ["prepare", "warmup", "measured", "recovery", "convergence", "collect", "cleanup"]
        # AC-19
        for f in doc["faults"]:
            assert {"planned_ms", "dispatched_ms", "confirmed_ms"} <= set(f) and f["result"] == "ok"
        # AC-20
        assert {p["name"] for p in doc["topology"]["proxies"].values()} == {"db", "lookup"}
        iso = doc["topology"].get("api_isolation")
        if iso is not None:  # runs recorded before the isolation probe existed lack it
            assert iso["reachable"] == [] and all(iso["control_ok"].values()) and set(iso["control_ok"]) == {"app", "k6"}
        env = c["services"]["app"]["environment"]
        assert "toxiproxy:" in env["DB_URL"] and "toxiproxy:" in env["LOOKUP_BASE_URL"]
        # AC-25
        if doc["recovery"]["applicable"]:
            assert doc["verdicts"]["slo"]["issued"] == doc["cohorts"]["measured"]
        # AC-30
        res = doc["app"]["resolved"]
        assert res["spring.threads.virtual.enabled"] == "false" and res["actual.business.max-threads"] == 50
        # AC-31: no request id label anywhere in exported metrics
        for m in (d / "metrics").glob("*.json"):
            assert "request_id" not in m.read_text() and "requestId" not in m.read_text()
        # AC-33
        kinds = [e["kind"] for e in map(json.loads, (d / "events.jsonl").read_text().splitlines())]
        assert kinds.index("first-scrape-ok") < kinds.index("phase-start", kinds.index("phase-end"))
        assert doc["scrape_targets"][0]["network"].endswith("-run")
        # AC-36
        assert {"offset_ms", "rtt_ms"} <= set(doc["clock_start"]) and {"offset_ms", "rtt_ms"} <= set(doc["clock_end"])
    assert len(projects) == len({p for p in projects})  # distinct per repeat


@pytest.mark.parametrize("run", RUNS, ids=[p.name for p in RUNS])
def test_no_forbidden_strings(run):
    """AC-37: generated result files carry no home path, user, host name, credentials or tokens."""
    home, host, user = os.path.expanduser("~"), socket.gethostname(), getpass.getuser()
    for p in run.rglob("*"):
        rel = p.relative_to(run).as_posix()
        if not p.is_file() or rel.startswith("inputs/"):
            continue
        data = p.read_bytes()
        assert home.encode() not in data, rel
        assert host.encode() not in data, rel
        assert not re.search(rb"glsa_[A-Za-z0-9_]{20,}", data), rel
        assert not re.search(rb"/(Users|home)/" + re.escape(user.encode()), data), rel


def test_impls_differ_only_in_wait_policy():
    by_impl = {}
    for run in runs():
        r = j(run / "run.json")
        rep = next((run / "repeats" / str(x["n"]) for x in r["repeats"] if x["completion"] == "complete"), None)
        if rep and r["identity"]["images"]["app"].get("build_flags"):  # runs before reproducible builds cannot share an ID
            by_impl[r["impl"]] = (j(rep / "repeat.json")["app"], r["identity"]["images"]["app"]["image_id"])
    if len(by_impl) < 2:
        pytest.skip("needs runs of both impls")
    (a, ia), (b, ib) = by_impl["naive"], by_impl["timeout"]
    policy = {"chaos.impl", "chaos.lookup.deadline-ms", "chaos.lookup.response-timeout-ms"}
    assert {k: v for k, v in a["resolved"].items() if k not in policy} == {k: v for k, v in b["resolved"].items() if k not in policy}
    assert ia == ib  # same image


def test_management_port_survives_worker_exhaustion():
    """AC-31: in naive api-slow, scrapes succeed while every business thread is busy."""
    for run in runs():
        r = j(run / "run.json")
        if (r["impl"], r["scenario"]) != ("naive", "api-slow"):
            continue
        for x in r["repeats"]:
            m = run / "repeats" / str(x["n"]) / "metrics"
            if not (m / "tomcat_threads_busy_threads.json").exists():
                continue
            busy = {t: float(v) for s in j(m / "tomcat_threads_busy_threads.json") for t, v in s["values"]}
            mx = {t: float(v) for s in j(m / "tomcat_threads_config_max_threads.json") for t, v in s["values"]}
            up = {t: float(v) for s in j(m / "up.json") for t, v in s["values"]}
            exhausted = [t for t in busy if t in mx and busy[t] >= mx[t]]
            assert exhausted, "business threads never reached the maximum"
            assert all(up.get(t, 1) == 1 for t in exhausted)
            return
    pytest.skip("no naive api-slow run")
