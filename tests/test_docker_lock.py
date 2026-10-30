"""Lock and clean against a real engine (AC-10, AC-11, AC-12). Needs the engine free of other chaos-lab runs."""
import subprocess

import psutil
import pytest

from chaos import runner
from chaos.cli import main
from chaos.engine import Engine as RealEngine

pytestmark = pytest.mark.docker
IMG = "alpine"


def sh(*args):
    return subprocess.run(["docker", *args], capture_output=True, text=True)


def labelled_container(name, run_id):
    sh("create", "--name", name, "--label", f"chaos-lab.run-id={run_id}", "--label", "chaos-lab.role=test", IMG)


def fake_lock(run_id, pid, start):
    sh("create", "--name", runner.LOCK, "--label", f"chaos-lab.run-id={run_id}", "--label", "chaos-lab.role=lock",
       "--label", f"chaos-lab.machine={runner.machine_id()}", "--label", f"chaos-lab.pid={pid}", "--label", f"chaos-lab.pid-start={start}", IMG)


@pytest.fixture
def engine(monkeypatch, repo):
    monkeypatch.setattr("chaos.engine.Engine", RealEngine)  # undo the fake from `repo`
    assert sh("ps", "-a", "--filter", f"name={runner.LOCK}", "-q").stdout.strip() == "", "engine busy with another run"
    sh("pull", "-q", IMG)
    names = ["chaos-test-live", "chaos-test-done", "chaos-test-decoy"]
    yield names
    for n in names + [runner.LOCK]:
        sh("rm", "-f", n)
    sh("volume", "rm", "-f", "chaos-test-decoy-vol")


LIVE = "20261031-000000-p-s-i-live01"
DONE = "20261031-000000-p-s-i-done01"


def test_second_run_from_another_checkout_is_refused(engine, repo, capsys):
    me = psutil.Process()
    fake_lock(LIVE, me.pid, me.create_time())  # a live run on this engine
    assert main(["run", "external-api/api-slow", "--impl", "naive"]) == 3
    assert "another run is in progress" in capsys.readouterr().err
    assert not (repo / "results").exists()


def test_leftover_lock_of_dead_process_is_reported(engine, repo, capsys):
    fake_lock(DONE, 999999999, 1.0)
    assert main(["run", "external-api/api-slow", "--impl", "naive"]) == 3
    assert "chaos clean" in capsys.readouterr().err


def test_clean_skips_live_runs_and_never_touches_foreign_resources(engine, capsys):
    me = psutil.Process()
    fake_lock(LIVE, me.pid, me.create_time())
    labelled_container("chaos-test-live", LIVE)
    labelled_container("chaos-test-done", DONE)
    sh("create", "--name", "chaos-test-decoy", IMG)
    sh("volume", "create", "chaos-test-decoy-vol")
    assert main(["clean"]) == 0
    out = capsys.readouterr().out
    assert "skipped 1 resource(s) of live run" in out
    names = sh("ps", "-a", "--format", "{{.Names}}").stdout.split()
    assert "chaos-test-live" in names and "chaos-test-decoy" in names and "chaos-test-done" not in names and runner.LOCK in names
    assert "chaos-test-decoy-vol" in sh("volume", "ls", "--format", "{{.Name}}").stdout.split()
    assert main(["clean", "--run", LIVE]) == 2  # still alive on this machine


def test_clean_releases_finished_and_unverifiable_runs(engine, capsys):
    fake_lock(DONE, 999999999, 1.0)
    labelled_container("chaos-test-done", DONE)
    assert main(["clean", "--run", DONE]) == 0
    names = sh("ps", "-a", "--format", "{{.Names}}").stdout.split()
    assert "chaos-test-done" not in names and runner.LOCK not in names
    assert main(["clean", "--run", DONE]) == 0
    assert "nothing to clean" in capsys.readouterr().out
