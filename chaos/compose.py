"""Compose files generated from the manifests: one per repeat, one for the run's observability stack.

Paths are relative to the run directory (the Compose project directory) and point into `inputs/`.
Credentials appear only as `${VAR}` references; their values reach Compose through the process environment.
"""
import yaml

from .validate import REF_RE

DB_USER, DB_PASSWORD, WM_AUTH, GF_PASSWORD = "CHAOS_DB_USER", "CHAOS_DB_PASSWORD", "CHAOS_WM_AUTH", "CHAOS_GF_PASSWORD"
PROXY_PORT_BASE = 20000
TOXI_API = 8474
ALLOY_OTLP = 4318
ALLOY_RW = 9999


def limits(budget):
    return {"cpus": str(budget["cpus"]), "mem_limit": f"{budget['memory_mib']}m"}


def labels(run_id, role, repeat=None):
    out = {"chaos-lab.run-id": run_id, "chaos-lab.role": role}
    if repeat is not None:
        out["chaos-lab.repeat"] = str(repeat)
    return out


def proxy_port(deps, name):
    return PROXY_PORT_BASE + [d["name"] for d in deps].index(name)


def resolve_value(value, deps, run_id, repeat):
    """Replace runtime references. Credentials become Compose variable references, never literal values."""
    def sub_ref(ref):
        if ref == "chaos.otlp.endpoint":
            return f"http://alloy:{ALLOY_OTLP}"
        if ref == "chaos.run_id":
            return run_id
        if ref == "chaos.repeat":
            return str(repeat)
        _, _, dep, field = ref.split(".")
        return {"host": "toxiproxy", "port": str(proxy_port(deps, dep)),
                "user": f"${{{DB_USER}}}", "password": f"${{{DB_PASSWORD}}}"}[field]
    parts = REF_RE.split(value)  # literal, ref, literal, ref, ...; literal `$` is escaped for Compose
    return "".join(p.replace("$", "$$") if i % 2 == 0 else sub_ref(p) for i, p in enumerate(parts))


def problem_path(spec, rel_from_problem):
    return f"./inputs/problems/{spec['problem']['id']}/{rel_from_problem}"


def repeat_compose(spec, run, repeat, image_volumes):
    """`run` carries run_id, project, run_network, app_image; `image_volumes` maps image -> declared volume paths."""
    run_id, project = run["run_id"], f"{run['prefix']}-r{repeat}"
    impl, contract = spec["impl"], spec["contract"]
    deps = spec["deps"]
    lab = lambda role: labels(run_id, role, repeat)  # noqa: E731
    services, volumes = {}, {}

    def declare_volumes(service, image):
        mounts = []
        for i, path in enumerate(image_volumes.get(image, [])):
            name = f"{project}-{service}-v{i}"
            volumes[name] = {"name": name, "labels": lab(service)}
            mounts.append(f"{name}:{path}")
        return mounts

    for d in deps:
        svc = {"image": d["image"], "labels": lab(d["name"]), "networks": ["deps"], **limits(d["budget"]),
               "ports": [f"127.0.0.1::{d['port']}"], "logging": {"driver": "json-file"}}
        if d["kind"] == "postgres":
            svc["environment"] = {"POSTGRES_USER": f"${{{DB_USER}}}", "POSTGRES_PASSWORD": f"${{{DB_PASSWORD}}}", "POSTGRES_DB": d["name"]}
            svc["volumes"] = [f"{problem_path(spec, d['schema'])}:/docker-entrypoint-initdb.d/schema.sql:ro"]
            svc["command"] = ["postgres", "-c", "default_transaction_isolation=read committed"]
            svc["healthcheck"] = {"test": ["CMD-SHELL", "pg_isready -U \"$${POSTGRES_USER}\" -d " + d["name"]],
                                  "interval": "1s", "timeout": "2s", "retries": 120}
        else:
            svc["command"] = ["--port", str(d["port"]), "--admin-api-basic-auth", f"${{{WM_AUTH}}}", "--disable-extensions-scanning",
                              "--disable-banner", "--max-request-journal-entries", "50000"]
            svc["volumes"] = [f"{problem_path(spec, d['stubs'])}:/home/wiremock/mappings:ro"]
        svc["volumes"] = svc.get("volumes", []) + declare_volumes(d["name"], d["image"])
        services[d["name"]] = svc

    services["toxiproxy"] = {
        "image": contract["images"]["toxiproxy"], "labels": lab("toxiproxy"),
        "command": ["-host=toxiproxy-ctl", f"-port={TOXI_API}"],
        "networks": {"ctl": {"aliases": ["toxiproxy-ctl"], "gw_priority": 100}, "deps": {}, "app": {}},
        "ports": [f"127.0.0.1::{TOXI_API}"], **limits(spec["problem"]["proxy_budget"]), "logging": {"driver": "json-file"},
    }

    env = {k: resolve_value(v, deps, run_id, repeat) for k, v in impl["env"].items()}
    services["app"] = {
        "image": run["app_image"], "labels": lab("app"), "environment": env,
        "networks": ["app", "run"], "ports": [f"127.0.0.1::{impl['ports']['management']}"],
        "expose": [str(impl["ports"]["business"])], **limits(contract["budgets"]["app"]),
        "depends_on": {d["name"]: {"condition": "service_healthy" if d["kind"] == "postgres" else "service_started"} for d in deps},
        "logging": {"driver": "json-file"},
    }
    services["k6"] = {
        "image": contract["images"]["k6"], "labels": lab("k6"), "networks": ["app", "run"],
        **limits(contract["budgets"]["k6"]),
        "volumes": ["./inputs/harness/k6/wrapper.js:/chaos/wrapper.js:ro",
                    f"{problem_path(spec, run['k6_script'])}:/problem/script.js:ro",
                    f"./repeats/{repeat}/k6:/out"],
        "environment": {"K6_PROMETHEUS_RW_SERVER_URL": f"http://alloy:{ALLOY_RW}/api/v1/metrics/write",
                        "K6_PROMETHEUS_RW_PUSH_INTERVAL": f"{contract['live']['k6_push_s']}s",
                        "K6_PROMETHEUS_RW_TREND_STATS": "p(50),p(95),p(99),max",
                        "K6_NO_USAGE_REPORT": "true", "K6_AUTO_EXTENSION_RESOLUTION": "false"},
        "profiles": ["load"], "logging": {"driver": "json-file"},
    }
    nets = {n: {"labels": lab("network")} for n in ("app", "deps", "ctl")}
    nets["run"] = {"external": True, "name": run["run_network"]}
    return {"name": project, "services": services, "networks": nets, "volumes": volumes}


def obs_compose(spec, run):
    run_id, contract, impl = run["run_id"], spec["contract"], spec["impl"]
    lab = lambda role: labels(run_id, role)  # noqa: E731
    return {
        "name": f"{run['prefix']}-obs",
        "services": {
            "alloy": {
                "image": contract["images"]["alloy"], "labels": lab("alloy"), "networks": ["run"],
                "command": ["run", "/etc/alloy/config.alloy", "--storage.path=/var/lib/alloy/data",
                            "--server.http.listen-addr=0.0.0.0:12345"],
                "environment": {"CHAOS_RUN_ID": run_id, "CHAOS_RUN_NETWORK": run["run_network"],
                                "CHAOS_MGMT_PORT": str(impl["ports"]["management"]), "CHAOS_METRICS_PATH": impl["metrics_path"],
                                "CHAOS_SCRAPE_INTERVAL": f"{contract['intervals_s']['scrape']}s",
                                "CHAOS_DISCOVERY_INTERVAL": f"{contract['intervals_s']['discovery']}s"},
                "volumes": ["./inputs/harness/alloy/config.alloy:/etc/alloy/config.alloy:ro",
                            "/var/run/docker.sock:/var/run/docker.sock:ro"],
                **limits(contract["budgets"]["alloy"]), "logging": {"driver": "json-file"},
            },
            "lgtm": {
                "image": contract["images"]["lgtm"], "labels": lab("lgtm"), "networks": ["run"],
                "environment": {"GF_AUTH_ANONYMOUS_ENABLED": "true", "GF_AUTH_ANONYMOUS_ORG_ROLE": "Viewer",
                                "GF_SECURITY_ADMIN_PASSWORD": f"${{{GF_PASSWORD}}}", "GF_AUTH_DISABLE_LOGIN_FORM": "false",
                                "GF_USERS_ALLOW_SIGN_UP": "false", "GF_PLUGINS_PREINSTALL_DISABLED": "true",
                                "GF_ANALYTICS_REPORTING_ENABLED": "false", "GF_ANALYTICS_CHECK_FOR_UPDATES": "false"},
                "ports": ["127.0.0.1::3000", "127.0.0.1::9090", "127.0.0.1::3200"],
                "volumes": ["./inputs/harness/grafana/provider.yaml:/otel-lgtm/grafana/conf/provisioning/dashboards/chaos-lab.yaml:ro",
                            "./inputs/harness/grafana/dashboard.json:/chaos/dashboard.json:ro"],
                **limits(contract["budgets"]["lgtm"]), "logging": {"driver": "json-file"},
            },
        },
        "networks": {"run": {"name": run["run_network"], "labels": lab("network")}},
    }


def dump(doc):
    return yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=200)
