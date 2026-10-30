"""Strict YAML: 1.2 core schema, JSON-compatible values only.

PyYAML resolves plain scalars by YAML 1.1 (`no` -> False, `010` -> 8), so we walk the
event stream and resolve scalars ourselves; the Rust CLI must read the same files the same way.
"""
import re

import yaml

INT = re.compile(r"-?(0|[1-9][0-9]*)")
LEADING_ZERO = re.compile(r"[-+]?0[0-9]+")
FLOAT = re.compile(r"-?(0|[1-9][0-9]*)(\.[0-9]+)?([eE][-+]?[0-9]+)?")
SPECIAL_FLOAT = re.compile(r"[-+]?\.(inf|Inf|INF)|\.(nan|NaN|NAN)")
MAX_INT = 2**53


class YamlError(ValueError):
    pass


def _scalar(ev):
    if ev.style is not None:  # quoted or block scalar: always a string
        return ev.value
    v = ev.value
    if v in ("", "~", "null"):
        return None
    if v in ("true", "false"):
        return v == "true"
    if v in ("True", "TRUE", "False", "FALSE", "Null", "NULL"):
        raise YamlError(f"only lowercase true/false/null allowed: {v!r}")
    if LEADING_ZERO.fullmatch(v):
        raise YamlError(f"integer with leading zero: {v!r}")
    if SPECIAL_FLOAT.fullmatch(v):
        raise YamlError(f".inf/.nan not allowed: {v!r}")
    if INT.fullmatch(v):
        n = int(v)
        if abs(n) > MAX_INT:
            raise YamlError(f"integer outside ±2^53: {v!r}")
        return n
    if FLOAT.fullmatch(v):
        return float(v)
    return v


def loads(text):
    events = iter(yaml.parse(text, Loader=yaml.SafeLoader))

    def node(ev):
        if getattr(ev, "anchor", None) is not None:
            raise YamlError("anchors are not allowed")
        if isinstance(ev, yaml.AliasEvent):
            raise YamlError("aliases are not allowed")
        if ev.tag is not None:
            raise YamlError(f"tags are not allowed: {ev.tag}")
        if isinstance(ev, yaml.ScalarEvent):
            return _scalar(ev)
        if isinstance(ev, yaml.SequenceStartEvent):
            out = []
            for e in events:
                if isinstance(e, yaml.SequenceEndEvent):
                    return out
                out.append(node(e))
        if isinstance(ev, yaml.MappingStartEvent):
            out = {}
            for e in events:
                if isinstance(e, yaml.MappingEndEvent):
                    return out
                if isinstance(e, yaml.ScalarEvent) and e.style is None and e.value == "<<":
                    raise YamlError("merge keys are not allowed")
                k = node(e)
                if not isinstance(k, str):
                    raise YamlError(f"mapping keys must be strings: {k!r}")
                if k in out:
                    raise YamlError(f"duplicate key: {k}")
                out[k] = node(next(events))
        raise YamlError(f"unexpected YAML event {ev}")

    docs = []
    try:
        for ev in events:
            if isinstance(ev, yaml.DocumentStartEvent):
                docs.append(node(next(events)))
                next(events)  # DocumentEnd
    except yaml.YAMLError as e:
        raise YamlError(str(e)) from None
    if len(docs) != 1:
        raise YamlError("expected exactly one YAML document")
    return docs[0]


def load(path):
    with open(path, encoding="utf-8") as f:
        return loads(f.read())
