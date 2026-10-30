"""App contract (AC-28, AC-29, AC-30, AC-32): Gradle tests in a pinned container against a Postgres container."""
import subprocess
from pathlib import Path

import pytest

from chaos.validate import ROOT_SCHEMAS
from chaos import yamlload

ROOT = ROOT_SCHEMAS.parent
APP = ROOT / "problems" / "external-api" / "app"


@pytest.mark.docker
def test_app_contract():
    problem = yamlload.load(ROOT / "problems" / "external-api" / "problem.yaml")
    pg = next(d["image"] for d in problem["dependencies"] if d["kind"] == "postgres")
    gradle = next(l.split()[1] for l in (APP / "Dockerfile").read_text().splitlines() if l.startswith("FROM gradle"))
    compose = f"""
services:
  db:
    image: {pg}
    environment: {{POSTGRES_USER: orders, POSTGRES_PASSWORD: orders, POSTGRES_DB: orders}}
    volumes: ["{(APP.parent / 'schema.sql').as_posix()}:/docker-entrypoint-initdb.d/schema.sql:ro"]
    healthcheck: {{test: ["CMD", "pg_isready", "-U", "orders"], interval: 1s, retries: 30}}
  test:
    image: {gradle}
    working_dir: /src
    command: ["gradle", "--no-daemon", "-q", "test"]
    environment: {{DB_URL: "jdbc:postgresql://db:5432/orders"}}
    volumes: ["{APP.as_posix()}:/src", "gradle-cache:/home/gradle/.gradle"]
    depends_on: {{db: {{condition: service_healthy}}}}
volumes:
  gradle-cache: {{name: chaos-lab-gradle-cache}}
"""
    base = ["docker", "compose", "-p", "chaos-lab-app-contract", "-f", "-"]
    try:
        r = subprocess.run(base + ["up", "--abort-on-container-exit", "--exit-code-from", "test"],
                           input=compose, text=True, capture_output=True, timeout=900)
        assert r.returncode == 0, r.stdout[-6000:] + r.stderr[-2000:]
    finally:
        subprocess.run(base + ["down", "-v", "--remove-orphans"], input=compose, text=True, capture_output=True)
