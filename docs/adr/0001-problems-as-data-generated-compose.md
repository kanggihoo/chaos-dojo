# Problems are language-neutral data and every environment is generated

Problems, scenarios and impls are YAML manifests plus SQL, k6, OpenAPI and stub files, validated by committed JSON Schemas, with no per-problem code or hooks; the CLI generates a fresh Compose file for every repeat from them (and one run-level Compose for the observability stack) and stores the exact file in the results. We chose this so every scenario runs with the same command and report, so a run's environment is reproducible from its results alone, and so the Python CLI can be rewritten in Rust later by reading the same files and schemas.

## Considered Options

- **Per-problem Python modules or hooks**: fastest to write, but the Rust rewrite would have to port each one, and problems would drift into their own procedures.
- **Hand-written Compose file per problem with overrides**: familiar, but problems diverge in naming, limits and wiring, and the stored result no longer proves which environment ran.
- **Long-lived containers with a DB reset between repeats**: faster repeats, but reset completeness is unproven, so state from one repeat could leak into the next.

## Consequences

- A new need (a new fault type, a new dependency kind) is added to the common runner vocabulary and the schema version, never as a one-off in a problem.
- Each repeat pays container start-up time; revisit in-place reset only when measured prep time is the bottleneck and a reset-completeness check exists.
- The observability stack is the one long-lived part of a run, so backend state carries over between its repeats and is recorded as a limit.
- Problems whose invariants join several sources (a fake API's journal, client outcomes, DB rows) grow the common check vocabulary and bump the contract version, so stored results span several contract versions.
- The run-level observability stack's own load can grow from repeat to repeat; fixed CPU/memory limits bound it and its usage is recorded per repeat, but repeat order is not fully neutral.
- The engine lock is per Docker engine: two engines on one Mac (OrbStack and Docker Desktop at once) can run two runs side by side undetected.
- A scenario that kills or saturates the app itself will see scrape failures by design; the rule that `up=0` invalidates a repeat must be revisited when such a scenario is added.
- Committing every container's log grows the repository; per-file byte caps bound each repeat.
