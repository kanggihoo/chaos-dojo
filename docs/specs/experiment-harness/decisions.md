# Experiment harness decisions

Glossary: [GLOSSARY.md](../../../GLOSSARY.md) · ADRs: [0001](../../adr/0001-problems-as-data-generated-compose.md)

## D-1 Scope of this feature
- Status: settled
- Decision: The harness (CLI, data format, environment generation, run lifecycle, verdicts, results, report) plus one first problem, "an external HTTP API gets slow or dies". Concurrency topics come later. PLAN, ROADMAP and README are updated to these decisions; PLAN links the spec instead of duplicating rules (spec: Existing code).
- Rejected: harness + A1 stock contention + naive/atomic-update (PLAN season0) → user wants main scenarios first and harder concurrency topics later · harness only → nothing real runs end to end

## D-2 Done criteria
- Status: settled
- Decision: Every scenario × impl of the first problem runs with one command and renders the same report; complete after a recorded verification run on macOS arm64. Platform parity is a design obligation (one code path, no per-OS parts), not a second verification run.
- Rejected: a recorded Windows run required for completion → the user switches between a Mac and a Windows PC and wants no platform-specific parts, not a formal per-platform sign-off · Windows-only or Mac-only scripts or settings → exactly what the user wants to avoid

## D-3 Stack
- Status: settled
- Decision: Spring Boot 4, Java 21, JdbcTemplate, PostgreSQL READ COMMITTED, JDBC pool 10, synchronous MVC on platform threads; server, client and pool settings fixed and identical across impls except the lookup wait policy that defines each impl; tracing through the Spring Boot 4 OpenTelemetry starter, no Java agent.
- Rejected: OpenTelemetry Java agent → bytecode-instruments executors, the subject of the thread-exhaustion experiment; agent on/off is a later experiment · Java 25 now → a Java 21 vs 25 comparison is a later experiment · virtual threads on → threading model is a separate later variable · framework defaults → can change silently between versions

## D-4 Names and terms
- Status: settled
- Decision: No Japanese-derived names. Project `chaos-lab` (docs only), CLI `chaos`, terms problem, scenario, impl, run, repeat as in the glossary.
- Rejected: `dojo` CLI and "kata" → rejected by the user · `drill` → reads as both tool and problem family

## D-5 Host requirements and platforms
- Status: settled
- Decision: The host needs only Docker with Compose v2 and uv; everything else runs in pinned multi-arch containers. macOS arm64 and Windows x86_64 are served by the same files and code with no per-OS variant; file and environment rules keep runs independent of host settings.
- Rejected: host JDK/k6 → per-OS setup diverges · Linux host as a target now → not needed yet

## D-6 CLI surface and exit codes
- Status: settled
- Decision: Three commands, `run <problem>/<scenario> --impl <impl> [--predict]`, `report`, `clean [--run]`, with exit codes fixed for every problem; no prompts.
- Rejected: Makefile entry point → no make on stock Windows · up/down/check commands → not needed yet · non-zero exit on correctness fail → a detected weakness is an expected result

## D-7 Problems as data and discovery convention
- Status: settled
- Decision: Problems, scenarios and impls are language-neutral data under a fixed directory convention, validated by committed versioned JSON Schemas shared by the Python and future Rust CLI, with strict YAML, id and path rules and confined executable assets; invalid input is rejected before any resource exists; new needs extend the common vocabulary and contract version.
- Rejected: repo-wide unique scenario ids → every problem wants names like `baseline`, so adding one problem would break another · YAML 1.1 parsing (PyYAML default) → `no`/`off`/`010` would mean different things to the Python and Rust CLIs · validating every manifest in the repo before each run → one work-in-progress problem would block all runs · per-problem Python modules or hook files → breaks the Rust rewrite and the same-command rule · a root registry file → drifts · markdown-only format docs → Python's accidental behaviour becomes the contract
- ADR: [0001](../../adr/0001-problems-as-data-generated-compose.md)

## D-8 Impl descriptor and image contract
- Status: settled
- Decision: `--impl` resolves to a declarative descriptor with no exec hooks: image, start settings, declared env vars, extra dependencies, provenance. The app serves business traffic on one port and readiness plus metrics on a separate management port with its own small executor, so observation survives worker exhaustion; required metrics are fixed and their absence invalidates. The first problem's two impls share one image.
- Rejected: one Dockerfile/image per impl as a harness rule → not needed for provenance or per-impl dependencies · metrics on the business port → naive exhausts Tomcat workers under api-slow and scrapes would fail

## D-9 Environment generation and isolation
- Status: provisional
- Decision: The CLI generates a fresh Compose project per repeat (and one observability stack per run) from the manifests and stores the exact file; repeats never share DB state; one run per Docker engine through an atomic engine lock; cleanup and `clean` touch only owned resources.
- Default: Fresh environment per repeat; revisit (in-place reset) only when measured prep time is the bottleneck and a reset-completeness check is defined.
- Rejected: reset DB between repeats in long-lived containers → reset completeness unproven · concurrent runs → CPU/memory contention confounds results
- ADR: [0001](../../adr/0001-problems-as-data-generated-compose.md)

## D-10 Dependency wiring and faults
- Status: settled
- Decision: Every experiment dependency of the app goes through Toxiproxy whether or not a fault is planned; Toxiproxy injects network faults on a timeline; external APIs are faked by a pinned WireMock image plus stub data; harness paths are not proxied.
- Rejected: proxy only on faulted paths → baseline vs fault would also change the network path · one generic harness-built fake → payment-like semantics cannot be expressed by status codes

## D-11 Run lifecycle
- Status: provisional
- Decision: A fixed phase order for every scenario with per-phase timeouts, a quiescence boundary after warmup, a bounded drain after measured load, and recorded partial results on interrupt or failure; a repeat that exceeds a phase timeout is recorded incomplete, cleaned up, and the run continues, ending with exit 3.
- Default: Fixed manifest-declared warmup duration, same for every impl, recorded as `warmup_policy=fixed`, never claimed as verified stability; revisit with a stability rule once the first backend's data shows which metric and window to use.
- Rejected: stability-based warmup now → no metric/window/tolerance chosen yet

## D-12 Load model and aggregation
- Status: settled
- Decision: Open-model constant-arrival-rate load with fixed rate and duration; metrics computed per repeat and aggregated as medians over complete and valid repeats, never pooled; dropped or cut-off iterations invalidate a repeat.
- Rejected: pooling requests across repeats → hides variance and over-weights some repeats

## D-13 Observability and metrics collection
- Status: settled
- Decision: Grafana Alloy is the single collection point and one pinned `grafana/otel-lgtm` stores and shows metrics, logs and traces live, bound to localhost; canonical evidence (k6 raw output, exported app metrics, container logs, events) is exported to result files after each repeat, with only the AC-37 forbidden strings replaced in saved logs, and the report reads files only; live copies never decide a verdict.
- Rejected: a 2 s k6 remote-write push timeout → the pinned k6 has no such setting; the push runs apart from load generation, so a slow push only marks the live copy degraded · saving container logs byte for byte with no replacement → container labels carry the absolute working directory, so home paths would reach committed results · Prometheus scraping the app directly with no collector → logs and traces would need separate paths; user asked for one collector for all three signals · separate Prometheus/Loki/Tempo/Grafana containers → four containers for the same local view; otel-lgtm's unused parts are cheaper than that · traces as required evidence → completeness depends on sampling, buffers and how an impl builds its HTTP client · Prometheus + cAdvisor as in PLAN → cAdvisor on OrbStack/WSL2 unverified and redundant with Docker stats · observability stack per repeat → traces, logs and the live view vanish between repeats · reading the backend at report time → reports would not be regenerable without it

## D-14 Resource budgets
- Status: settled
- Decision: Fixed finite CPU and memory limits on every container, k6 and observability included, with values shared by every problem kept in one versioned harness contract file that is part of the comparison identity; a run the engine cannot cover is rejected before start, never shrunk.
- Rejected: only the app limited → saturation denominator differs per host

## D-15 Verdict axes
- Status: settled
- Decision: Four separate verdicts per repeat (completion, measurement validity, correctness, SLO); the SLO has two parts, in-budget success rate and p99 of successes; only complete and valid repeats enter statistics; a correctness or SLO unknown does not remove a repeat.
- Rejected: SLO miss as correctness fail → mixes "slow" with "wrong" · latency-only SLO → fast errors would win

## D-16 Results, identity and git
- Status: settled
- Decision: Every run gets a new, never-overwritten directory under committed `results/` recording the exact identity of every image and input; dirty trees are allowed and flagged; inputs are fixed at run start.
- Rejected: git-ignored results with manual promotion → user chose to commit results · refusing dirty trees → slows the fast iteration loop

## D-17 Report and comparison
- Status: settled
- Decision: The Python CLI renders one HTML report layout for every scenario from stored result files only; `chaos report` writes new files under git-ignored `reports/` and never touches result directories; comparisons need matching identities, and cross-environment display never ranks.
- Rejected: a separate Rust report generator now (PLAN week 4) → one language until the CLI rewrite · `run` taking several impls → runs stay single-impl and independently preserved

## D-18 First problem: API and data contract
- Status: settled
- Decision: `POST /orders` looks up price and stock from an external API outside any transaction, then stores the order in one short transaction and answers 201; every failure maps to a shared RFC 9457 problem type and stores no order; the problem commits an OpenAPI contract that app, k6, stubs and checker share; k6 tags each request with its cohort in a header the app forwards to the lookup and uses as a metric label.
- Rejected: order + external payment → a timed-out payment has an unknown outcome (idempotency/reconciliation is a later problem) · read-only quote with no DB → leaves JdbcTemplate and stored-state verdicts unused

## D-19 First problem: scenarios and impls
- Status: settled
- Decision: Three scenarios (baseline, api-slow, api-down) share workload and topology; two impls in one image, `naive` with a long explicit lookup limit and `timeout` with a short deadline; numbers in the spec.
- Rejected: naive with library-default infinite timeout → k6 cuts requests first and censors latency · baseline taken from the pre-fault window → time and warmup effects mix in · api-slow latency on the downstream (response) stream → with the pinned Toxiproxy, a client that abandons the call (the timeout impl at 300 ms) strands a delayed chunk and the toxic can never be removed; latency on the request stream delays the response by the same 2 s without that hang

## D-20 First problem: invariants and recovery
- Status: settled
- Decision: Invariants are checked once on a consistent snapshot after recovery and quiescence; orders a client never saw confirmed are reported as ambiguous, not as violations; a recovery probe, sent once per second from the planned removal time alongside the remaining measured load, measures time-to-recovery from the confirmed removal at one-second resolution; a repeat with ambiguous orders and no violation is a correctness pass shown with its ambiguous count.
- Rejected: probe started only after measured load → time-to-recovery would always exceed the remaining load window · ambiguous orders making correctness unknown → nearly every naive api-slow repeat would drop out of the comparison · phantom check treating every client timeout + order as a violation → a lost response does not mean the server failed (RFC 9110 §9.2.2)

## D-21 What must never happen
- Status: settled
- Decision: Never: a valid verdict on incomplete or saturated measurement, an unapplied fault reported as a fault run, a hidden violation, overwritten or discarded results, a per-problem command or report shape, cleanup of foreign resources, a live dashboard as verdict source, and the first-problem violations listed in the spec.
