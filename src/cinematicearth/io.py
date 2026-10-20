"""Load stops + settings from Markdown, CSV, JSON, YAML, plain text, or Python lists.

Markdown example::

    ---
    title: EarthRISE flyover
    speed: slow
    stop_duration: 8
    orbit: 45
    ---
    - Coeur d'Alene, ID | 47.6777, -116.7805 | elev=670
    - Santa Fe, NM | 35.6870, -105.9378 | orbit 60 + zoom 9km>3km; hold 1s | note=Partner site
    - Kathmandu, Nepal          (no coords -> geocoded if allowed)

or a pipe table with columns ``name | lat | lon | elev | duration | moves | transit | note``.
"""
from __future__ import annotations

import csv
import io as _io
import json
import os
import re
from dataclasses import fields
from typing import Iterable, List, Tuple, Union

from .model import Settings, Stop

_STOP_KEYS = {f.name for f in fields(Stop)}
_SET_KEYS = {f.name for f in fields(Settings)}
_ALIASES = {"latitude": "lat", "longitude": "lon", "lng": "lon", "elevation": "elev", "alt": "elev",
            "camera": "moves", "move": "moves", "commands": "moves", "dur": "duration",
            "city": "name", "location": "name", "title": "label"}
_COORD = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)(?:\s*,\s*(-?\d+(?:\.\d+)?))?\s*$")
_PAREN = re.compile(r"\(\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\)")
_KV = re.compile(r"^\s*([A-Za-z_]+)\s*[=:]\s*(.+?)\s*$")


def _coerce(key, val):
    if val is None:
        return None
    if isinstance(val, str):
        val = val.strip()
        if val == "" or val.lower() in ("none", "null", "-", "auto") and key in ("duration", "elev", "heading", "lat", "lon"):
            return None
    if key in ("lat", "lon", "elev", "duration", "heading"):
        return float(val)
    return val


def _coerce_setting(key, val):
    default = getattr(Settings(), key)
    if isinstance(val, str):
        v = val.strip()
        if v.lower() in ("none", "null", "auto", ""):
            return None
        if isinstance(default, bool):
            return v.lower() in ("1", "true", "yes", "on")
        if isinstance(default, int) and not isinstance(default, bool):
            return int(float(v))
        if isinstance(default, float) or default is None:
            try:
                return float(v)
            except ValueError:
                return v
        if key == "speed":
            try:
                return float(v)
            except ValueError:
                return v
        return v
    return val


def stop_from_any(x) -> Stop:
    if isinstance(x, Stop):
        return x
    if isinstance(x, str):
        return parse_stop_line(x)
    if isinstance(x, (tuple, list)):
        keys = ["name", "lat", "lon", "elev", "moves"]
        return Stop(**{k: _coerce(k, v) for k, v in zip(keys, x)})
    if isinstance(x, dict):
        d = {}
        for k, v in x.items():
            k = _ALIASES.get(str(k).lower().strip(), str(k).lower().strip())
            if k in _STOP_KEYS:
                if k == "moves" and isinstance(v, (list, tuple)):
                    v = "; ".join(map(str, v))
                d[k] = _coerce(k, v)
        return Stop(**d)
    raise TypeError(f"can't make a stop from {x!r}")


def parse_stop_line(line: str) -> Stop:
    line = line.strip().lstrip("-*•").strip()
    line = re.sub(r"^\d+[.)]\s+", "", line)          # "1. Name"
    parts = [p.strip() for p in re.split(r"\s+\|\s+|\t", line)]
    name, d, rest = parts[0], {}, []
    m = _PAREN.search(name)
    if m:
        d["lat"], d["lon"] = float(m.group(1)), float(m.group(2))
        name = (name[:m.start()] + name[m.end():]).strip()
    if ":" in name and "lat" not in d and not _COORD.match(name.split(":", 1)[1]):
        name, mv = name.split(":", 1)           # "Name: orbit 60"
        rest.append(mv.strip())
    for p in parts[1:]:
        c = _COORD.match(p)
        if c:
            d["lat"], d["lon"] = float(c.group(1)), float(c.group(2))
            if c.group(3):
                d["elev"] = float(c.group(3))
            continue
        kv = _KV.match(p)
        if kv:
            k = _ALIASES.get(kv.group(1).lower(), kv.group(1).lower())
            if k in _STOP_KEYS:
                d[k] = _coerce(k, kv.group(2))
                continue
        rest.append(p)
    if rest:
        d["moves"] = "; ".join(r for r in rest if r)
    return Stop(name=name.strip().strip('"'), **d)


def _front_matter(text: str) -> Tuple[dict, str]:
    m = re.match(r"^\s*---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.S)
    if not m:
        return {}, text
    raw, body = m.group(1), m.group(2)
    try:
        import yaml  # type: ignore
        meta = yaml.safe_load(raw) or {}
    except Exception:
        meta = {}
        for ln in raw.splitlines():
            kv = _KV.match(ln.split("#", 1)[0]) if ln.strip() else None
            if kv:
                meta[kv.group(1)] = kv.group(2)
    return meta, body


def _md_table(lines: List[str]):
    rows = [[c.strip() for c in ln.strip().strip("|").split("|")] for ln in lines]
    rows = [r for r in rows if not all(re.fullmatch(r":?-{2,}:?", c or "--") for c in r)]
    head = [_ALIASES.get(h.lower(), h.lower()) for h in rows[0]]
    return [dict(zip(head, r)) for r in rows[1:]]


def parse_markdown(text: str):
    meta, body = _front_matter(text)
    stops, table, settings = [], [], dict(meta)
    for ln in body.splitlines() + [""]:
        s = ln.strip()
        if s.startswith("|"):
            table.append(s)
            continue
        if table:
            stops += [stop_from_any(r) for r in _md_table(table)]
            table = []
        if not s or s.startswith("#") or s.startswith("<!--") or s.startswith(">"):
            continue
        kv = _KV.match(s)
        if kv and kv.group(1) in _SET_KEYS and not s.startswith(("-", "*")):
            settings[kv.group(1)] = kv.group(2)
            continue
        if re.match(r"^([-*•]|\d+[.)])\s+", s):
            stops.append(parse_stop_line(s))
    return settings, stops


def load(source: Union[str, os.PathLike, Iterable], **overrides) -> Tuple[Settings, List[Stop]]:
    """Load (Settings, stops) from a path, a text blob, or a Python list."""
    settings: dict = {}
    if isinstance(source, (str, os.PathLike)) and os.path.exists(str(source)):
        path = str(source)
        ext = os.path.splitext(path)[1].lower()
        with open(path, encoding="utf-8-sig") as f:
            text = f.read()
        if ext in (".md", ".markdown"):
            settings, stops = parse_markdown(text)
        elif ext == ".csv":
            stops = [stop_from_any(r) for r in csv.DictReader(_io.StringIO(text))]
        elif ext in (".json", ".yaml", ".yml"):
            if ext == ".json":
                data = json.loads(text)
            else:
                import yaml  # type: ignore
                data = yaml.safe_load(text)
            if isinstance(data, dict):
                settings = data.get("settings", {}) or {}
                data = data.get("stops", [])
            stops = [stop_from_any(x) for x in data]
        else:   # .txt or anything else: one stop per line
            settings, stops = parse_markdown("\n".join(
                ln if ln.strip().startswith(("-", "*", "#", "|", "---")) or _KV.match(ln) and
                ln.split(":")[0].strip() in _SET_KEYS else ("- " + ln if ln.strip() else ln)
                for ln in text.splitlines()))
    elif isinstance(source, str):
        settings, stops = parse_markdown(source)
    else:
        stops = [stop_from_any(x) for x in source]
    settings.update({k: v for k, v in overrides.items() if v is not None})
    clean = {}
    for k, v in settings.items():
        if k in _SET_KEYS:
            clean[k] = _coerce_setting(k, v)
    return Settings(**clean), stops
