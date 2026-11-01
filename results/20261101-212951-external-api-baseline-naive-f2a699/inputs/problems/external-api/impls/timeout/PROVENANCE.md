# timeout

Shared app image (`../../app`) with `IMPL=timeout`: the whole lookup call (pool acquire + connect + response) is cut at `LOOKUP_DEADLINE_MS` (300 ms). Written for chaos-lab; no external source.
