"""Optional network helpers: place-name geocoding (Nominatim) and ground elevation
(Open-Meteo). Standard library only; results cached in ~/.cache/cinematicearth."""
from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from typing import Optional, Tuple

_CACHE = os.path.join(os.path.expanduser("~"), ".cache", "cinematicearth", "geo.json")
_UA = "CinematicEarth (https://github.com/MayerT1/CinematicEarth)"


def _load():
    try:
        with open(_CACHE) as f:
            return json.load(f)
    except Exception:
        return {}


def _save(c):
    try:
        os.makedirs(os.path.dirname(_CACHE), exist_ok=True)
        with open(_CACHE, "w") as f:
            json.dump(c, f)
    except Exception:
        pass


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def geocode(name: str) -> Optional[Tuple[float, float]]:
    c = _load()
    key = "g:" + name.lower().strip()
    if key in c:
        return tuple(c[key]) if c[key] else None
    q = urllib.parse.urlencode({"q": name, "format": "json", "limit": 1})
    res = _get(f"https://nominatim.openstreetmap.org/search?{q}")
    time.sleep(1.0)    # Nominatim usage policy: max 1 request / second
    val = (float(res[0]["lat"]), float(res[0]["lon"])) if res else None
    c[key] = val
    _save(c)
    return val


def elevation(lat: float, lon: float) -> Optional[float]:
    c = _load()
    key = f"e:{lat:.4f},{lon:.4f}"
    if key in c:
        return c[key]
    try:
        res = _get(f"https://api.open-meteo.com/v1/elevation?latitude={lat}&longitude={lon}")
        val = float(res["elevation"][0])
    except Exception:
        return None
    c[key] = val
    _save(c)
    return val


def resolve(stops, need_coords=True, need_elev=True, verbose=True):
    """Fill missing lat/lon (geocode) and elev (elevation API) in place."""
    for s in stops:
        if need_coords and (s.lat is None or s.lon is None):
            r = geocode(s.name)
            if r is None:
                raise ValueError(f"could not geocode {s.name!r}; add lat/lon")
            s.lat, s.lon = r
            if verbose:
                print(f"geocoded {s.name}: {s.lat:.4f}, {s.lon:.4f}")
        if need_elev and s.elev is None:
            s.elev = elevation(s.lat, s.lon)
            if verbose and s.elev is not None:
                print(f"elevation {s.name}: {s.elev:.0f} m")
    return stops
