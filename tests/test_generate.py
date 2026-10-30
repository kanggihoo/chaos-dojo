"""Generated Compose and k6 settings (AC-8, AC-13, AC-17, AC-20, AC-37) and the log cap (AC-35)."""
import json
import os

import pytest
import yaml

from chaos import compose
from chaos.engine import ENV_ALLOW, Engine
from chaos.runner import Repeat, cap_log, redactor
from chaos.validate import validate
from conftest import ROOT

RUN = {"run_id": "20261031-000000-external-api-api-slow-naive-abc123", "prefix": "chaos-abc123", "run_network": "chaos-abc123-run",
       "app_image": "sha256:" + "a" * 64, "k6_script": "k6/orders.js"}
EXPECTED = ROOT / "tests" / "expected"


@pytest.fixture
def spec():
    return validate(ROOT, "external-api/api-slow", "naive")


def generated(spec):
    vols = {spec["deps"][0]["image"]: ["/var/lib/postgresql/data"]}
    return compose.dump(compose.repeat_compose(spec, RUN, 1, vols)), compose.dump(compose.obs_compose(spec, RUN))


def test_matches_expected_files(spec, request):
    rep, obs = generated(spec)
    for name, text in (("repeat-compose.yaml", rep), ("run-compose.yaml", obs)):
        f = EXPECTED / name
        if request.config.getoption("--update-expected", default=False) or not f.exists():
            f.write_text(text, encoding="utf-8")
        assert text == f.read_text(encoding="utf-8"), f"{name} changed; review and rerun with --update-expected"


def test_paths_are_relative_and_inputs_only(spec):
    for text in generated(spec):
        doc = yaml.safe_load(text)
        for svc in doc["services"].values():
            for v in svc.get("volumes", []):
                src = v.split(":", 1)[0]
                assert src.startswith(("./inputs/", "./repeats/")) or src == "/var/run/docker.sock" or not src.startswith((".", "/")), v
                if src.startswith("./") and "k6" not in src.split("/")[-1] and not src.startswith("./repeats/"):
                    assert src.startswith("./inputs/")
        assert str(ROOT) not in text and os.path.expanduser("~") not in text


def test_labels_and_credentials(spec):
    rep, obs = (yaml.safe_load(t) for t in generated(spec))
    for doc, repeat in ((rep, "1"), (obs, None)):
        for name, svc in doc["services"].items():
            assert svc["labels"]["chaos-lab.run-id"] == RUN["run_id"] and svc["labels"]["chaos-lab.role"]
            assert svc["labels"].get("chaos-lab.repeat") == repeat
        for net in doc["networks"].values():
            assert net.get("external") or net["labels"]["chaos-lab.run-id"] == RUN["run_id"]
    for vol in rep["volumes"].values():
        assert vol["labels"]["chaos-lab.repeat"] == "1"
    env = rep["services"]["app"]["environment"]
    assert env["DB_PASSWORD"] == "${CHAOS_DB_PASSWORD}" and env["DB_USER"] == "${CHAOS_DB_USER}"
    assert rep["services"]["db"]["environment"]["POSTGRES_PASSWORD"] == "${CHAOS_DB_PASSWORD}"
    assert "${CHAOS_WM_AUTH}" in rep["services"]["lookup"]["command"]
    assert obs["services"]["lgtm"]["environment"]["GF_SECURITY_ADMIN_PASSWORD"] == "${CHAOS_GF_PASSWORD}"


def test_dependencies_go_through_toxiproxy_and_its_api_is_isolated(spec):
    rep = yaml.safe_load(generated(spec)[0])
    env = rep["services"]["app"]["environment"]
    assert env["DB_URL"] == "jdbc:postgresql://toxiproxy:20000/db"
    assert env["LOOKUP_BASE_URL"] == "http://toxiproxy:20001"
    assert env["OTLP_ENDPOINT"] == "http://alloy:4318" and env["CHAOS_REPEAT"] == "1"
    tp = rep["services"]["toxiproxy"]
    assert tp["command"] == ["-host=toxiproxy-ctl", "-port=8474"]
    assert tp["networks"]["ctl"]["aliases"] == ["toxiproxy-ctl"]
    for svc in ("app", "k6"):
        assert "ctl" not in rep["services"][svc]["networks"] and "deps" not in rep["services"][svc]["networks"]
    for dep in ("db", "lookup"):
        assert rep["services"][dep]["networks"] == ["deps"]
    for doc in (rep, yaml.safe_load(generated(spec)[1])):
        for svc in doc["services"].values():
            for p in svc.get("ports", []):
                assert p.startswith("127.0.0.1::")


def test_host_settings_do_not_change_generation(spec, tmp_path, monkeypatch):
    before = generated(spec)
    monkeypatch.setenv("DOCKER_DEFAULT_PLATFORM", "linux/amd64")
    monkeypatch.setenv("COMPOSE_FILE", "evil.yaml")
    monkeypatch.setenv("COMPOSE_PROFILES", "evil")
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("CHAOS_DB_PASSWORD=x\nCOMPOSE_PROJECT_NAME=evil\n")
    assert generated(spec) == before


def test_subprocess_environment_is_the_allowlist(monkeypatch):
    for k in ("DOCKER_DEFAULT_PLATFORM", "COMPOSE_FILE", "COMPOSE_PROFILES", "SECRET_THING"):
        monkeypatch.setenv(k, "x")
    monkeypatch.setenv("PATH", "/usr/bin")
    e = Engine()
    e.host, e.secrets = "unix:///x.sock", {"CHAOS_DB_PASSWORD": "pw"}
    env = e.env()
    assert set(env) <= set(ENV_ALLOW) | {"DOCKER_HOST", "CHAOS_DB_PASSWORD"}
    assert env["DOCKER_HOST"] == "unix:///x.sock" and "COMPOSE_FILE" not in env


class _R:  # minimal Run stand-in for k6 option generation
    def __init__(self, spec, tmp):
        self.scenario, self.contract, self.problem, self.impl, self.run_id = spec["scenario"], spec["contract"], spec["problem"], spec["impl"], RUN["run_id"]


def test_k6_options(spec, tmp_path):
    rp = Repeat.__new__(Repeat)
    rp.r, rp.n, rp.rd = _R(spec, tmp_path), 2, tmp_path
    (tmp_path / "k6").mkdir()
    warm, meas = rp.k6_config("warmup"), rp.k6_config("measured")
    w = warm["options"]["scenarios"]["warmup"]
    assert (w["executor"], w["rate"], w["duration"], w["preAllocatedVUs"], w["maxVUs"]) == ("constant-arrival-rate", 50, "30s", 900, 900)
    m = meas["options"]["scenarios"]["measured"]
    assert (m["executor"], m["rate"], m["duration"], m["gracefulStop"]) == ("constant-arrival-rate", 50, "120s", "20s")
    p = meas["options"]["scenarios"]["probe"]
    assert p["startTime"] == "80s" and meas["probe"]["intervalMs"] == 1000 and meas["probe"]["count"] == 62
    assert meas["probe"]["consecutive"] == 5 and meas["options"]["tags"] == {"run_id": RUN["run_id"], "repeat": "2"}
    assert json.loads((tmp_path / "k6" / "measured.json").read_text()) == meas


# ---- log cap (AC-35)
def test_log_under_cap_is_untouched():
    assert cap_log(b"abc", 10, 4) == (b"abc", None)


def test_log_cap_keeps_head_and_tail_and_marks_cut():
    data = bytes(range(32, 127)) * 30
    out, cut = cap_log(data, 100, 20)
    assert out.startswith(data[:20]) and out.endswith(data[-80:]) and b"truncated" in out
    assert cut == {"original_bytes": 2850, "kept_head": 20, "kept_tail": 80}


def test_log_cap_never_splits_utf8():
    data = ("가" * 50).encode()  # 3 bytes each
    out, cut = cap_log(data, 31, 10)
    head, _, tail = out.partition(b"\n[chaos-lab:")
    head.decode("utf-8")
    tail.split(b"]\n", 1)[1].decode("utf-8")
    assert cut["kept_head"] == 9


def test_log_cap_keeps_ansi_and_invalid_bytes():
    data = b"\x1b[31mred\x1b[0m\xff\xfe" * 3
    assert cap_log(data, 1000, 10)[0] == data
    out, _ = cap_log(data + b"x" * 100, 40, 15)
    assert out.startswith(b"\x1b[31mred\x1b[0m\xff\xfe")


def test_redaction_of_home_host_and_secrets():
    red = redactor(["s3cr3t-value-xyz"])
    data = f"{os.path.expanduser('~')}/x pw=s3cr3t-value-xyz".encode()
    out, n = red(data)
    assert b"s3cr3t" not in out and os.path.expanduser("~").encode() not in out and n == 2
