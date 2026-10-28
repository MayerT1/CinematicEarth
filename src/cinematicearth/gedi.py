"""GEDI spaceborne lidar -> KML layers for the flyover.

Data sources
------------
* SlideRule (https://slideruleearth.io, no login):
    - L2A: ground elevation (``elevation_lm``), canopy top (``elevation_hr``), sensitivity, flags
           -> ``canopy_height = elevation_hr - elevation_lm``
    - L4A: above-ground biomass density ``agbd`` (Mg/ha) + ground elevation
  SlideRule does not serve GEDI L2B.
* GEDI L2B (foliage height diversity ``fhd_normal``, ``cover``, ``pai``, ``rh100``):
    - ``harmony_l2b(...)`` subsets GEDI02_B granules to your AOI with NASA Harmony
      (free Earthdata login), the same approach as the EarthRISE L2B tutorial
    - ``read_l2b_h5(...)`` reads full or subsetted GEDI02_B HDF5 files
* Anything already processed: ``read_table(csv / parquet / geojson)``

Every loader returns a pandas DataFrame with ``lat``, ``lon``, ``time``, ``year``
plus the product variables. ``gedi_kmz(...)`` turns it into KMZ layers:

* ``columns``  : one extruded column per shot (height = canopy height, colour = e.g. FHD)
* ``curtains`` : vertical walls along each ground track showing the canopy profile
* ``grid2d`` / ``grid3d`` : shots averaged onto a grid, then draped (2D) or extruded (3D)
* ``by="year"``: one KMZ per year (fade them in with Keyframe Opacity = time series)

Requires: ``pip install "CinematicEarth[gedi]"`` (sliderule, h5py, earthaccess, harmony-py,
geopandas, shapely, pandas) -- only the parts you use are imported.
"""
from __future__ import annotations

import glob
import io as _io
import json
import math
import os
import re
import zipfile
from dataclasses import dataclass, field, asdict
from typing import Iterable, List, Optional, Sequence, Union
from xml.sax.saxutils import escape

import numpy as np

GEDI_EPOCH = np.datetime64("2018-01-01T00:00:00")
FILL = -9999.0

AOI_PRESETS = {
    "sewanee": "https://raw.githubusercontent.com/SERVIR/Explore_GEDI_EarthRISE_Training/main/AOIs/Sewanee_Domain.geojson",
    "sewanee_domain": "https://raw.githubusercontent.com/SERVIR/Explore_GEDI_EarthRISE_Training/main/AOIs/Sewanee_Domain.geojson",
}

VARIABLES = {   # name: (label, units, default colormap)
    "canopy_height": ("Canopy height", "m", "YlGn"),
    "rh100": ("Canopy height (RH100)", "m", "YlGn"),
    "fhd_normal": ("Foliage height diversity", "", "viridis"),
    "cover": ("Canopy cover", "", "Greens"),
    "pai": ("Plant area index", "m²/m²", "summer_r"),
    "agbd": ("Aboveground biomass density", "Mg/ha", "YlOrBr"),
    "elev_ground": ("Ground elevation", "m", "terrain"),
    "sensitivity": ("Beam sensitivity", "", "magma"),
}


def _pd():
    import pandas as pd
    return pd


# ======================================================================================
# AOI
# ======================================================================================
@dataclass
class AOI:
    ring: List[tuple]          # [(lon, lat), ...] closed
    name: str = "aoi"

    @property
    def bbox(self):
        xs, ys = zip(*self.ring)
        return (min(xs), min(ys), max(xs), max(ys))

    @property
    def center(self):
        w, s, e, n = self.bbox
        return (0.5 * (s + n), 0.5 * (w + e))

    def contains(self, lon, lat):
        """Vectorised point-in-polygon (ray casting)."""
        lon, lat = np.asarray(lon, float), np.asarray(lat, float)
        inside = np.zeros(lon.shape, bool)
        pts = self.ring
        for (x1, y1), (x2, y2) in zip(pts[:-1], pts[1:]):
            cond = (y1 > lat) != (y2 > lat)
            with np.errstate(divide="ignore", invalid="ignore"):
                xint = (x2 - x1) * (lat - y1) / (y2 - y1) + x1
            inside ^= cond & (lon < xint)
        return inside

    def sliderule_poly(self):
        return [{"lon": float(x), "lat": float(y)} for x, y in self.ring]

    def geojson(self):
        return {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {"name": self.name},
                "geometry": {"type": "Polygon", "coordinates": [[list(p) for p in self.ring]]}}]}


def _ring_from_geojson(gj):
    feats = gj["features"] if gj.get("type") == "FeatureCollection" else [gj]
    geom = feats[0]["geometry"] if "geometry" in feats[0] else feats[0]
    c = geom["coordinates"]
    if geom["type"] == "MultiPolygon":
        c = max(c, key=lambda p: len(p[0]))   # largest part
    ring = [tuple(p[:2]) for p in c[0]]
    if ring[0] != ring[-1]:
        ring.append(ring[0])
    return ring


def load_aoi(aoi, name: Optional[str] = None) -> AOI:
    """AOI from: preset name ("sewanee"), GeoJSON path/URL, (w, s, e, n) bbox, [(lon, lat), ...], or AOI."""
    if isinstance(aoi, AOI):
        return aoi
    if isinstance(aoi, str):
        key = aoi.strip().lower()
        src = AOI_PRESETS.get(key, aoi)
        nm = name or (key if key in AOI_PRESETS else os.path.splitext(os.path.basename(src.split("?")[0]))[0])
        m = re.fullmatch(r"\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*", aoi)
        if m:
            return load_aoi(tuple(float(v) for v in m.groups()), name or "bbox")
        if src.startswith(("http://", "https://")):
            import urllib.request
            with urllib.request.urlopen(src, timeout=60) as r:
                gj = json.loads(r.read().decode())
        else:
            with open(src) as f:
                gj = json.load(f)
        return AOI(_ring_from_geojson(gj), nm)
    if hasattr(aoi, "exterior"):                    # shapely Polygon
        return AOI([tuple(p[:2]) for p in aoi.exterior.coords], name or "aoi")
    if hasattr(aoi, "geometry") and hasattr(aoi, "total_bounds"):   # GeoDataFrame
        return load_aoi(aoi.to_crs(4326).geometry.iloc[0], name)
    seq = list(aoi)
    if len(seq) == 4 and all(isinstance(v, (int, float)) for v in seq):
        w, s, e, n = seq
        return AOI([(w, s), (e, s), (e, n), (w, n), (w, s)], name or "bbox")
    ring = [tuple(p[:2]) for p in seq]
    if ring[0] != ring[-1]:
        ring.append(ring[0])
    return AOI(ring, name or "aoi")


# ======================================================================================
# Normalisation
# ======================================================================================
def _finish(df, aoi: Optional[AOI] = None):
    pd = _pd()
    df = df.copy()
    if "time" in df.columns:
        df["time"] = pd.to_datetime(df["time"], errors="coerce", utc=True).dt.tz_localize(None)
        df["year"] = df["time"].dt.year
    if aoi is not None and len(df):
        df = df[aoi.contains(df["lon"].values, df["lat"].values)]
    if "canopy_height" not in df.columns:
        if "rh100" in df.columns:
            df["canopy_height"] = df["rh100"]
        elif {"elev_top", "elev_ground"} <= set(df.columns):
            df["canopy_height"] = df["elev_top"] - df["elev_ground"]
    if "canopy_height" in df.columns:
        df["canopy_height"] = df["canopy_height"].clip(lower=0)
    return df.reset_index(drop=True)


_ALIASES = {"latitude": "lat", "lat_lowestmode": "lat", "geolocation/lat_lowestmode": "lat", "y": "lat",
            "longitude": "lon", "lon_lowestmode": "lon", "geolocation/lon_lowestmode": "lon", "lng": "lon", "x": "lon",
            "elevation_lm": "elev_ground", "elevation_lowestmode": "elev_ground", "elev_lowestmode": "elev_ground",
            "geolocation/elev_lowestmode": "elev_ground", "elevation": "elev_ground",
            "elevation_hr": "elev_top", "elevation_highestreturn": "elev_top", "elev_highestreturn": "elev_top",
            "geolocation/elev_highestreturn": "elev_top",
            "geolocation/degrade_flag": "degrade_flag", "datetime": "time", "date": "time", "time_ns": "time"}


def normalise_columns(df):
    df = df.rename(columns={c: _ALIASES.get(c, _ALIASES.get(str(c).lower(), c)) for c in df.columns})
    if ("lat" not in df.columns or "lon" not in df.columns) and "geometry" in df.columns:
        geo = df["geometry"]
        if hasattr(geo, "x"):
            df["lon"], df["lat"] = geo.x.values, geo.y.values
        else:
            df["lon"] = [p.x for p in geo]
            df["lat"] = [p.y for p in geo]
    if "geometry" in df.columns:
        df = df.drop(columns="geometry")
    return df


# ======================================================================================
# SlideRule (L2A, L4A)
# ======================================================================================
_SR_READY = False


def sliderule_gedi(aoi, product: str = "l2a", t0: Optional[str] = None, t1: Optional[str] = None,
                   quality: bool = True, beams: Optional[Sequence[int]] = None,
                   anc_fields: Optional[Sequence[str]] = None, verbose: bool = False):
    """GEDI L2A (canopy height, ground elevation) or L4A (biomass) footprints from SlideRule.

    t0 / t1: 'YYYY-MM-DD' (optional). quality=True drops degraded and low-quality shots.
    """
    global _SR_READY
    try:
        from sliderule import sliderule, gedi
    except ImportError as e:
        raise ImportError('SlideRule needs: pip install "CinematicEarth[gedi]"') from e
    a = load_aoi(aoi)
    if not _SR_READY:
        sliderule.init(verbose=verbose)
        _SR_READY = True
    parms = {"poly": a.sliderule_poly(), "degrade_filter": bool(quality)}
    p = product.lower().replace("gedi", "").replace("_", "").replace("0", "")
    if p in ("2a", "l2a"):
        parms["l2_quality_filter"] = bool(quality)
    elif p in ("4a", "l4a"):
        parms["l4_quality_filter"] = bool(quality)
    else:
        raise ValueError("SlideRule serves GEDI L1B/L2A/L4A; for L2B (FHD) use harmony_l2b() + read_l2b_h5()")
    if t0:
        parms["t0"] = f"{t0}T00:00:00Z" if len(t0) == 10 else t0
    if t1:
        parms["t1"] = f"{t1}T23:59:59Z" if len(t1) == 10 else t1
    if beams is not None:
        parms["beams"] = list(beams)
    if anc_fields:
        parms["anc_fields"] = list(anc_fields)
    gdf = gedi.gedi02ap(parms) if p in ("2a", "l2a") else gedi.gedi04ap(parms)
    pd = _pd()
    if len(gdf) == 0:
        return _finish(pd.DataFrame(columns=["lat", "lon", "time"]))
    df = pd.DataFrame(gdf.drop(columns="geometry"))
    df["lon"], df["lat"] = gdf.geometry.x.values, gdf.geometry.y.values
    df["time"] = gdf.index
    df = normalise_columns(df)
    if "agbd" in df.columns:
        df.loc[df["agbd"] < 0, "agbd"] = np.nan
    df["product"] = "L2A" if p in ("2a", "l2a") else "L4A"
    return _finish(df, a)


# ======================================================================================
# L2B via Harmony + HDF5 reader
# ======================================================================================
def harmony_l2b(aoi, t0: str = "2019-04-18", t1: str = "2030-01-01", out_dir: str = "gedi_l2b",
                version: str = "002", persist_login: bool = True) -> List[str]:
    """Subset GEDI02_B granules to the AOI bbox with NASA Harmony and download them.

    Needs a free NASA Earthdata login (prompted once; persist_login stores it in ~/.netrc).
    """
    try:
        import earthaccess
        from harmony import BBox, Client, Collection, Request, CapabilitiesRequest
    except ImportError as e:
        raise ImportError('L2B download needs: pip install "CinematicEarth[gedi]"') from e
    from datetime import datetime
    a = load_aoi(aoi)
    auth = earthaccess.login(persist=persist_login)
    client = Client(auth=(auth.username, auth.password))
    caps = client.submit(CapabilitiesRequest(short_name="GEDI02_B"))
    concept = caps["conceptId"]
    w, s, e, n = a.bbox
    req = Request(collection=Collection(id=concept), spatial=BBox(w, s, e, n),
                  temporal={"start": datetime.fromisoformat(t0), "stop": datetime.fromisoformat(t1)})
    if not req.is_valid():
        raise ValueError("Harmony request is not valid")
    os.makedirs(out_dir, exist_ok=True)
    job = client.submit(req)
    client.wait_for_processing(job, show_progress=True)
    files = [f.result() for f in client.download_all(job, directory=out_dir, overwrite=False)]
    return [f for f in files if str(f).endswith(".h5")]


def _first(g, names):
    for n in names:
        if n in g:
            return g[n][()]
    return None


def read_l2b_h5(paths: Union[str, Sequence[str]], aoi=None, beams: Optional[Sequence[str]] = None):
    """Read GEDI02_B HDF5 files (full or Harmony-subsetted) into a DataFrame."""
    import h5py
    pd = _pd()
    if isinstance(paths, str):
        paths = sorted(glob.glob(os.path.join(paths, "**", "*.h5"), recursive=True)) if os.path.isdir(paths) else [paths]
    a = load_aoi(aoi) if aoi is not None else None
    rows = []
    for p in paths:
        with h5py.File(p, "r") as f:
            for b in [k for k in f.keys() if k.startswith("BEAM")]:
                if beams and b not in beams:
                    continue
                g = f[b]
                lat = _first(g, ["geolocation/lat_lowestmode", "lat_lowestmode"])
                lon = _first(g, ["geolocation/lon_lowestmode", "lon_lowestmode"])
                if lat is None or lon is None or len(np.atleast_1d(lat)) == 0:
                    continue
                d = {"lat": lat, "lon": lon, "beam": b}
                dt = _first(g, ["geolocation/delta_time", "delta_time"])
                if dt is not None:
                    d["time"] = GEDI_EPOCH + (np.asarray(dt) * 1e9).astype("timedelta64[ns]")
                for key, names, scale in [
                    ("fhd_normal", ["fhd_normal"], 1), ("cover", ["cover"], 1), ("pai", ["pai"], 1),
                    ("rh100", ["rh100"], 0.01), ("l2b_quality_flag", ["l2b_quality_flag"], 1),
                    ("degrade_flag", ["geolocation/degrade_flag", "degrade_flag"], 1),
                    ("sensitivity", ["sensitivity"], 1),
                    ("elev_ground", ["geolocation/elev_lowestmode", "elev_lowestmode"], 1),
                    ("elev_top", ["geolocation/elev_highestreturn", "elev_highestreturn"], 1),
                    ("shot_number", ["shot_number", "geolocation/shot_number"], 1),
                    ("num_detectedmodes", ["num_detectedmodes"], 1)]:
                    v = _first(g, names)
                    if v is not None and np.ndim(v) == 1 and len(v) == len(lat):
                        v = np.asarray(v)
                        if scale != 1:
                            v = np.where(v <= FILL, np.nan, v * scale)
                        d[key] = v
                d["granule"] = os.path.basename(p)
                rows.append(pd.DataFrame(d))
    if not rows:
        return _finish(pd.DataFrame(columns=["lat", "lon", "time"]))
    df = pd.concat(rows, ignore_index=True)
    for c in ("fhd_normal", "cover", "pai"):
        if c in df.columns:
            df.loc[df[c] <= FILL, c] = np.nan
    df["product"] = "L2B"
    return _finish(df, a)


def filter_l2b(df, min_sensitivity: float = 0.9, require_quality: bool = True, drop_degraded: bool = True,
               leaf_on_only: bool = False):
    """Recommended L2B screening (as in the EarthRISE tutorial)."""
    m = np.ones(len(df), bool)
    if require_quality and "l2b_quality_flag" in df:
        m &= df["l2b_quality_flag"].values == 1
    if drop_degraded and "degrade_flag" in df:
        m &= df["degrade_flag"].values == 0
    if min_sensitivity and "sensitivity" in df:
        m &= df["sensitivity"].values >= min_sensitivity
    if "fhd_normal" in df:
        m &= np.isfinite(df["fhd_normal"].values)
    return df[m].reset_index(drop=True)


def read_table(path: str, aoi=None):
    """CSV / Parquet / GeoJSON / GeoPackage of GEDI shots (any column naming used by the tutorials)."""
    pd = _pd()
    ext = os.path.splitext(path)[1].lower()
    if ext == ".csv":
        df = pd.read_csv(path)
    elif ext in (".parquet", ".pq"):
        try:
            import geopandas as gpd
            df = gpd.read_parquet(path)
        except Exception:
            df = pd.read_parquet(path)
    else:
        import geopandas as gpd
        df = gpd.read_file(path).to_crs(4326)
    return _finish(normalise_columns(df), load_aoi(aoi) if aoi is not None else None)


def synthetic_shots(aoi="sewanee", n_tracks: int = 10, years=(2019, 2020, 2021, 2022, 2023), seed: int = 0):
    """Plausible-looking fake GEDI shots for testing the visual pipeline offline (NOT real data)."""
    pd = _pd()
    a = load_aoi(aoi) if not isinstance(aoi, AOI) else aoi
    w, s, e, n = a.bbox
    rng = np.random.default_rng(seed)
    rows = []
    for k in range(n_tracks):
        yr = years[k % len(years)]
        lon0 = rng.uniform(w, e)
        ang = math.radians(rng.uniform(-40, -30) if k % 2 else rng.uniform(30, 40))
        for beam in range(4):
            off = (beam - 1.5) * 600 / 111_320
            m = int((n - s) * 110_574 / 60)
            t = np.arange(m)
            lat = s + (n - s) * t / m
            lon = lon0 + off + np.tan(ang) * (lat - s) * 110_574 / (111_320 * math.cos(math.radians(lat.mean())))
            hz = 22 + 9 * np.sin(lon * 400) * np.cos(lat * 300) + rng.normal(0, 3, m)
            fhd = np.clip(1.6 + 0.04 * hz + rng.normal(0, 0.25, m), 0.2, 3.8)
            rows.append(pd.DataFrame({
                "lat": lat, "lon": lon, "beam": f"BEAM{beam:04b}", "track": k,
                "time": np.datetime64(f"{yr}-0{3 + k % 6}-15") + (t * 0.0165 * 1e9).astype("timedelta64[ns]"),
                "rh100": np.clip(hz, 0, 45), "fhd_normal": fhd, "cover": np.clip(hz / 40, 0, 1),
                "pai": np.clip(hz / 8, 0, 6), "elev_ground": 560 + 30 * np.sin(lat * 900),
                "sensitivity": rng.uniform(0.9, 0.99, m), "l2b_quality_flag": 1, "degrade_flag": 0}))
    df = pd.concat(rows, ignore_index=True)
    df["product"] = "synthetic"
    return _finish(df, a)


# ======================================================================================
# KML / KMZ
# ======================================================================================
def _cm(name):
    import matplotlib
    try:
        return matplotlib.colormaps[name]
    except Exception:
        import matplotlib.cm as cm
        return cm.get_cmap(name)


def _kml_color(rgba, alpha):
    r, g, b = (int(round(255 * c)) for c in rgba[:3])
    return f"{int(round(255 * alpha)):02x}{b:02x}{g:02x}{r:02x}"


def _offset(lat, lon, de, dn):
    return lat + dn / 110_574.0, lon + de / (111_320.0 * max(0.05, math.cos(math.radians(lat))))


def _extent_m(df):
    lat0 = float(np.nanmean(df["lat"]))
    return ((df["lon"].max() - df["lon"].min()) * 111_320 * math.cos(math.radians(lat0)),
            (df["lat"].max() - df["lat"].min()) * 110_574)


@dataclass
class GediLayer:
    """A GEDI dataset rendered into the flyover (also the parsed form of a `- gedi:` line)."""
    aoi: str = "sewanee"
    source: str = "sliderule"          # sliderule | harmony | h5:<path> | table:<path> | synthetic
    product: str = "l2a"               # l2a | l4a (sliderule) ; l2b (harmony / h5)
    name: Optional[str] = None
    viz: str = "columns"               # comma list: columns, curtains, grid2d, grid3d
    color: Optional[str] = None        # variable for colour (default by product)
    height: Optional[str] = None       # variable for height (default canopy height)
    cmap: Optional[str] = None
    vmin: Optional[float] = None
    vmax: Optional[float] = None
    exaggeration: Union[float, str] = "auto"
    radius: float = 35.0               # m, visual radius of a column (GEDI footprint is ~12.5 m)
    sides: int = 6
    opacity: float = 0.9
    by: Optional[str] = None           # None | year
    t0: Optional[str] = None
    t1: Optional[str] = None
    quality: bool = True
    min_sensitivity: float = 0.9
    max_shots: int = 20_000
    cell: float = 250.0                # m, grid cell for grid2d / grid3d
    legend: bool = True
    fly: bool = False
    after: Optional[str] = None
    moves: Optional[str] = None
    duration: Optional[float] = None
    elev: Optional[float] = None
    drive_id: Optional[str] = None

    @property
    def title(self):
        if self.name:
            return self.name
        lab = VARIABLES.get(self.color_var, (self.color_var,))[0]
        return f"GEDI {self.product.upper()} {lab} ({self.aoi_name})"

    @property
    def aoi_name(self):
        a = str(self.aoi)
        if re.fullmatch(r"[\s\d.,+-]+", a) or isinstance(self.aoi, (tuple, list)):
            return "bbox"
        if a.lower() in AOI_PRESETS:
            return a.replace("_", " ").title()
        return os.path.splitext(os.path.basename(a.split("?")[0]))[0] or "AOI"

    @property
    def color_var(self):
        if self.color:
            return self.color
        return {"l2b": "fhd_normal", "l4a": "agbd"}.get(self.product.lower(), "canopy_height")

    @property
    def height_var(self):
        return self.height or "canopy_height"


def load_gedi(gl: GediLayer, cache_dir: str = "cinematicearth_layers/gedi"):
    """Fetch / read the shots for a GediLayer (cached to Parquet/CSV by AOI + product + dates)."""
    pd = _pd()
    os.makedirs(cache_dir, exist_ok=True)
    src = gl.source.lower()
    key = re.sub(r"[^A-Za-z0-9]+", "_", f"{gl.aoi_name}_{gl.product}_{src}_{gl.t0}_{gl.t1}_{gl.quality}")
    cache = os.path.join(cache_dir, key + ".csv")
    if os.path.exists(cache) and not src.startswith(("h5:", "table:")):
        df = pd.read_csv(cache, parse_dates=["time"])
        return _finish(df)
    aoi = load_aoi(gl.aoi)
    if src == "sliderule":
        df = sliderule_gedi(aoi, gl.product, gl.t0, gl.t1, gl.quality)
    elif src == "harmony":
        files = harmony_l2b(aoi, gl.t0 or "2019-04-18", gl.t1 or "2030-01-01", os.path.join(cache_dir, key + "_h5"))
        df = read_l2b_h5(files, aoi)
    elif src.startswith("h5:"):
        df = read_l2b_h5(gl.source[3:], aoi)
    elif src.startswith("table:"):
        df = read_table(gl.source[6:], aoi)
    elif src == "synthetic":
        df = synthetic_shots(aoi)
    else:
        raise ValueError(f"unknown GEDI source {gl.source!r}")
    if gl.quality and "fhd_normal" in df.columns:
        df = filter_l2b(df, gl.min_sensitivity)
    elif gl.quality and "sensitivity" in df.columns and gl.min_sensitivity:
        df = df[df["sensitivity"] >= gl.min_sensitivity].reset_index(drop=True)
    if gl.t0 and "time" in df.columns:
        df = df[df["time"] >= pd.Timestamp(gl.t0)]
    if gl.t1 and "time" in df.columns:
        df = df[df["time"] <= pd.Timestamp(gl.t1) + pd.Timedelta(days=1)]
    df = df.reset_index(drop=True)
    if not src.startswith(("h5:", "table:")):
        df.to_csv(cache, index=False)
    return df


def _range(v, vmin, vmax):
    v = v[np.isfinite(v)]
    if v.size == 0:
        raise ValueError("no valid values to colour")
    lo = vmin if vmin is not None else float(np.percentile(v, 2))
    hi = vmax if vmax is not None else float(np.percentile(v, 98))
    return lo, (hi if hi > lo else lo + 1e-6)


def _legend(title, units, cmap, vmin, vmax, extra=""):
    from .layers import Layer, legend_png
    return legend_png(Layer(source="", name=title, cmap=cmap, units=units), vmin, vmax, extra)


def _write(path, kml, assets):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("doc.kml", kml)
        for k, v in assets.items():
            z.writestr(k, v)
    return path


def _doc(name, styles, body, legend):
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
            f"<name>{escape(name)}</name>{''.join(styles)}{body}"
            + (('<ScreenOverlay><name>Legend</name><Icon><href>legend.png</href></Icon>'
                '<overlayXY x="0" y="0" xunits="fraction" yunits="fraction"/>'
                '<screenXY x="0.015" y="0.03" xunits="fraction" yunits="fraction"/>'
                '<size x="0.22" y="0" xunits="fraction" yunits="fraction"/></ScreenOverlay>') if legend else "")
            + "</Document></kml>\n")


def _classes(vals, lo, hi, n, cmap, opacity):
    edges = np.linspace(lo, hi, n + 1)
    cls = np.clip(np.digitize(vals, edges[1:-1]), 0, n - 1)
    cm = _cm(cmap)
    styles = []
    for k in range(n):
        rgba = cm((k + 0.5) / n)
        styles.append(f'<Style id="g{k}"><LineStyle><color>{_kml_color(rgba, 1)}</color><width>0</width></LineStyle>'
                      f"<PolyStyle><color>{_kml_color(rgba, opacity)}</color><outline>0</outline></PolyStyle></Style>")
    return cls, edges, styles


def auto_exaggeration(df, hvar, frac=0.04):
    ext = _extent_m(df)
    hmax = float(np.nanpercentile(df[hvar], 98)) if len(df) else 1.0
    return max(1.0, frac * max(1.0, min(ext)) / max(hmax, 1e-6))


def columns_kml(df, gl: GediLayer, ex: float, lo: float, hi: float, cmap: str, n: int = 16):
    cv, hv = gl.color_var, gl.height_var
    cls, edges, styles = _classes(df[cv].values, lo, hi, n, cmap, gl.opacity)
    groups = [[] for _ in range(n)]
    ang = [2 * math.pi * k / gl.sides for k in range(gl.sides)] + [0.0]
    for lat, lon, h, c in zip(df["lat"].values, df["lon"].values, df[hv].values, cls):
        if not np.isfinite(h):
            continue
        top = max(0.5, float(h)) * ex
        ring = " ".join("{1:.7f},{0:.7f},{2:.1f}".format(*_offset(lat, lon, gl.radius * math.sin(a), gl.radius * math.cos(a)), top)
                        for a in ang)
        groups[c].append(f"<Polygon><extrude>1</extrude><altitudeMode>relativeToGround</altitudeMode>"
                         f"<outerBoundaryIs><LinearRing><coordinates>{ring}</coordinates></LinearRing></outerBoundaryIs></Polygon>")
    body = "".join(f"<Placemark><name>{edges[k]:.3g}-{edges[k + 1]:.3g}</name><styleUrl>#g{k}</styleUrl>"
                   f"<MultiGeometry>{''.join(g)}</MultiGeometry></Placemark>" for k, g in enumerate(groups) if g)
    return styles, body, sum(len(g) for g in groups)


def curtains_kml(df, gl: GediLayer, ex: float, lo: float, hi: float, cmap: str, n: int = 16, max_gap: float = 150.0):
    """Vertical walls between consecutive shots along each beam track (height = canopy height x ex)."""
    pd = _pd()
    cv, hv = gl.color_var, gl.height_var
    cls_all, edges, styles = _classes(df[cv].values, lo, hi, n, cmap, gl.opacity)
    d = df.assign(_cls=cls_all)
    keys = [k for k in ("granule", "orbit", "track") if k in d.columns]
    keys += ["beam"] if "beam" in d.columns else []
    if "time" in d.columns and not keys:
        keys = [d["time"].dt.date.rename("_day")]
    groups = [[] for _ in range(n)]
    nseg = 0
    grp = d.groupby(keys, sort=False) if keys else [(None, d)]
    for _, t in grp:
        t = t.sort_values("time") if "time" in t.columns else t.sort_values("lat")
        la, lo_, h, c = t["lat"].values, t["lon"].values, t[hv].values, t["_cls"].values
        for i in range(len(t) - 1):
            if not (np.isfinite(h[i]) and np.isfinite(h[i + 1])):
                continue
            dy = (la[i + 1] - la[i]) * 110_574
            dx = (lo_[i + 1] - lo_[i]) * 111_320 * math.cos(math.radians(la[i]))
            if math.hypot(dx, dy) > max_gap:
                continue
            h1, h2 = max(0.5, h[i]) * ex, max(0.5, h[i + 1]) * ex
            ring = (f"{lo_[i]:.7f},{la[i]:.7f},0 {lo_[i + 1]:.7f},{la[i + 1]:.7f},0 "
                    f"{lo_[i + 1]:.7f},{la[i + 1]:.7f},{h2:.1f} {lo_[i]:.7f},{la[i]:.7f},{h1:.1f} {lo_[i]:.7f},{la[i]:.7f},0")
            groups[c[i]].append(f"<Polygon><altitudeMode>relativeToGround</altitudeMode><outerBoundaryIs>"
                                f"<LinearRing><coordinates>{ring}</coordinates></LinearRing></outerBoundaryIs></Polygon>")
            nseg += 1
    body = "".join(f"<Placemark><name>{edges[k]:.3g}-{edges[k + 1]:.3g}</name><styleUrl>#g{k}</styleUrl>"
                   f"<MultiGeometry>{''.join(g)}</MultiGeometry></Placemark>" for k, g in enumerate(groups) if g)
    return styles, body, nseg


def grid_geotiff(df, var: str, path: str, cell: float = 250.0, stat: str = "mean"):
    """Average shots onto a lon/lat grid (cell metres) and write a GeoTIFF."""
    import rasterio
    from rasterio.transform import from_origin
    lat0 = float(np.nanmean(df["lat"]))
    dlat = cell / 110_574.0
    dlon = cell / (111_320.0 * math.cos(math.radians(lat0)))
    w, e = df["lon"].min() - dlon, df["lon"].max() + dlon
    s, n = df["lat"].min() - dlat, df["lat"].max() + dlat
    W, H = int(math.ceil((e - w) / dlon)), int(math.ceil((n - s) / dlat))
    c = ((df["lon"].values - w) / dlon).astype(int).clip(0, W - 1)
    r = ((n - df["lat"].values) / dlat).astype(int).clip(0, H - 1)
    v = df[var].values.astype(float)
    ok = np.isfinite(v)
    tot = np.zeros((H, W))
    cnt = np.zeros((H, W))
    np.add.at(tot, (r[ok], c[ok]), v[ok])
    np.add.at(cnt, (r[ok], c[ok]), 1)
    with np.errstate(invalid="ignore", divide="ignore"):
        grid = np.where(cnt > 0, tot / cnt, np.nan).astype("float32")
    with rasterio.open(path, "w", driver="GTiff", height=H, width=W, count=1, dtype="float32", crs="EPSG:4326",
                       transform=from_origin(w, n, dlon, dlat), nodata=np.nan) as ds:
        ds.write(grid, 1)
    return path


def gedi_kmz(df, gl: GediLayer, out_dir: str = "cinematicearth_layers"):
    """Write KMZ(s) for a GEDI DataFrame. Returns (files, info dict)."""
    os.makedirs(out_dir, exist_ok=True)
    cv, hv = gl.color_var, gl.height_var
    for v in (cv, hv):
        if v not in df.columns:
            raise ValueError(f"variable {v!r} not in GEDI data (have: {', '.join(map(str, df.columns))})")
    df = df[np.isfinite(df[cv].values) & np.isfinite(df[hv].values)].reset_index(drop=True)
    if len(df) == 0:
        raise ValueError(f"{gl.title}: no GEDI shots left after filtering")
    if len(df) > gl.max_shots:
        df = df.sample(gl.max_shots, random_state=0).reset_index(drop=True)
    label, units, cdef = VARIABLES.get(cv, (cv, "", "viridis"))
    cmap = gl.cmap or cdef
    lo, hi = _range(df[cv].values.astype(float), gl.vmin, gl.vmax)
    ex = auto_exaggeration(df, hv) if str(gl.exaggeration).lower() == "auto" else float(gl.exaggeration)
    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", gl.title).strip("_")
    vizs = [v.strip().lower() for v in gl.viz.split(",") if v.strip()]
    hl = VARIABLES.get(hv, (hv, ""))
    legend_extra = f"height = {hl[0].lower()} x{ex:.3g}" if hv != cv else f"heights x{ex:.3g}"
    leg = {"legend.png": _legend(f"GEDI {label}", units, cmap, lo, hi, legend_extra)} if gl.legend else {}
    subsets = [(None, df)]
    if (gl.by or "").lower() == "year" and "year" in df.columns:
        subsets = [(int(y), d) for y, d in sorted(df.groupby("year"), key=lambda x: x[0])]
    files, counts = [], {}
    for tag, d in subsets:
        suffix = f"_{tag}" if tag is not None else ""
        for viz in vizs:
            nm = f"{gl.title}{(' ' + str(tag)) if tag is not None else ''} [{viz}]"
            if viz == "columns":
                st, body, k = columns_kml(d, gl, ex, lo, hi, cmap)
            elif viz == "curtains":
                st, body, k = curtains_kml(d, gl, ex, lo, hi, cmap)
            elif viz in ("grid2d", "grid3d", "grid"):
                from .layers import Layer, convert_layer
                tif = grid_geotiff(d, cv, os.path.join(out_dir, f"{slug}{suffix}_{cv}.tif"), gl.cell)
                lay = Layer(source=tif, name=f"GEDI {label}{(' ' + str(tag)) if tag is not None else ''}",
                            mode="3d" if viz == "grid3d" else "2d", cmap=cmap, vmin=lo, vmax=hi, units=units,
                            opacity=gl.opacity, legend=gl.legend, max_cells=20_000)
                res = convert_layer(lay, out_dir, verbose=False)
                files += res.files
                counts[f"{viz}{suffix}"] = res.n_polygons
                continue
            else:
                raise ValueError(f"unknown GEDI viz {viz!r} (columns, curtains, grid2d, grid3d)")
            p = os.path.join(out_dir, f"{slug}{suffix}_{viz}.kmz")
            _write(p, _doc(nm, st, f"<Folder><name>{escape(nm)}</name>{body}</Folder>", gl.legend), leg)
            files.append(p)
            counts[f"{viz}{suffix}"] = k
    info = {"n_shots": int(len(df)), "vmin": lo, "vmax": hi, "exaggeration": ex, "counts": counts,
            "years": sorted({int(y) for y in df["year"].dropna()}) if "year" in df.columns else [],
            "color": cv, "height": hv, "label": label, "units": units}
    return files, info


def convert_gedi(gl: GediLayer, out_dir="cinematicearth_layers", drive_dir=None, verbose=True, df=None):
    """Fetch + render a GediLayer. Returns a cinematicearth.layers.LayerResult."""
    from .layers import LayerResult, drive_file_id
    import shutil
    aoi = load_aoi(gl.aoi)
    if df is None:
        df = load_gedi(gl, os.path.join(out_dir, "gedi"))
    files, info = gedi_kmz(df, gl, out_dir)
    ids = [gl.drive_id] * len(files) if gl.drive_id else [None] * len(files)
    if drive_dir:
        os.makedirs(drive_dir, exist_ok=True)
        for k, f in enumerate(files):
            dst = os.path.join(drive_dir, os.path.basename(f))
            shutil.copy2(f, dst)
            ids[k] = ids[k] or drive_file_id(dst)
    w, s, e, n = aoi.bbox
    ext = ((e - w) * 111_320 * math.cos(math.radians(0.5 * (s + n))), (n - s) * 110_574)
    hmax = float(np.nanpercentile(df[gl.height_var], 98)) if len(df) else 0.0
    res = LayerResult(gl.title, "gedi:" + gl.viz, files, aoi.bbox, aoi.center, ext, info["vmin"], info["vmax"],
                      info["exaggeration"], sum(info["counts"].values()), ids)
    res.vmax_height = hmax
    if "elev_ground" in df.columns and df["elev_ground"].notna().any():
        res.elev_hint = float(np.nanmedian(df["elev_ground"]))
    if verbose:
        yrs = info["years"]
        print(f"gedi {gl.title}: {info['n_shots']} shots"
              + (f" ({yrs[0]}-{yrs[-1]})" if yrs else "")
              + f" | colour {info['color']} {info['vmin']:.3g}..{info['vmax']:.3g} | height {info['height']} x{info['exaggeration']:.3g}"
              + f" -> {', '.join(os.path.basename(f) for f in files)}")
    return res
