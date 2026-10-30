"""Per-repeat verdicts and run aggregation. Pure functions over collected evidence (spec: Interfaces, D-15, D-20).

All times are host UTC milliseconds; engine-clock values are converted before they get here.
"""
import math
import statistics

K6_TIMEOUT = 1050
FAILURE_TYPES = {"invalid-request", "upstream-timeout", "upstream-unavailable", "upstream-error",
                 "invalid-upstream-response", "product-unavailable"}
NO_ORDER_STATUSES = {400, 502, 503, 504}


def requests_from_records(records, offset_ms):
    """k6 issue/done records -> {id: request}; engine ms converted to host ms."""
    reqs = {}
    for r in records:
        if r["k"] == "issue":
            reqs[r["id"]] = {"id": r["id"], "cohort": r["cohort"], "n": r["n"], "issued": r["issued"] - offset_ms,
                             "req": r["req"], "done": None, "status": None, "error_code": None, "res": None, "type": None}
        elif r["k"] == "done" and r["id"] in reqs:
            q = reqs[r["id"]]
            q.update(done=r["done"] - offset_ms, status=r["status"], error_code=r["error_code"], res=r.get("res"), type=r.get("type"))
    return reqs


def nearest_rank(values, p):
    s = sorted(values)
    return s[max(0, math.ceil(p / 100 * len(s)) - 1)]


def latency_summary(reqs, budget_ms):
    """Success latency (201 only) plus counts of what is excluded from it, with reasons."""
    ok = [q["done"] - q["issued"] for q in reqs if q["status"] == 201]
    return {
        "issued": len(reqs),
        "status_201": len(ok),
        "in_budget_201": sum(1 for v in ok if v <= budget_ms),
        "k6_timeouts": sum(1 for q in reqs if q["done"] is not None and q["error_code"] == K6_TIMEOUT),
        "client_errors": sum(1 for q in reqs if q["done"] is not None and q["status"] == 0 and q["error_code"] != K6_TIMEOUT),
        "cut_off": sum(1 for q in reqs if q["done"] is None),
        "p99_201_ms": nearest_rank(ok, 99) if ok else None,
        "p50_201_ms": nearest_rank(ok, 50) if ok else None,
    }


def slo(reqs, slo_cfg, fault_window, evidence_ok):
    """SLO over the measured cohort; segments split by issue time at the actual fault apply/remove times."""
    measured = [q for q in reqs.values() if q["cohort"] == "measured"]
    out = {"budget_ms": slo_cfg["budget_ms"], "threshold": slo_cfg["success_ratio"]}
    if not evidence_ok:
        return {**out, "value": "unknown", "reasons": ["k6 raw results missing"]}
    if not measured:
        return {**out, "value": "unknown", "reasons": ["no measured requests issued"]}
    s = latency_summary(measured, slo_cfg["budget_ms"])
    ratio = s["in_budget_201"] / s["issued"]
    reasons = []
    if ratio < slo_cfg["success_ratio"]:
        reasons.append(f"in-budget 201 ratio {ratio:.4f} < {slo_cfg['success_ratio']}")
    if s["status_201"] == 0:
        reasons.append("no 201 responses; p99 not computed")
    elif s["p99_201_ms"] > slo_cfg["budget_ms"]:
        reasons.append(f"201 p99 {s['p99_201_ms']:.0f} ms > {slo_cfg['budget_ms']} ms")
    segments = {}
    if fault_window:
        a, b = fault_window
        for name, sel in (("before", lambda q: q["issued"] < a), ("during", lambda q: a <= q["issued"] < b),
                          ("after", lambda q: q["issued"] >= b)):
            part = [q for q in measured if sel(q)]
            ps = latency_summary(part, slo_cfg["budget_ms"])
            ps["in_budget_ratio"] = ps["in_budget_201"] / ps["issued"] if ps["issued"] else None
            segments[name] = ps
    return {**out, "value": "missed" if reasons else "met", "reasons": reasons, "in_budget_ratio": ratio, **s, "segments": segments}


def recovery(reqs, removed_at, cfg, budget_ms):
    """Time-to-recovery from the confirmed removal; None removed_at means no fault (not applicable)."""
    if removed_at is None:
        return {"applicable": False, "reason": "scenario has no fault"}
    window_end = removed_at + cfg["max_s"] * 1000
    probes = sorted((q for q in reqs.values() if q["cohort"] == "probe" and q["issued"] >= removed_at), key=lambda q: q["issued"])
    run = []
    for q in probes:
        good = q["status"] == 201 and q["done"] is not None and q["done"] - q["issued"] <= budget_ms
        run = run + [q] if good else []
        if len(run) == cfg["consecutive"]:
            if run[-1]["done"] < window_end:
                return {"applicable": True, "recovered": True, "removed_at": removed_at,
                        "time_to_recovery_ms": run[0]["issued"] - removed_at, "probes_counted": probes.index(q) + 1}
            break
    return {"applicable": True, "recovered": False, "removed_at": removed_at, "time_to_recovery_ms": None,
            "probes_counted": len(probes)}


def invariants(reqs, rows, prices, rollbacks, rec, store):
    """Check the first-problem invariants per request id (spec: 첫 problem 불변식).

    rows: stored orders as dicts keyed by API field names plus request_id and cohort.
    Returns (violations, ambiguous, boundary_orders).
    """
    by_id = {}
    for r in rows:
        by_id.setdefault(r["request_id"], []).append(r)
    violations, ambiguous = [], []
    issued = {i for i, q in reqs.items() if q["cohort"] in ("measured", "probe")}
    for i, q in reqs.items():
        if q["cohort"] not in ("measured", "probe"):
            continue
        stored = by_id.get(i, [])
        st = q["status"]
        if st == 201:
            if len(stored) != 1:
                violations.append({"invariant": 1, "request_id": i, "detail": f"201 but {len(stored)} orders"})
                continue
            o, res, req = stored[0], q["res"] or {}, q["req"]
            want = {"productId": req.get("productId"), "quantity": req.get("quantity"), "unitPrice": res.get("unitPrice"),
                    "total": res.get("total"), "currency": res.get("currency"), "cohort": q["cohort"]}
            if res.get("productId") != req.get("productId") or res.get("quantity") != req.get("quantity"):
                want["response"] = "differs from request"
            diff = {k: (o.get(k), v) for k, v in want.items() if o.get(k) != v}
            if diff:
                violations.append({"invariant": 2, "request_id": i, "detail": {k: {"stored": a, "expected": b} for k, (a, b) in diff.items()}})
        elif stored and (st in NO_ORDER_STATUSES or (st == 409 and q["type"] == "urn:chaos-lab:problem:product-unavailable")):
            violations.append({"invariant": 3, "request_id": i, "detail": f"{st} response but {len(stored)} orders"})
        elif stored and st == 500:
            if i in rollbacks:
                violations.append({"invariant": 3, "request_id": i, "detail": "500 with recorded rollback but order stored"})
            else:
                ambiguous.append({"kind": "persisted despite server error", "request_id": i})
        elif stored and (q["done"] is None or st == 0):
            ambiguous.append({"kind": "persisted without client confirmation", "request_id": i,
                              "reason": "cut off" if q["done"] is None else ("k6 timeout" if q["error_code"] == K6_TIMEOUT else "client error")})
    boundary = []
    for r in rows:
        if prices.get(r["productId"]) != r["unitPrice"]:
            violations.append({"invariant": 4, "request_id": r["request_id"], "detail": f"unit price {r['unitPrice']} != stub {prices.get(r['productId'])}"})
        if r["cohort"] == "warmup":
            boundary.append(r["request_id"])
        elif r["request_id"] not in issued:
            violations.append({"invariant": 5, "request_id": r["request_id"], "detail": "order for an id this repeat never issued"})
    if rec.get("applicable") and not rec.get("recovered"):
        violations.append({"invariant": 6, "request_id": None, "detail": f"no recovery within {store.get('recovery_max_s', 60)} s of removal"})
    return violations, ambiguous, boundary


def correctness(violations, ambiguous, evidence_reasons):
    if violations:
        return {"value": "fail", "reasons": [f"{len(violations)} confirmed violation(s)"] + evidence_reasons}
    if evidence_reasons:
        return {"value": "unknown", "reasons": evidence_reasons}
    return {"value": "pass", "reasons": [f"{len(ambiguous)} ambiguous"] if ambiguous else []}


def series_points(prom_result):
    """Prometheus matrix -> list of (series labels, [(t_ms, value)])."""
    return [(s["metric"], [(float(t) * 1000, float(v)) for t, v in s["values"]]) for s in prom_result]


def missing_metrics(exported, required, window, scrape_s, min_ratio, max_gap_s, offset_ms):
    """Required metric is missing when < min_ratio of expected scrape times have a sample, or a gap > max_gap_s."""
    a, b = window
    expected = max(1, int((b - a) / 1000 / scrape_s))
    reasons = []
    for name in required:
        times = sorted({round(t - offset_ms) for _, pts in series_points(exported.get(name, [])) for t, _ in pts if a <= t - offset_ms <= b})
        if len(times) / expected < min_ratio:
            reasons.append(f"metric {name}: {len(times)}/{expected} samples")
            continue
        edges = [a] + times + [b]
        gap = max(y - x for x, y in zip(edges, edges[1:]))
        if gap > max_gap_s * 1000:
            reasons.append(f"metric {name}: gap {gap / 1000:.1f} s")
    return reasons


def scrape_down(up_result, window, offset_ms):
    a, b = window
    return any(v == 0 for _, pts in series_points(up_result) for t, v in pts if a <= t - offset_ms <= b)


def saturated(stats, container, cpus, window, win_s, max_ratio):
    """Any `win_s` window inside `window` whose mean CPU exceeds max_ratio of the container's budget."""
    a, b = window
    pts = sorted((s["t"], s["cpu"]) for s in stats if s["name"] == container and a <= s["t"] <= b)
    if not pts:
        return None  # no evidence
    for i, (t0, _) in enumerate(pts):
        win = [c for t, c in pts[i:] if t < t0 + win_s * 1000]
        if pts[-1][0] - t0 < win_s * 1000 * 0.9:
            break
        if statistics.fmean(win) > max_ratio * cpus * 100:
            return True
    return False


def median(xs):
    return statistics.median(xs) if xs else None


def cv(xs):
    if len(xs) < 2:
        return None
    m = statistics.fmean(xs)
    return None if m == 0 else statistics.stdev(xs) / m


AGG_METRICS = [("in_budget_ratio", "median of per-repeat in-budget 201 ratio"),
               ("p99_201_ms", "median of per-repeat 201 p99 (ms)"),
               ("p50_201_ms", "median of per-repeat 201 p50 (ms)"),
               ("time_to_recovery_ms", "median of per-repeat time-to-recovery (ms)"),
               ("ambiguous", "median of per-repeat ambiguous orders"),
               ("violations", "median of per-repeat confirmed violations")]


def aggregate(repeats, planned):
    """Run-level values: per-repeat values of complete and valid repeats, never pooled requests."""
    included = [r for r in repeats if r["completion"] == "complete" and r["validity"] == "valid"]
    excluded = [{"n": r["n"], "reasons": r["exclusion"]} for r in repeats if r not in included]
    metrics = {}
    for key, label in AGG_METRICS:
        xs = [r["values"][key] for r in included if r["values"].get(key) is not None]
        c = cv(xs)
        metrics[key] = {"label": label, "median": median(xs), "cv": c, "n": len(xs),
                        "investigate": c is not None and c > 0.10}
    return {"planned": planned, "executed": sum(1 for r in repeats if r["completion"] != "not-run"),
            "complete": sum(1 for r in repeats if r["completion"] == "complete"), "valid": len(included),
            "not_full_five": len(included) < 5, "excluded": excluded, "metrics": metrics}
