"""Warmup boundary order (AC-16) and non-blocking annotations around fault actions (AC-26)."""
import json
import queue
import socket
import threading
import time

import pytest

from chaos import runner


class Stub:
    pass


def test_warmup_boundary_sequence(tmp_path, monkeypatch):
    calls = []
    rp = runner.Repeat.__new__(runner.Repeat)
    rp.n, rp.rd, rp.invalid = 1, tmp_path, []
    rp.events = runner.Events(tmp_path / "events.jsonl")
    r = rp.r = Stub()
    r.problem = {"store": {"dependency": "db", "table": "orders"}}
    r.spec = {"deps": [{"name": "db", "kind": "postgres"}, {"name": "lookup", "kind": "http-fake"}]}
    r.creds = {"CHAOS_WM_AUTH": "chaos:x"}
    r.annotate = lambda *a, **k: calls.append("annotate")
    rp.dep_addr = {"db": "127.0.0.1:1", "lookup": "127.0.0.1:2"}
    rp.start_k6 = lambda phase: calls.append(f"k6-{phase}")
    rp.wait_k6 = lambda d, w: calls.append("k6-exit")
    rp.quiescent = lambda cohorts: calls.append(f"quiescence-{cohorts}") or False

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql):
            calls.append(sql)
    rp.db_connect = lambda addr, db: Conn()
    monkeypatch.setattr(runner, "http", lambda m, url, *a, **k: calls.append(f"{m} {url.split('/', 3)[-1]}"))
    rp.warmup(None)
    assert calls[:6] == ["k6-warmup", "k6-exit", "quiescence-['warmup']", "DELETE FROM orders", "DELETE __admin/requests", "annotate"]
    kinds = [json.loads(l)["kind"] for l in (tmp_path / "events.jsonl").read_text().splitlines()]
    assert kinds == ["quiescence", "orders-cleared", "journal-cleared", "boundary"]
    assert rp.invalid == ["warmup cohort did not reach quiescence within 30 s"]  # recorded; the phase still went on


def test_annotations_never_delay_fault_actions(tmp_path, monkeypatch):
    # a Grafana that accepts connections and never answers
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(100)
    hung = []
    threading.Thread(target=lambda: [hung.append(srv.accept()) for _ in range(100)], daemon=True).start()

    run = runner.Run.__new__(runner.Run)
    run.contract = {"live": {"annotation_queue": 3, "annotation_timeout_s": 2}}
    run.annotations = queue.Queue(maxsize=3)
    run.live = {"status": "ok", "reasons": []}
    run.grafana = {"url": f"http://127.0.0.1:{srv.getsockname()[1]}", "token": "t"}
    threading.Thread(target=run.annotation_worker, daemon=True).start()

    rp = runner.Repeat.__new__(runner.Repeat)
    rp.r, rp.n, rp.faults, rp.fault_error = run, 1, [], None
    rp.events = runner.Events(tmp_path / "events.jsonl")
    toxi_calls = []
    rp.toxi = lambda *a: toxi_calls.append(runner.now()) or ""
    rp.k6 = Stub()
    rp.k6.poll = lambda: None
    run.scenario = {"faults": [{"target": "lookup", "action": "latency", "value_ms": 2000, "apply_at_s": 0.3, "remove_at_s": 0.6}]}
    for _ in range(10):
        run.annotate("noise", ["x"])  # fill the queue; must not block
    rp.t0 = runner.now()
    rp.fault_schedule()
    assert len(toxi_calls) == 2
    assert toxi_calls[0] - (rp.t0 + 300) < 100 and toxi_calls[1] - (rp.t0 + 600) < 100
    assert run.live["status"] == "degraded"
    kinds = [json.loads(l)["kind"] for l in (tmp_path / "events.jsonl").read_text().splitlines()]
    assert kinds == ["fault-apply", "fault-remove"]


@pytest.mark.parametrize("outputs,error", [(["Proxy lookup is now disabled", "Proxy lookup is now enabled"], None),
                                           (["Proxy lookup is now enabled"], "fault apply on lookup failed")])
def test_down_fault_checks_the_toggled_state(tmp_path, outputs, error):
    run = runner.Run.__new__(runner.Run)
    run.annotate = lambda *a: None
    run.scenario = {"faults": [{"target": "lookup", "action": "down", "apply_at_s": 0, "remove_at_s": 0.1}]}
    rp = runner.Repeat.__new__(runner.Repeat)
    rp.r, rp.n, rp.faults, rp.fault_error = run, 1, [], None
    rp.events = runner.Events(tmp_path / "events.jsonl")
    calls, outs = [], iter(outputs)
    rp.toxi = lambda *a: calls.append(a) or next(outs)
    rp.k6 = Stub()
    rp.k6.poll = lambda: None
    rp.t0 = runner.now()
    rp.fault_schedule()
    assert all(c == ("toggle", "lookup") for c in calls)
    assert (rp.fault_error or "").startswith(error or "") and (error is None) == (rp.fault_error is None)
    assert len(rp.faults) == (2 if error is None else 0)

def validity_repeat(tmp_path, **kw):
    rp = runner.Repeat.__new__(runner.Repeat)
    rp.rd, rp.n, rp.project, rp.invalid = tmp_path, 1, "chaos-x-r1", []
    r = rp.r = Stub()
    r.scenario = {"workload": {"graceful_stop_s": 20}, "faults": [{"target": "lookup"}]}
    r.problem = {"required_metrics": []}
    r.contract = {"budgets": {"k6": {"cpus": 2}}, "k6_saturation": {"window_s": 10, "max_ratio": 0.7}, "intervals_s": {"scrape": 1},
                  "metrics_missing": {"min_ratio": 0.95, "max_gap_s": 5}, "clock_ms": {"max_offset": 100, "max_drift": 50},
                  "fault_tolerance_s": 1}
    rp.t0, rp.measured_end, rp.offset = 0, 60_000, 0
    rp.stats = [{"t": t, "name": "chaos-x-r1-k6-run-abc", "cpu": 50.0} for t in range(0, 60_001, 1000)]
    rp.exported = {"up": []}
    rp.extra = {"clock_start": {"offset_ms": 10}, "clock_end": {"offset_ms": 20}}
    rp.faults = [{"kind": "fault-apply", "target": "lookup", "planned_ms": 40_000, "confirmed_ms": 40_010},
                 {"kind": "fault-remove", "target": "lookup", "planned_ms": 80_000, "confirmed_ms": 80_010}]
    (tmp_path / "k6").mkdir()
    (tmp_path / "k6/measured-summary.json").write_text(json.dumps({"metrics": {"dropped_iterations": {"count": kw.get("dropped", 0)}}}))
    for f in ("compose.yaml", "events.jsonl", "k6/measured.jsonl"):
        (tmp_path / f).write_text("")
    for k, v in kw.items():
        if k != "dropped":
            setattr(rp, k, v)
    return rp


def test_validity_clean(tmp_path):
    assert validity_repeat(tmp_path).validity_reasons({}) == []


def test_validity_reasons_each(tmp_path):
    reqs = {"a": {"cohort": "measured", "done": None}}
    rp = validity_repeat(tmp_path, dropped=3)
    rp.faults[1]["confirmed_ms"] = 81_500
    rp.extra["clock_end"] = {"offset_ms": 140}
    rp.stats = [dict(s, cpu=160.0) for s in rp.stats]
    out = rp.validity_reasons(reqs)
    for frag in ("dropped_iterations=3", "1 measured iterations cut off", "k6 saturated", "fault-remove on lookup confirmed 1500 ms",
                 "clock offset above 100", "clock drift above 50"):
        assert any(frag in r for r in out), (frag, out)


def test_validity_without_k6_cpu_evidence(tmp_path):
    rp = validity_repeat(tmp_path, stats=[])
    assert any("k6 CPU usage unavailable" in r for r in rp.validity_reasons({}))


def test_unconfirmed_fault_is_invalid(tmp_path):
    rp = validity_repeat(tmp_path)
    rp.faults = rp.faults[:1]
    assert any("not every planned fault" in r for r in rp.validity_reasons({}))


def test_container_exit_before_ready_is_incomplete(monkeypatch):
    rp = runner.Repeat.__new__(runner.Repeat)
    rp.project, rp.file = "chaos-x-r1", "repeats/1/compose.yaml"
    rp.eng = Stub()
    rp.eng.text = lambda *a: "exited 137"
    import pytest
    with pytest.raises(runner.Incomplete, match="exited abnormally"):
        rp.ready(runner.now() + 5000, "app", 8081, lambda a: True)


def test_dirty_tree_rules(tmp_path):
    import subprocess as sp
    g = lambda *a: sp.run(["git", *a], cwd=tmp_path, capture_output=True, check=True)  # noqa: E731
    g("init", "-q")
    g("-c", "user.email=a@b", "-c", "user.name=a", "commit", "-q", "--allow-empty", "-m", "x")
    for d in ("results", "reports", ".wf-grill", "problems/p/app"):
        (tmp_path / d).mkdir(parents=True)
        (tmp_path / d / "f.txt").write_text("x")
    h = runner.harness_git(tmp_path)
    assert h["dirty"] is False  # results/, reports/, .wf-grill/ and problems/ never make the harness dirty
    (tmp_path / "chaos.py").write_text("x")
    assert runner.harness_git(tmp_path)["dirty"] is True
    b = runner.build_git(tmp_path, "problems/p/app")
    assert b["dirty"] and "untracked problems/p/app/f.txt" in b["patch"]
