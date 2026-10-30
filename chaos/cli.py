"""`chaos` command line: run, report, clean. Exit codes are fixed for every problem (spec: Interfaces)."""
import argparse
import sys
from pathlib import Path

from . import engine as engine_mod
from .validate import Rejected, validate


def main(argv=None):
    p = argparse.ArgumentParser(prog="chaos")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run one scenario against one impl")
    r.add_argument("target", metavar="<problem>/<scenario>")
    r.add_argument("--impl", required=True)
    r.add_argument("--predict")
    rp = sub.add_parser("report", help="render a report from stored results")
    rp.add_argument("runs", nargs="+")
    rp.add_argument("--allow-cross-env", action="store_true")
    c = sub.add_parser("clean", help="remove leftovers of finished runs")
    c.add_argument("--run", dest="run_id")
    try:
        args = p.parse_args(argv)
    except SystemExit as e:
        return 2 if e.code else 0
    root = Path.cwd()

    if args.cmd == "run":
        try:
            spec = validate(root, args.target, args.impl, args.predict)
        except Rejected as e:
            print(f"rejected: {e}", file=sys.stderr)
            return 2
        from .runner import run
        return run(spec, engine_mod.Engine())
    if args.cmd == "report":
        from .report import report_cmd
        return report_cmd(root, args.runs, args.allow_cross_env)
    from .clean import clean_cmd
    return clean_cmd(engine_mod.Engine(), args.run_id)


if __name__ == "__main__":
    sys.exit(main())
