"""Warmup boundary order (AC-16) and non-blocking annotations around fault actions (AC-26)."""
import json
import queue
import socket
import threading
import time

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
    rp.toxi = "toxi"
    rp.k6 = Stub()
    rp.k6.poll = lambda: None
    run.scenario = {"faults": [{"target": "lookup", "action": "latency", "value_ms": 2000, "apply_at_s": 0.3, "remove_at_s": 0.6}]}
    toxi_calls = []
    real_http = runner.http
    monkeypatch.setattr(runner, "http", lambda m, url, *a, **k: toxi_calls.append(runner.now()) if url.startswith("http://toxi") else real_http(m, url, *a, **k))
    for _ in range(10):
        run.annotate("noise", ["x"])  # fill the queue; must not block
    rp.t0 = runner.now()
    rp.fault_schedule()
    assert len(toxi_calls) == 2
    assert toxi_calls[0] - (rp.t0 + 300) < 100 and toxi_calls[1] - (rp.t0 + 600) < 100
    assert run.live["status"] == "degraded"
    kinds = [json.loads(l)["kind"] for l in (tmp_path / "events.jsonl").read_text().splitlines()]
    assert kinds == ["fault-apply", "fault-remove"]
