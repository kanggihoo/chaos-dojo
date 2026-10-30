"""Verdicts from evidence (AC-17, AC-19, AC-22..AC-27, AC-36): fixtures built in code, one behaviour per test."""
import pytest
from hypothesis import given, strategies as st

from chaos import verdict as v

SLO = {"budget_ms": 500, "success_ratio": 0.99}
REC = {"interval_s": 1, "max_s": 60, "consecutive": 5}
PRICES = {"p-001": 1500, "p-002": 2500}


def q(i, cohort="measured", issued=0, lat=10, status=201, error_code=0, done=True, product="p-001", qty=2, res=None, typ=None):
    res = res if res is not None else ({"productId": product, "quantity": qty, "unitPrice": PRICES[product], "total": PRICES[product] * qty,
                                        "currency": "KRW"} if status == 201 else None)
    return {"id": i, "cohort": cohort, "n": 0, "issued": issued, "req": {"productId": product, "quantity": qty},
            "done": issued + lat if done else None, "status": status if done else None, "error_code": error_code if done else None,
            "res": res, "type": typ}


def row(i, cohort="measured", product="p-001", qty=2, price=None, total=None):
    p = PRICES[product] if price is None else price
    return {"request_id": i, "cohort": cohort, "productId": product, "quantity": qty, "unitPrice": p,
            "total": p * qty if total is None else total, "currency": "KRW"}


def reqs(*qs):
    return {x["id"]: x for x in qs}


# ---- records and latency samples
def test_records_convert_engine_time_and_mark_cut_offs():
    recs = [{"k": "issue", "id": "a", "cohort": "measured", "n": 0, "issued": 1100, "req": {}},
            {"k": "done", "id": "a", "cohort": "measured", "done": 1300, "status": 201, "error_code": 0},
            {"k": "issue", "id": "b", "cohort": "measured", "n": 1, "issued": 1200, "req": {}}]
    r = v.requests_from_records(recs, offset_ms=100)
    assert r["a"]["issued"] == 1000 and r["a"]["done"] == 1200
    assert r["b"]["done"] is None


def test_timeouts_and_cut_offs_are_counted_and_excluded_from_success_latency():
    s = v.latency_summary([q("a", lat=20), q("b", lat=15000, status=0, error_code=1050), q("c", done=False)], 500)
    assert s["status_201"] == 1 and s["k6_timeouts"] == 1 and s["cut_off"] == 1 and s["p99_201_ms"] == 20


# ---- SLO
def test_slo_met():
    assert v.slo(reqs(*[q(str(i), issued=i, lat=100) for i in range(100)]), SLO, None, True)["value"] == "met"


def test_slo_missed_by_ratio():
    rs = [q(str(i), issued=i, lat=100) for i in range(98)] + [q("x", lat=600), q("y", status=503)]
    out = v.slo(reqs(*rs), SLO, None, True)
    assert out["value"] == "missed" and "ratio" in out["reasons"][0]


def test_slo_missed_by_p99_nearest_rank():
    rs = [q(str(i), lat=100) for i in range(995)] + [q(f"s{i}", lat=900) for i in range(5)]
    assert v.slo(reqs(*rs), dict(SLO, success_ratio=0.9), None, True)["value"] == "met"  # rank 990 is still 100 ms
    rs += [q(f"t{i}", lat=900) for i in range(10)]
    out = v.slo(reqs(*rs), dict(SLO, success_ratio=0.9), None, True)
    assert out["value"] == "missed" and out["p99_201_ms"] == 900


def test_slo_no_201_is_missed_without_p99():
    out = v.slo(reqs(q("a", status=503), q("b", status=504)), SLO, None, True)
    assert out["value"] == "missed" and out["p99_201_ms"] is None and any("p99 not computed" in r for r in out["reasons"])


def test_slo_unknown_when_nothing_issued_or_evidence_missing():
    assert v.slo({}, SLO, None, True)["value"] == "unknown"
    assert v.slo(reqs(q("a")), SLO, None, False)["value"] == "unknown"


def test_slo_ignores_probe_and_splits_segments_by_actual_fault_time():
    rs = [q("a", issued=0), q("b", issued=1500, lat=2000), q("c", issued=3000), q("p", cohort="probe", status=503)]
    out = v.slo(reqs(*rs), SLO, (1000, 2000), True)
    assert out["issued"] == 3
    assert [out["segments"][k]["issued"] for k in ("before", "during", "after")] == [1, 1, 1]
    assert out["segments"]["during"]["in_budget_ratio"] == 0


# ---- recovery
def probes(removed, statuses, start_offset=0, lat=10):
    return [q(f"p{k}", cohort="probe", issued=removed + start_offset + k * 1000, lat=lat, status=s) for k, s in enumerate(statuses)]


def test_time_to_recovery_from_confirmed_removal():
    out = v.recovery(reqs(*probes(10_000, [503, 503, 201, 201, 201, 201, 201], start_offset=200)), 10_000, REC, 500)
    assert out["recovered"] and out["time_to_recovery_ms"] == 2200


def test_probes_before_removal_are_excluded():
    ps = probes(9_000, [201] * 7)  # first probe issued 1 s before the confirmed removal
    out = v.recovery(reqs(*ps), 10_000, REC, 500)
    assert out["time_to_recovery_ms"] == 0 and out["probes_counted"] == 5


def test_late_removal_moves_the_window():
    ps = probes(80_000, [503] * 3 + [201] * 70)
    out = v.recovery(reqs(*ps), 80_600, REC, 500)  # removal confirmed late; window counts from 80.6 s
    assert out["recovered"] and out["time_to_recovery_ms"] == 2400


def test_no_recovery_within_60s():
    out = v.recovery(reqs(*probes(0, [503] * 62)), 0, REC, 500)
    assert out["recovered"] is False


def test_fifth_success_issued_inside_window_but_arriving_after_is_not_recovery():
    ps = probes(0, [503] * 55 + [201] * 4, start_offset=0) + [q("last", cohort="probe", issued=59_800, lat=400)]
    out = v.recovery(reqs(*ps), 0, REC, 500)
    assert out["recovered"] is False


def test_out_of_budget_201_breaks_the_run():
    ps = probes(0, [201, 201, 201, 201]) + [q("slow", cohort="probe", issued=4000, lat=600)] + probes(5000, [201] * 5)
    assert v.recovery(reqs(*ps), 0, REC, 500)["time_to_recovery_ms"] == 5000


def test_recovery_not_applicable_without_fault():
    assert v.recovery({}, None, REC, 500) == {"applicable": False, "reason": "scenario has no fault"}


# ---- invariants
OK_REC = {"applicable": True, "recovered": True}


def kinds(viol):
    return sorted(x["invariant"] for x in viol)


def test_clean_repeat_passes():
    viol, amb, bnd = v.invariants(reqs(q("a"), q("b", status=504)), [row("a")], PRICES, set(), OK_REC, {})
    assert (viol, amb, bnd) == ([], [], [])


@pytest.mark.parametrize("case,rs,rows,expect", [
    ("1 missing order", [q("a")], [], [1]),
    ("2 payload differs", [q("a")], [row("a", qty=3)], [2]),
    ("2 cohort differs", [q("a", cohort="probe")], [row("a", cohort="measured")], [2]),
    ("3 order after 503", [q("a", status=503)], [row("a")], [3]),
    ("3 order after unavailable 409", [q("a", status=409, typ="urn:chaos-lab:problem:product-unavailable")], [row("a")], [3]),
    ("4 price differs from stub", [q("a", res={"productId": "p-001", "quantity": 2, "unitPrice": 9, "total": 18, "currency": "KRW"})],
     [row("a", price=9)], [4]),
    ("5 foreign order", [q("a")], [row("a"), row("zzz")], [5]),
])
def test_each_violation(case, rs, rows, expect):
    viol, _, _ = v.invariants(reqs(*rs), rows, PRICES, set(), OK_REC, {})
    assert kinds(viol) == expect


def test_violation_6_no_recovery():
    viol, _, _ = v.invariants({}, [], PRICES, set(), {"applicable": True, "recovered": False}, {})
    assert kinds(viol) == [6]


def test_duplicate_request_409_is_not_a_violation():
    viol, _, _ = v.invariants(reqs(q("a", status=409, typ="urn:chaos-lab:problem:duplicate-request")), [row("a")], PRICES, set(), OK_REC, {})
    assert viol == []


def test_ambiguous_kinds_and_rollback():
    rs = [q("t", status=0, error_code=1050, lat=15000), q("c", done=False), q("s", status=500), q("r", status=500)]
    viol, amb, _ = v.invariants(reqs(*rs), [row("t"), row("c"), row("s"), row("r")], PRICES, {"r"}, OK_REC, {})
    assert sorted(a["kind"] for a in amb) == ["persisted despite server error"] + ["persisted without client confirmation"] * 2
    assert kinds(viol) == [3]  # the 500 whose rollback the app recorded


def test_warmup_orders_are_a_boundary_violation_not_v5():
    viol, _, bnd = v.invariants(reqs(q("a")), [row("a"), row("w", cohort="warmup")], PRICES, set(), OK_REC, {})
    assert viol == [] and bnd == ["w"]


def test_correctness_combinations():
    assert v.correctness([], [], [])["value"] == "pass"
    assert v.correctness([], [{"kind": "x"}], []) == {"value": "pass", "reasons": ["1 ambiguous"]}
    assert v.correctness([], [], ["DB snapshot missing"])["value"] == "unknown"
    mixed = v.correctness([{"invariant": 1}, {"invariant": 3}], [], ["DB snapshot missing"])
    assert mixed["value"] == "fail" and mixed["reasons"][0] == "2 confirmed violation(s)"


# ---- measurement validity inputs
def prom(points, labels=None):
    return [{"metric": labels or {}, "values": [[t / 1000, str(val)] for t, val in points]}]


def test_missing_metric_by_ratio_and_gap():
    full = prom([(t, 1) for t in range(0, 100_001, 1000)])
    gappy = prom([(t, 1) for t in range(0, 100_001, 1000) if not 40_000 < t < 47_000])
    sparse = prom([(t, 1) for t in range(0, 100_001, 2000)])
    out = v.missing_metrics({"a": full, "b": gappy, "c": sparse}, ["a", "b", "c", "d"], (0, 100_000), 1, 0.95, 5, 0)
    assert [r.split(":")[0] for r in out] == ["metric b", "metric c", "metric d"]


def test_metric_times_are_converted_from_engine_clock():
    m = prom([(t + 50, 1) for t in range(0, 10_001, 1000)])
    assert v.missing_metrics({"a": m}, ["a"], (0, 10_000), 1, 0.95, 5, offset_ms=50) == []


def test_scrape_down():
    assert v.scrape_down(prom([(0, 1), (1000, 0)]), (0, 2000), 0)
    assert not v.scrape_down(prom([(0, 1), (5000, 0)]), (0, 2000), 0)


def test_saturation_window():
    calm = [{"t": t, "name": "k6", "cpu": 60.0} for t in range(0, 30_000, 1000)]
    spike = [dict(s, cpu=150.0) if 10_000 <= s["t"] < 21_000 else s for s in calm]
    assert v.saturated(calm, "k6", 2, (0, 30_000), 10, 0.7) is False
    assert v.saturated(spike, "k6", 2, (0, 30_000), 10, 0.7) is True
    assert v.saturated([], "k6", 2, (0, 30_000), 10, 0.7) is None


# ---- aggregation
def rep(n, completion="complete", validity="valid", **values):
    return {"n": n, "completion": completion, "validity": validity, "exclusion": [] if validity == "valid" else ["x"], "values": values}


def test_aggregate_medians_only_complete_and_valid():
    rs = [rep(1, p99_201_ms=100), rep(2, p99_201_ms=300), rep(3, validity="invalid", p99_201_ms=9999),
          rep(4, completion="incomplete", validity="unknown"), rep(5, p99_201_ms=200), rep(6, p99_201_ms=400)]
    a = v.aggregate(rs, 5)
    m = a["metrics"]["p99_201_ms"]
    assert m["median"] == 250 and m["n"] == 4  # even n: mean of the middle two
    assert a["valid"] == 4 and a["not_full_five"] and [e["n"] for e in a["excluded"]] == [3, 4]


def test_cv_and_investigation_flag():
    a = v.aggregate([rep(i, p99_201_ms=x) for i, x in enumerate([100, 100, 100, 100, 200], 1)], 5)
    m = a["metrics"]["p99_201_ms"]
    assert m["cv"] == pytest.approx(0.3727, abs=1e-3) and m["investigate"]
    assert v.cv([5]) is None and v.cv([0, 0]) is None


def test_unknown_correctness_or_slo_stays_in_statistics():
    r = rep(1, p99_201_ms=10)
    r.update(correctness="unknown", slo="unknown")
    assert v.aggregate([r], 5)["metrics"]["p99_201_ms"]["n"] == 1


@given(st.lists(st.lists(st.floats(1, 1000), min_size=1, max_size=50), min_size=1, max_size=7))
def test_aggregate_is_median_of_per_repeat_values_never_pooled(per_repeat):
    rs = [rep(i, p99_201_ms=v.nearest_rank(xs, 99)) for i, xs in enumerate(per_repeat, 1)]
    expect = sorted(v.nearest_rank(xs, 99) for xs in per_repeat)
    k = len(expect)
    med = expect[k // 2] if k % 2 else (expect[k // 2 - 1] + expect[k // 2]) / 2
    assert v.aggregate(rs, 5)["metrics"]["p99_201_ms"]["median"] == pytest.approx(med)
