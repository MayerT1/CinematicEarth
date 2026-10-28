"""GeoTIFF products -> KML/KMZ overlays for Google Earth Studio.

Earth Studio renders KML Polygons, Placemarks, GroundOverlays and ScreenOverlays
(https://earth.google.com/studio/docs/advanced-features/overlays-and-kmls/), so:

* ``mode=2d``  -> a colour-mapped PNG draped on the terrain (GroundOverlay) in a KMZ
* ``mode=3d``  -> the raster values become extruded polygons (height = value x
                  exaggeration), colour-mapped, in a KMZ. ``style=terraces`` (default)
                  merges cells of the same colour class into stepped 3D shapes;
                  ``style=prisms`` makes one column per cell.
* ``mode=both`` -> both of the above
* ``legend=yes`` -> a colour bar fixed on screen (ScreenOverlay) inside each KMZ

Requires the ``layers`` extra: ``pip install "CinematicEarth[layers]"``
(rasterio, matplotlib, pillow, gdown).
"""
from __future__ import annotations

import io as _io
import math
import os
import re
import shutil
import time
import zipfile
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Union
from xml.sax.saxutils import escape

import numpy as np

TIF_RE = re.compile(r"\.(tif|tiff|vrt|img)$", re.I)
DRIVE_RE = re.compile(r"(?:drive\.google\.com/(?:file/d/|open\?id=|uc\?id=)|^drive:)([A-Za-z0-9_-]{20,})")


@dataclass
class Layer:
    source: str                         # path, Google Drive link, drive:<id>, or http(s) URL
    name: Optional[str] = None          # display name (default: file name)
    mode: str = "2d"                    # 2d | 3d | both
    band: int = 1
    cmap: str = "viridis"               # any matplotlib colormap name
    vmin: Optional[float] = None        # colour range (default: 2nd-98th percentile)
    vmax: Optional[float] = None
    min_value: Optional[float] = None   # values below this are transparent / not extruded
    nodata: Optional[float] = None      # override the file's nodata value
    opacity: float = 0.85
    exaggeration: Union[float, str] = "auto"   # 3D height multiplier ("auto" -> fits extent)
    base: float = 0.0                   # m above ground where 3D shapes start
    levels: int = 12                    # 3D colour/height classes (terraces)
    style: str = "terraces"             # terraces | prisms
    max_cells: int = 30_000             # 3D grid budget (cells after downsampling)
    max_pixels: int = 4096              # 2D image longest side
    legend: bool = True
    units: str = ""
    fly: bool = False                   # add a stop that orbits this product
    moves: Optional[str] = None         # camera moves for the fly stop
    duration: Optional[float] = None    # seconds for the fly stop
    elev: Optional[float] = None        # ground elevation for the fly stop
    drive_id: Optional[str] = None      # Drive file id of the KMZ (if already uploaded)
    after: Optional[str] = None         # fly stop goes after the stop with this name (default: list order / end)

    @property
    def title(self):
        return self.name or os.path.splitext(os.path.basename(self.source.split("?")[0]))[0]


@dataclass
class LayerResult:
    name: str
    mode: str
    files: List[str]
    bounds: tuple                       # west, south, east, north (deg)
    center: tuple                       # lat, lon
    extent_m: tuple                     # width, height (m)
    vmin: float
    vmax: float
    exaggeration: Optional[float] = None
    n_polygons: int = 0
    drive_ids: List[Optional[str]] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)


def _need():
    try:
        import rasterio  # noqa
        import matplotlib  # noqa
        from PIL import Image  # noqa
    except ImportError as e:
        raise ImportError('GeoTIFF layers need: pip install "CinematicEarth[layers]"') from e


# ---------------- sources ----------------
def resolve_source(src: str, cache_dir: str = "cinematicearth_layers/src") -> str:
    """Local path for a layer source; downloads Google Drive links / ids and URLs."""
    if os.path.exists(src):
        return src
    m = DRIVE_RE.search(src)
    os.makedirs(cache_dir, exist_ok=True)
    if m:
        fid = m.group(1)
        out = os.path.join(cache_dir, f"{fid}.tif")
        if not os.path.exists(out):
            try:
                import gdown
            except ImportError as e:
                raise ImportError("Drive downloads need gdown: pip install gdown") from e
            gdown.download(id=fid, output=out, quiet=False)
        return out
    if src.startswith(("http://", "https://")):
        import urllib.request
        out = os.path.join(cache_dir, os.path.basename(src.split("?")[0]) or "layer.tif")
        if not os.path.exists(out):
            urllib.request.urlretrieve(src, out)
        return out
    raise FileNotFoundError(f"layer source not found: {src}")


# ---------------- raster ----------------
def read_wgs84(path, band=1, max_dim=4096, nodata=None):
    """Reproject one band to EPSG:4326. Returns (array with NaN, (west,south,east,north), info)."""
    import rasterio
    from rasterio.warp import calculate_default_transform, reproject, Resampling
    with rasterio.open(path) as ds:
        nd = nodata if nodata is not None else ds.nodata
        src = ds.read(band).astype("float64")
        if nd is not None:
            src[src == nd] = np.nan
        src[~np.isfinite(src)] = np.nan
        info = {"crs": str(ds.crs), "shape": ds.shape, "count": ds.count,
                "res": ds.res, "dtype": ds.dtypes[band - 1],
                "descriptions": list(ds.descriptions)}
        dst_crs = "EPSG:4326"
        if ds.crs is None:
            raise ValueError(f"{path} has no CRS; cannot place it on the globe")
        tr, w, h = calculate_default_transform(ds.crs, dst_crs, ds.width, ds.height, *ds.bounds)
        scale = max(1.0, max(w, h) / max_dim)
        w2, h2 = max(1, int(round(w / scale))), max(1, int(round(h / scale)))
        sx, sy = w / w2, h / h2
        tr2 = type(tr)(tr.a * sx, tr.b * sy, tr.c, tr.d * sx, tr.e * sy, tr.f)   # == tr * scale(sx, sy)
        dst = np.full((h2, w2), np.nan)
        reproject(src, dst, src_transform=ds.transform, src_crs=ds.crs, src_nodata=np.nan,
                  dst_transform=tr2, dst_crs=dst_crs, dst_nodata=np.nan,
                  resampling=Resampling.average if scale > 1.5 else Resampling.bilinear)
    west, north = tr2.c, tr2.f
    east, south = west + tr2.a * w2, north + tr2.e * h2
    return dst, (west, south, east, north), info


def _extent_m(b):
    west, south, east, north = b
    lat = math.radians(0.5 * (south + north))
    return (abs(east - west) * 111_320 * math.cos(lat), abs(north - south) * 110_574)


def _range(arr, layer):
    v = arr[np.isfinite(arr)]
    if layer.min_value is not None:
        v = v[v >= layer.min_value]
    if v.size == 0:
        raise ValueError(f"layer {layer.title!r}: no valid pixels")
    lo = layer.vmin if layer.vmin is not None else float(np.percentile(v, 2))
    hi = layer.vmax if layer.vmax is not None else float(np.percentile(v, 98))
    if hi <= lo:
        hi = lo + 1e-6
    return lo, hi


def _cmap(name):
    import matplotlib
    try:
        return matplotlib.colormaps[name]
    except Exception:
        import matplotlib.cm as cm
        return cm.get_cmap(name)


def _kml_color(rgba, alpha):
    r, g, b = (int(round(255 * c)) for c in rgba[:3])
    return f"{int(round(255 * alpha)):02x}{b:02x}{g:02x}{r:02x}"


# ---------------- legend ----------------
def legend_png(layer: Layer, vmin, vmax, extra: str = "") -> bytes:
    import matplotlib
    matplotlib.use("Agg", force=False)
    import matplotlib.pyplot as plt
    fig = plt.figure(figsize=(3.6, 1.05), dpi=150)
    fig.patch.set_alpha(0)
    bg = fig.add_axes([0, 0, 1, 1])
    bg.add_patch(plt.Rectangle((0, 0), 1, 1, color=(0.05, 0.07, 0.09, 0.72), transform=bg.transAxes))
    bg.axis("off")
    ax = fig.add_axes([0.07, 0.30, 0.86, 0.22])
    grad = np.linspace(0, 1, 256)[None, :]
    ax.imshow(grad, aspect="auto", cmap=_cmap(layer.cmap), extent=[vmin, vmax, 0, 1])
    ax.set_yticks([])
    ax.tick_params(colors="white", labelsize=7, length=2)
    for s in ax.spines.values():
        s.set_visible(False)
    title = layer.title + (f" ({layer.units})" if layer.units else "")
    fig.text(0.07, 0.72, title, color="white", fontsize=8.5, weight="bold")
    if extra:
        fig.text(0.07, 0.06, extra, color=(0.8, 0.85, 0.9), fontsize=6.5)
    buf = _io.BytesIO()
    fig.savefig(buf, format="png", transparent=True)
    plt.close(fig)
    return buf.getvalue()


def _screen_overlay(name="legend.png"):
    return ("<ScreenOverlay><name>Legend</name><Icon><href>" + name + "</href></Icon>"
            '<overlayXY x="0" y="0" xunits="fraction" yunits="fraction"/>'
            '<screenXY x="0.015" y="0.03" xunits="fraction" yunits="fraction"/>'
            '<size x="0.22" y="0" xunits="fraction" yunits="fraction"/></ScreenOverlay>')


def _write_kmz(path, kml: str, assets: dict):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("doc.kml", kml)
        for n, data in assets.items():
            z.writestr(n, data)
    return path


# ---------------- 2D: GroundOverlay ----------------
def to_ground_overlay(arr, bounds, layer: Layer, vmin, vmax, out_path):
    from PIL import Image
    cm = _cmap(layer.cmap)
    norm = np.clip((arr - vmin) / (vmax - vmin), 0, 1)
    rgba = cm(np.nan_to_num(norm))
    valid = np.isfinite(arr)
    if layer.min_value is not None:
        valid &= arr >= layer.min_value
    rgba[..., 3] = np.where(valid, layer.opacity, 0.0)
    img = Image.fromarray((rgba * 255).astype(np.uint8), "RGBA")
    buf = _io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    west, south, east, north = bounds
    name = escape(layer.title)
    kml = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
           f"<name>{name}</name>"
           f"<GroundOverlay><name>{name}</name><drawOrder>1</drawOrder>"
           "<Icon><href>overlay.png</href></Icon><altitudeMode>clampToGround</altitudeMode>"
           f"<LatLonBox><north>{north:.8f}</north><south>{south:.8f}</south>"
           f"<east>{east:.8f}</east><west>{west:.8f}</west></LatLonBox></GroundOverlay>"
           + (_screen_overlay() if layer.legend else "") +
           "</Document></kml>\n")
    assets = {"overlay.png": buf.getvalue()}
    if layer.legend:
        assets["legend.png"] = legend_png(layer, vmin, vmax)
    return _write_kmz(out_path, kml, assets)


# ---------------- 3D: extruded polygons ----------------
def _block_reduce(arr, bounds, max_cells):
    h, w = arr.shape
    f = max(1, int(math.ceil(math.sqrt(h * w / max_cells))))
    if f == 1:
        return arr, bounds
    H, W = h // f, w // f
    a = arr[:H * f, :W * f].reshape(H, f, W, f)
    import warnings
    with np.errstate(all="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        cnt = np.isfinite(a).sum(axis=(1, 3))
        red = np.where(cnt >= (f * f) / 2, np.nanmean(a, axis=(1, 3)), np.nan)
    west, south, east, north = bounds
    east2 = west + (east - west) * (W * f) / w
    south2 = north - (north - south) * (H * f) / h
    return red, (west, south2, east2, north)


def auto_exaggeration(extent_m, vmax, base=0.0):
    """Tallest shape ~5% of the product's smaller side (never < 1x)."""
    target = 0.05 * min(extent_m)
    return max(1.0, target / max(abs(vmax), 1e-9))


def to_extruded(arr, bounds, layer: Layer, vmin, vmax, out_path):
    from rasterio import features
    from rasterio.transform import from_bounds
    grid, gb = _block_reduce(arr, bounds, layer.max_cells if layer.style == "terraces"
                             else min(layer.max_cells, 12_000))
    H, W = grid.shape
    tr = from_bounds(*gb, W, H)
    ext = _extent_m(gb)
    ex = auto_exaggeration(ext, vmax) if str(layer.exaggeration).lower() == "auto" else float(layer.exaggeration)
    valid = np.isfinite(grid)
    if layer.min_value is not None:
        valid &= grid >= layer.min_value
    n = max(2, int(layer.levels))
    edges = np.linspace(vmin, vmax, n + 1)
    cls = np.clip(np.digitize(grid, edges[1:-1]), 0, n - 1)
    cm = _cmap(layer.cmap)
    styles, marks, npoly = [], [], 0

    def ring(coords, hgt):
        return " ".join(f"{x:.7f},{y:.7f},{hgt:.1f}" for x, y in coords)

    def poly(geom, hgt):
        rings = geom["coordinates"]
        s = (f"<Polygon><extrude>1</extrude><altitudeMode>relativeToGround</altitudeMode>"
             f"<outerBoundaryIs><LinearRing><coordinates>{ring(rings[0], hgt)}</coordinates></LinearRing></outerBoundaryIs>")
        for r in rings[1:]:
            s += f"<innerBoundaryIs><LinearRing><coordinates>{ring(r, hgt)}</coordinates></LinearRing></innerBoundaryIs>"
        return s + "</Polygon>"

    for k in range(n):
        mid = 0.5 * (edges[k] + edges[k + 1])
        col = _kml_color(cm((mid - vmin) / (vmax - vmin)), layer.opacity)
        line = _kml_color(tuple(0.75 * c for c in cm((mid - vmin) / (vmax - vmin))[:3]), min(1.0, layer.opacity + 0.1))
        styles.append(f'<Style id="c{k}"><LineStyle><color>{line}</color><width>0.5</width></LineStyle>'
                      f"<PolyStyle><color>{col}</color><outline>0</outline></PolyStyle></Style>")
        if layer.style == "prisms":
            continue
        m = valid & (cls == k)
        if not m.any():
            continue
        hgt = layer.base + max(edges[k + 1], 0) * ex
        geoms = [g for g, _ in features.shapes(m.astype("uint8"), mask=m, transform=tr, connectivity=4)]
        npoly += len(geoms)
        lo, hi = edges[k], edges[k + 1]
        marks.append(f"<Placemark><name>{lo:.3g} to {hi:.3g}{(' ' + escape(layer.units)) if layer.units else ''}"
                     f"</name><styleUrl>#c{k}</styleUrl><MultiGeometry>"
                     + "".join(poly(g, hgt) for g in geoms) + "</MultiGeometry></Placemark>")
    if layer.style == "prisms":
        dx, dy = tr.a, tr.e
        by = [[] for _ in range(n)]
        for r, c in zip(*np.nonzero(valid)):
            x0, y0 = tr.c + c * dx, tr.f + r * dy
            hgt = layer.base + max(grid[r, c], 0) * ex
            g = {"coordinates": [[(x0, y0), (x0 + dx, y0), (x0 + dx, y0 + dy), (x0, y0 + dy), (x0, y0)]]}
            by[cls[r, c]].append(poly(g, hgt))
        for k in range(n):
            if by[k]:
                npoly += len(by[k])
                marks.append(f"<Placemark><name>class {k + 1}</name><styleUrl>#c{k}</styleUrl>"
                             f"<MultiGeometry>{''.join(by[k])}</MultiGeometry></Placemark>")
    name = escape(layer.title)
    kml = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
           f"<name>{name} (3D)</name>" + "".join(styles) +
           f"<Folder><name>{name}</name>" + "".join(marks) + "</Folder>"
           + (_screen_overlay() if layer.legend else "") + "</Document></kml>\n")
    assets = {}
    if layer.legend:
        assets["legend.png"] = legend_png(layer, vmin, vmax, f"heights x{ex:.3g}")
    _write_kmz(out_path, kml, assets)
    return out_path, ex, npoly


# ---------------- Drive ----------------
def drive_file_id(path, wait=60.0) -> Optional[str]:
    """Google Drive file id of a file under a Colab Drive mount (via the FUSE xattr)."""
    if not os.path.abspath(path).startswith("/content/drive"):
        try:
            v = os.getxattr(path, "user.drive.id")
            return v.decode() if isinstance(v, bytes) else str(v)
        except Exception:
            return None
    t0 = time.time()
    while True:
        try:
            v = os.getxattr(path, "user.drive.id")
            return v.decode() if isinstance(v, bytes) else str(v)
        except Exception:
            if time.time() - t0 > wait:
                return None
            time.sleep(2.0)


# ---------------- driver ----------------
def convert_layer(layer: Layer, out_dir="cinematicearth_layers", drive_dir: Optional[str] = None,
                  verbose=True) -> LayerResult:
    _need()
    os.makedirs(out_dir, exist_ok=True)
    path = resolve_source(layer.source, os.path.join(out_dir, "src"))
    arr, bounds, info = read_wgs84(path, layer.band, layer.max_pixels, layer.nodata)
    vmin, vmax = _range(arr, layer)
    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", layer.title).strip("_") or "layer"
    files, ex, npoly = [], None, 0
    mode = layer.mode.lower()
    if mode in ("2d", "both"):
        files.append(to_ground_overlay(arr, bounds, layer, vmin, vmax, os.path.join(out_dir, f"{slug}_2d.kmz")))
    if mode in ("3d", "both"):
        p, ex, npoly = to_extruded(arr, bounds, layer, vmin, vmax, os.path.join(out_dir, f"{slug}_3d.kmz"))
        files.append(p)
    if mode not in ("2d", "3d", "both"):
        raise ValueError(f"layer {layer.title!r}: mode must be 2d, 3d or both")
    ids = [layer.drive_id] * len(files) if layer.drive_id else [None] * len(files)
    if drive_dir:
        os.makedirs(drive_dir, exist_ok=True)
        for k, f in enumerate(files):
            dst = os.path.join(drive_dir, os.path.basename(f))
            shutil.copy2(f, dst)
            ids[k] = ids[k] or drive_file_id(dst)
    west, south, east, north = bounds
    res = LayerResult(layer.title, mode, files, bounds, (0.5 * (south + north), 0.5 * (west + east)),
                      _extent_m(bounds), vmin, vmax, ex, npoly, ids)
    if verbose:
        w, h = res.extent_m
        msg = (f"layer {res.name}: {info['crs']} {info['shape'][1]}x{info['shape'][0]} band {layer.band}/{info['count']}"
               f" -> {', '.join(os.path.basename(f) for f in files)} | {w / 1000:.1f} x {h / 1000:.1f} km"
               f" | colour {vmin:.3g}..{vmax:.3g}{(' ' + layer.units) if layer.units else ''}")
        if ex:
            msg += f" | 3D x{ex:.3g}, {npoly} polygons"
        print(msg)
        for f in files:
            if os.path.getsize(f) > 20e6:
                print(f"  note: {os.path.basename(f)} is {os.path.getsize(f) / 1e6:.0f} MB; lower max_cells/levels "
                      "if Earth Studio is slow")
    return res


def fly_stop_for(layer: Layer, res: LayerResult, settings):
    """A Stop that orbits the product, framed to its extent."""
    from .model import Stop
    diag = math.hypot(*res.extent_m)
    top = (res.exaggeration or 0) * max(res.vmax, 0)
    r_end = max(1500.0, 0.85 * diag + 2 * top)
    r_start = 1.6 * r_end
    moves = layer.moves or f"orbit {settings.orbit} + zoom {r_start:.0f}>{r_end:.0f}"
    lat, lon = res.center
    return Stop(name=res.name, lat=lat, lon=lon, elev=layer.elev if layer.elev is not None else 0.0,
                duration=layer.duration, moves=moves, label=res.name,
                note=(f"{res.vmin:.3g}-{res.vmax:.3g} {layer.units}".strip() if layer.units else None))
