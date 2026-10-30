"""HTML report from stored result files only. One layout for every scenario (D-17).

Nothing outside the result files goes into the HTML (no generation time, no randomness, no repo state),
so `chaos report <run>` reproduces a run's report.html byte for byte.
"""
import json
import secrets
import sys
from datetime import datetime, timezone
from html import escape
from pathlib import Path

from .validate import schema_errors

SUPPORTED_SCHEMA_VERSIONS = {1}
CSS = """body{font:14px/1.45 system-ui,sans-serif;margin:24px;color:#1b1b1b;background:#fff}
h1{font-size:20px}h2{font-size:17px;margin-top:28px}h3{font-size:15px}
table{border-collapse:collapse;margin:8px 0}td,th{border:1px solid #ccc;padding:3px 8px;text-align:left;vertical-align:top}
th{background:#f3f3f3}.na{color:#777}.bad{color:#b00020}.ok{color:#0a6b2d}.note{color:#555;font-size:13px}
code{background:#f3f3f3;padding:1px 4px}@media(prefers-color-scheme:dark){body{background:#151515;color:#e8e8e8}
th{background:#262626}td,th{border-color:#444}code{background:#262626}.na{color:#999}.note{color:#aaa}}"""
VERDICT_CLASS = {"pass": "ok", "met": "ok", "complete": "ok", "valid": "ok",
                 "fail": "bad", "missed": "bad", "incomplete": "bad", "invalid": "bad"}


class ReportError(Exception):
    pass


def load(run_dir):
    run_dir = Path(run_dir)
    if not (run_dir / "run.json").is_file():
        raise ReportError(f"{run_dir.as_posix()}: no run.json (not a run directory)")
    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    if run.get("schema_version") not in SUPPORTED_SCHEMA_VERSIONS:
        raise ReportError(f"{run_dir.as_posix()}: unsupported result schema version {run.get('schema_version')}")
    errs = schema_errors("run", run)
    if errs:
        raise ReportError(f"{run_dir.as_posix()}/run.json: schema violation: {'; '.join(errs)}")
    repeats = {}
    for r in run["repeats"]:
        p = run_dir / "repeats" / str(r["n"]) / "repeat.json"
        if p.is_file():
            doc = json.loads(p.read_text(encoding="utf-8"))
            errs = schema_errors("repeat", doc)
            if errs:
                raise ReportError(f"{p.as_posix()}: schema violation: {'; '.join(errs)}")
            repeats[r["n"]] = doc
    predict = None
    if run.get("predict") and (run_dir / run["predict"]).is_file():
        predict = (run_dir / run["predict"]).read_text(encoding="utf-8", errors="replace")
    return {"dir": run_dir, "run": run, "repeats": repeats, "predict": predict}


def fmt(v, digits=1):
    if v is None:
        return '<span class="na">n/a</span>'
    if isinstance(v, float):
        return f"{v:.{digits}f}" if abs(v) >= 1 or v == 0 else f"{v:.4f}"
    return escape(str(v))


def verdict_cell(v):
    if v is None:
        return '<td class="na">n/a</td>'
    return f'<td class="{VERDICT_CLASS.get(v, "")}">{escape(str(v))}</td>'


def table(head, rows):
    h = "".join(f"<th>{escape(x)}</th>" for x in head)
    return f"<table><tr>{h}</tr>" + "".join("<tr>" + "".join(r) + "</tr>" for r in rows) + "</table>"


def td(v, digits=1):
    return f"<td>{fmt(v, digits)}</td>"


def section_run(d):
    run, reps = d["run"], d["repeats"]
    ident = run["identity"]
    eng = ident.get("engine", {})
    agg = run["aggregate"]
    out = [f'<h2>{escape(run["impl"])} — run <code>{escape(run["run_id"])}</code></h2>']
    out.append(f'<p>{escape(run.get("impl_description") or "")}</p>')
    extra = run.get("impl_extra_dependencies") or []
    out.append("<p>Comparison variable: impl <code>{}</code>; extra dependencies: {}</p>".format(
        escape(run["impl"]), ", ".join(f'{escape(x["name"])} ({x["budget"]["cpus"]} CPU / {x["budget"]["memory_mib"]} MiB)' for x in extra) or "none"))
    out.append(f'<p>Exit code <b>{run["exit_code"]}</b>'
               + (f' — <span class="bad">{escape(run["error"])}</span>' if run.get("error") else "")
               + f'. Live view: {escape(run["live_status"])}'
               + (f' ({escape("; ".join(run.get("live_reasons", [])))})' if run.get("live_reasons") else "") + ".</p>")
    h = ident.get("harness", {})
    out.append(f'<p class="note">Engine: {escape(str(eng.get("product")))} {escape(str(eng.get("server_version")))}, '
               f'{escape(str(eng.get("os_type")))}/{escape(str(eng.get("architecture")))}, {eng.get("cpus")} CPU, '
               f'{(eng.get("memory_bytes") or 0) // 2**20} MiB. Harness commit {escape(str(h.get("commit")))}'
               + (' <span class="bad">(dirty)</span>' if h.get("dirty") else "")
               + (' · app build <span class="bad">dirty</span>' if ident.get("images", {}).get("app", {}).get("dirty") else "") + "</p>")
    out.append(f'<p>Reproduce: <code>uv run chaos run {escape(run["problem"])}/{escape(run["scenario"])} --impl {escape(run["impl"])}</code></p>')

    out.append("<h3>Repeats</h3>")
    rows = []
    for r in run["repeats"]:
        rep = reps.get(r["n"], {})
        rec = rep.get("recovery") or {}
        lat = rep.get("latency") or {}
        slo = (rep.get("verdicts") or {}).get("slo") or {}
        rows.append([td(r["n"]), verdict_cell(r["completion"]), verdict_cell(r["validity"]), verdict_cell(r.get("correctness")),
                     verdict_cell(r.get("slo")), td(slo.get("in_budget_ratio"), 4), td(slo.get("p99_201_ms")),
                     td(rec.get("time_to_recovery_ms")) if rec.get("applicable") else '<td class="na">not applicable</td>',
                     td(rep.get("values", {}).get("violations")), td(rep.get("values", {}).get("ambiguous")),
                     td(lat.get("k6_timeouts")), td(lat.get("cut_off")),
                     f'<td>{escape("; ".join(r["exclusion"]))}</td>'])
    out.append(table(["#", "completion", "validity", "correctness", "SLO", "in-budget 201 ratio", "201 p99 ms",
                      "time-to-recovery ms", "violations", "ambiguous", "k6 timeouts", "cut off", "excluded because"], rows))

    out.append("<h3>Run values</h3>")
    flags = []
    if agg["not_full_five"]:
        flags.append("완전한 5회 결과 아님")
    out.append(f'<p>planned {agg["planned"]} · executed {agg["executed"]} · complete {agg["complete"]} · valid {agg["valid"]}'
               + (f' — <span class="bad">{escape(", ".join(flags))}</span>' if flags else "") + "</p>")
    rows = [[f'<td>{escape(m["label"])}</td>', td(m["median"]), td(m["cv"], 3), td(m["n"]),
             '<td class="bad">조사 신호 (CV&gt;10%)</td>' if m["investigate"] else "<td></td>"] for m in agg["metrics"].values()]
    out.append(table(["value", "median", "CV", "n", ""], rows))

    out.append("<h3>Fault segments (measured cohort, split by actual apply/remove time)</h3>")
    rows = []
    for r in run["repeats"]:
        seg = ((reps.get(r["n"], {}).get("verdicts") or {}).get("slo") or {}).get("segments") or {}
        if not seg:
            rows.append([td(r["n"]), '<td class="na" colspan="3">not applicable</td>'])
            continue
        rows.append([td(r["n"])] + [f'<td>{fmt(seg[k].get("in_budget_ratio"), 4)} / p99 {fmt(seg[k].get("p99_201_ms"))} ms (n={seg[k]["issued"]})</td>'
                                    for k in ("before", "during", "after")])
    out.append(table(["#", "before", "during", "after"], rows))

    out.append("<h3>Observability stack usage per repeat</h3>")
    rows = [[td(n)] + [td((rep.get("observability_usage") or {}).get(s, {}).get("cpu_mean_pct")) for s in ("alloy", "lgtm")]
            for n, rep in sorted(reps.items())]
    out.append(table(["#", "alloy CPU % (mean)", "lgtm CPU % (mean)"], rows))
    out.append('<p class="note">Limit: the observability stack stays up for the whole run, so its backend state carries over between repeats '
               'and repeat order is not fully neutral.</p>')
    if d["predict"] is not None:
        out.append(f"<h3>Prediction</h3><pre>{escape(d['predict'])}</pre>")
    else:
        out.append('<h3>Prediction</h3><p class="na">none recorded</p>')
    return "\n".join(out)


def render(runs, cross_env=False):
    first = runs[0]["run"]
    title = f'{first["problem"]}/{first["scenario"]}'
    body = [f"<h1>chaos-lab · {escape(title)}</h1>"]
    if cross_env:
        body.append('<p class="bad">Different environments: shown side by side only. No winner or ranking.</p>')
    elif len(runs) > 1:
        rows = [[f'<td>{escape(d["run"]["impl"])}</td>'] + [td(m["median"]) for m in d["run"]["aggregate"]["metrics"].values()] for d in runs]
        labels = [m["label"] for m in first["aggregate"]["metrics"].values()]
        body.append("<h2>Comparison</h2>" + table(["impl", *labels], rows))
    body += [section_run(d) for d in runs]
    return (f'<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>chaos-lab report</title><style>{CSS}</style></head><body>" + "\n".join(body) + "</body></html>\n")


def render_runs(dirs):
    return render([load(d) for d in dirs])


def env_of(run):
    return run["identity"].get("engine")


def report_cmd(root, dirs, allow_cross_env):
    try:
        runs = []
        for d in dirs:
            if not Path(d).is_dir():
                raise ReportError(f"{d}: no such directory")
            runs.append(load(d))
        cross = False
        base = runs[0]["run"]
        for d in runs[1:]:
            r = d["run"]
            if (r["problem"], r["scenario"]) != (base["problem"], base["scenario"]):
                raise ReportError(f"{r['run_id']} is a different scenario; only runs of one scenario are compared")
            if r["identity"].get("comparison") != base["identity"].get("comparison"):
                raise ReportError(f"{r['run_id']} differs in comparison identity (scenario, problem, workload, seed or contract)")
            if env_of(r) != env_of(base):
                if not allow_cross_env:
                    raise ReportError(f"{r['run_id']} ran on a different environment; pass --allow-cross-env to show them side by side")
                cross = True
        html = render(runs, cross_env=cross)
    except ReportError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except Exception as e:  # noqa: BLE001
        print(f"error: {type(e).__name__}: {e}", file=sys.stderr)
        return 3
    out_dir = Path(root) / "reports"
    out_dir.mkdir(exist_ok=True)
    while True:
        p = out_dir / f"{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{secrets.token_hex(3)}.html"
        try:
            with p.open("x", encoding="utf-8") as f:
                f.write(html)
            break
        except FileExistsError:
            continue
    print(p.relative_to(root).as_posix())
    return 0
