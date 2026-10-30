"""The one boundary through which every Docker and Compose call passes. Tests replace it with a fake."""
import json
import os
import subprocess

ENV_ALLOW = ["PATH", "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "SYSTEMROOT", "TEMP", "TMP",
             "DOCKER_CONFIG", "DOCKER_CERT_PATH", "DOCKER_TLS_VERIFY"]


class EngineError(Exception):
    """A Docker engine call failed (exit 3)."""


class Engine:
    def __init__(self):
        self.host = None
        self.secrets = {}  # generated credentials, passed to Compose only through the process environment

    def resolve(self):
        """Pick the engine once by the Docker CLI rules; every later call names it explicitly."""
        if os.environ.get("DOCKER_HOST"):
            self.host = os.environ["DOCKER_HOST"]
        else:
            ctx = os.environ.get("DOCKER_CONTEXT") or self._cli(["context", "show"]).strip()
            self.host = self._cli(["context", "inspect", ctx, "--format", "{{.Endpoints.docker.Host}}"]).strip()
        return self.host

    def env(self):
        e = {k: os.environ[k] for k in ENV_ALLOW if k in os.environ}
        if self.host:
            e["DOCKER_HOST"] = self.host
        e.update(self.secrets)
        return e

    def _cli(self, args):
        r = subprocess.run(["docker", *args], capture_output=True, text=True, env=self.env(), stdin=subprocess.DEVNULL)
        if r.returncode:
            raise EngineError(f"docker {' '.join(args[:2])}: {r.stderr.strip()[:500]}")
        return r.stdout

    def docker(self, *args, check=True, timeout=None):
        try:
            r = subprocess.run(["docker", *args], capture_output=True, env=self.env(), stdin=subprocess.DEVNULL, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise EngineError(f"docker {' '.join(args[:2])}: timed out after {timeout}s") from None
        if check and r.returncode:
            raise EngineError(f"docker {' '.join(args[:3])}: {r.stderr.decode('utf-8', 'replace').strip()[:800]}")
        return r

    def text(self, *args, **kw):
        return self.docker(*args, **kw).stdout.decode("utf-8", "replace")

    def json(self, *args):
        return json.loads(self.text(*args))

    def compose(self, project_dir, project, file, *args, check=True, timeout=None):
        return self.docker("compose", "--project-directory", str(project_dir), "-p", project, "-f", str(file), *args,
                           check=check, timeout=timeout)

    def popen(self, *args):
        """Start a long-running docker command whose merged output is read line by line."""
        return subprocess.Popen(["docker", *args], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=self.env(),
                                stdin=subprocess.DEVNULL, bufsize=1, text=True, encoding="utf-8", errors="replace")
