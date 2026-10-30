"""`chaos clean`: remove only labelled leftovers of runs known to be over (spec: clean 규칙)."""
import re
import sys

from .engine import EngineError
from .runner import LOCK, lock_alive, read_lock

RUN_ID = re.compile(r"[0-9]{8}-[0-9]{6}-[a-z0-9-]+-[a-z0-9]{6}")


def labelled(eng, run_id=None):
    f = ["--filter", f"label=chaos-lab.run-id={run_id}" if run_id else "label=chaos-lab.run-id"]
    fmt = '{{.Label "chaos-lab.run-id"}} '
    out = []
    for kind, args, name in (("container", ["ps", "-a"], "{{.Names}}"), ("network", ["network", "ls"], "{{.Name}}"),
                             ("volume", ["volume", "ls"], "{{.Name}}")):
        for line in eng.text(*args, *f, "--format", fmt + name).splitlines():
            rid, _, n = line.partition(" ")
            if n and n != LOCK:
                out.append((rid, kind, n))
    return out


def remove(eng, items):
    failed = []
    for kind in ("container", "network", "volume"):
        for _, k, n in items:
            if k != kind:
                continue
            args = {"container": ["rm", "-f", "-v", n], "network": ["network", "rm", n], "volume": ["volume", "rm", "-f", n]}[kind]
            if eng.docker(*args, check=False).returncode:
                failed.append(f"{kind}:{n}")
    return failed


def clean_cmd(eng, run_id):
    if run_id is not None and not RUN_ID.fullmatch(run_id):
        print(f"error: malformed run id {run_id!r}", file=sys.stderr)
        return 2
    try:
        eng.resolve()
        lock = read_lock(eng)
        lock_run = lock.get("chaos-lab.run-id") if lock else None
        if run_id is not None:
            if lock_run == run_id and lock_alive(lock):
                print(f"error: run {run_id} is still running on this machine", file=sys.stderr)
                return 2
            items = labelled(eng, run_id)
            failed = remove(eng, items)
            if lock_run == run_id and not failed:
                eng.docker("rm", LOCK, check=False)
                items.append((run_id, "lock", LOCK))
            print(f"removed {len(items) - len(failed)} resource(s) of {run_id}" if items else f"nothing to clean for {run_id}")
        else:
            items = labelled(eng)
            live = lock_run if lock and lock_alive(lock) is not False else None  # unknown (other machine) counts as live
            skip = [i for i in items if i[0] == live]
            todo = [i for i in items if i[0] != live]
            failed = remove(eng, todo)
            if lock and live is None and not failed:
                eng.docker("rm", LOCK, check=False)
                print(f"removed the lock of finished run {lock_run}")
            if skip:
                print(f"skipped {len(skip)} resource(s) of live run {live}")
            print(f"removed {len(todo) - len(failed)} resource(s)" if todo else "nothing to clean")
    except EngineError as e:
        print(f"error: {e}", file=sys.stderr)
        return 3
    if failed:
        print(f"error: could not remove {failed}", file=sys.stderr)
        return 3
    return 0
