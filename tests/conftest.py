import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


class FakeEngine:
    """Records every engine call in order. Behaviour is programmed per test through `responses`."""

    instances = []

    def __init__(self):
        self.calls = []
        self.host = None
        self.secrets = {}
        FakeEngine.instances.append(self)

    def __getattr__(self, name):
        def call(*args, **kw):
            self.calls.append((name, args))
            raise AssertionError(f"unexpected engine call {name}{args}")
        return call


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A repo-shaped copy (contract + problems) as the current directory."""
    shutil.copy(ROOT / "chaos-contract.yaml", tmp_path / "chaos-contract.yaml")
    shutil.copytree(ROOT / "harness", tmp_path / "harness")
    shutil.copytree(ROOT / "problems", tmp_path / "problems",
                    ignore=shutil.ignore_patterns("build", ".gradle", "src"))
    monkeypatch.chdir(tmp_path)
    FakeEngine.instances.clear()
    monkeypatch.setattr("chaos.engine.Engine", FakeEngine)
    return tmp_path


def pytest_addoption(parser):
    parser.addoption("--update-expected", action="store_true", help="rewrite tests/expected files from the generator")
