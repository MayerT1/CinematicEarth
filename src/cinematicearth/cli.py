"""Command line interface.

    cinematicearth build stops.md -o flyover.esp --speed slow --duration 180
    cinematicearth build "Huntsville, AL; Santa Fe, NM" --geocode
    cinematicearth preview stops.md -o preview.png
    cinematicearth annotate flyover.plan.json render.zip -o flyover_final.mp4
    cinematicearth annotate flyover.plan.json part01.zip part02.zip ...   (split projects)
    cinematicearth layer chm.tif --mode 3d --units m   # GeoTIFF -> 3D .kmz
    cinematicearth gedi sewanee --product l2a --viz columns,curtains --by year   # GEDI -> 3D KMZ
    cinematicearth moves          # print the camera-move reference
    cinematicearth init stops.md  # write an example stop file
"""
from __future__ import annotations

import argparse
import os
import sys

from . import build as _build, load, plan_flyover, __version__
from .model import Settings

EXAMPLE = """---
title: My flyover
speed: slow          # glacial | slow | medium | fast | number
stop_duration: 8     # seconds circling each stop
orbit: 45            # degrees of orbit per stop
tilt: 60             # 0 = straight down, 90 = horizon
# duration: 150      # optional total length (s); transits are re-paced to fit
---

# Stops:  name | lat, lon[, elev] | camera moves | key=value ...
- Huntsville, AL | 34.7304, -86.5861, 190 | orbit 60 + zoom 8km>3km | note=NASA EarthRISE
- Santa Fe, NM | 35.6870, -105.9378, 2130 | orbit 30 + tilt 55>68 @5s; truck 2km + zoom 2.5km
- Fort Collins, CO | 40.5853, -105.0844, 1525 | slow 1.5
"""


def _overrides(a):
    keys = ["duration", "speed", "stop_duration", "orbit", "tilt", "fps", "width", "height",
            "range_start", "range_end", "title", "ease", "max_part_seconds", "keyframe_tol_px", "cut_km",
            "direction", "layers_dir", "drive_dir"]
    ov = {k: getattr(a, k) for k in keys if getattr(a, k, None) is not None}
    if getattr(a, "no_intro", False):
        ov["intro"] = False
    if getattr(a, "no_outro", False):
        ov["outro"] = False
    if getattr(a, "every_frame", False):
        ov["keyframe_every_frame"] = True
    return ov


def _source(src):
    if os.path.exists(src):
        return src
    if src == "-":
        return sys.stdin.read()
    # inline list: "A; B; C" or newline separated
    return "\n".join("- " + s.strip() for s in src.replace("\n", ";").split(";") if s.strip())


def _add_common(p):
    p.add_argument("source", help=".md/.csv/.json/.yaml/.txt file, '-' for stdin, or 'A; B; C' inline list")
    p.add_argument("--duration", type=float, help="total seconds (default: auto from pacing)")
    p.add_argument("--speed", help="glacial | slow | medium | fast | number")
    p.add_argument("--stop-duration", dest="stop_duration", type=float)
    p.add_argument("--orbit", type=float, help="default orbit degrees per stop")
    p.add_argument("--tilt", type=float)
    p.add_argument("--range-start", dest="range_start", type=float)
    p.add_argument("--range-end", dest="range_end", type=float)
    p.add_argument("--fps", type=int)
    p.add_argument("--width", type=int)
    p.add_argument("--height", type=int)
    p.add_argument("--ease", choices=["smooth", "sine", "linear"])
    p.add_argument("--split", dest="max_part_seconds", type=float,
                   help="split into several .esp projects of at most N seconds (lighter for Earth Studio)")
    p.add_argument("--keyframe-tol", dest="keyframe_tol_px", type=float, help="px drift allowed at stops (default 3)")
    p.add_argument("--cut-km", dest="cut_km", type=float, help="hops longer than this become hard cuts")
    p.add_argument("--direction", help="orbit direction: alternate | 1 | -1")
    p.add_argument("--layers-dir", dest="layers_dir", help="where GeoTIFF layers are converted to .kmz")
    p.add_argument("--drive-dir", dest="drive_dir",
                   help="Colab: copy layer .kmz here (under /content/drive) and link them into the .esp")
    p.add_argument("--every-frame", action="store_true", help="one keyframe per frame (big .esp)")
    p.add_argument("--title")
    p.add_argument("--no-intro", action="store_true")
    p.add_argument("--no-outro", action="store_true")
    p.add_argument("--geocode", action="store_true", help="look up missing lat/lon (Nominatim)")
    p.add_argument("--elevation", action="store_true", help="look up missing ground elevation (Open-Meteo)")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="cinematicearth", description="Cinematic Google Earth Studio flyovers")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="write .esp (+ .kml, .plan.json)")
    _add_common(b)
    b.add_argument("-o", "--out", default="flyover.esp")
    b.add_argument("--template", help="an .esp exported from Earth Studio to inject keyframes into")
    b.add_argument("--no-kml", action="store_true")

    pv = sub.add_parser("preview", help="plot ground track / altitude / pacing")
    _add_common(pv)
    pv.add_argument("-o", "--out", default="flyover_preview.png")

    an = sub.add_parser("annotate", help="burn annotations into an Earth Studio render")
    an.add_argument("plan", help="the .plan.json written by build")
    an.add_argument("render", nargs="+", help="Earth Studio render(s): .zip of frames, frame folder, or video; "
                                               "one per project part, in order")
    an.add_argument("-o", "--out", default="flyover_final.mp4")
    an.add_argument("--accent", default="#FFB000")
    an.add_argument("--no-coords", action="store_true")
    an.add_argument("--no-counter", action="store_true")
    an.add_argument("--attribution", default="Google Earth")

    ly = sub.add_parser("layer", help="convert a GeoTIFF to a 2D / 3D .kmz overlay")
    ly.add_argument("source", help="GeoTIFF path, Google Drive link, drive:<id>, or URL")
    ly.add_argument("--mode", default="2d", choices=["2d", "3d", "both"])
    ly.add_argument("--name")
    ly.add_argument("--band", type=int, default=1)
    ly.add_argument("--cmap", default="viridis")
    ly.add_argument("--vmin", type=float)
    ly.add_argument("--vmax", type=float)
    ly.add_argument("--min-value", dest="min_value", type=float, help="values below this are transparent")
    ly.add_argument("--units", default="")
    ly.add_argument("--opacity", type=float, default=0.85)
    ly.add_argument("--exaggeration", default="auto", help="3D height multiplier or 'auto'")
    ly.add_argument("--levels", type=int, default=12, help="3D colour/height classes")
    ly.add_argument("--style", default="terraces", choices=["terraces", "prisms"])
    ly.add_argument("--max-cells", dest="max_cells", type=int, default=30000)
    ly.add_argument("--no-legend", action="store_true")
    ly.add_argument("-o", "--out-dir", default="cinematicearth_layers")
    ly.add_argument("--drive-dir", dest="drive_dir")

    gd = sub.add_parser("gedi", help="GEDI lidar shots (SlideRule L2A/L4A, Harmony L2B, h5, csv) -> 3D KMZ layers")
    gd.add_argument("aoi", nargs="?", help="'sewanee' or a GeoJSON path/URL (or use --bbox)")
    gd.add_argument("--bbox", help="west,south,east,north  e.g. --bbox=-85.99,35.13,-85.86,35.24")
    gd.add_argument("--source", default="sliderule", help="sliderule | harmony | h5:<file or dir> | table:<csv/parquet> | synthetic")
    gd.add_argument("--product", default="l2a", help="l2a | l4a (sliderule), l2b (harmony / h5)")
    gd.add_argument("--viz", default="columns", help="comma list: columns, curtains, grid2d, grid3d")
    gd.add_argument("--color", help="colour variable (default: fhd_normal for l2b, agbd for l4a, else canopy_height)")
    gd.add_argument("--height", help="height variable (default canopy_height)")
    gd.add_argument("--cmap")
    gd.add_argument("--by", choices=["year"], help="one KMZ per year (time series)")
    gd.add_argument("--t0", help="start date YYYY-MM-DD")
    gd.add_argument("--t1", help="end date YYYY-MM-DD")
    gd.add_argument("--exaggeration", default="auto")
    gd.add_argument("--radius", type=float, default=35.0, help="column radius (m)")
    gd.add_argument("--max-shots", dest="max_shots", type=int, default=20000)
    gd.add_argument("--no-quality", action="store_true", help="keep low-quality / degraded shots")
    gd.add_argument("--name")
    gd.add_argument("-o", "--out-dir", default="cinematicearth_layers")
    gd.add_argument("--drive-dir", dest="drive_dir")

    sm = sub.add_parser("simulate", help="wireframe preview MP4 of an .esp (check motion before Earth Studio)")
    sm.add_argument("esp")
    sm.add_argument("plan", help="the .plan.json written by build")
    sm.add_argument("-o", "--out", default="flyover_wireframe.mp4")
    sm.add_argument("--width", type=int, default=640)
    sm.add_argument("--height", type=int, default=360)
    sm.add_argument("--fps", type=int, default=15)
    sm.add_argument("--start", type=float, default=0.0)
    sm.add_argument("--seconds", type=float)

    sk = sub.add_parser("smoketest", help="write a tiny 10 s one-city .esp to check Earth Studio import")
    sk.add_argument("-o", "--out", default="test_tiny.esp")

    sub.add_parser("moves", help="print the camera-move reference")
    ini = sub.add_parser("init", help="write an example stops file")
    ini.add_argument("path", nargs="?", default="stops.md")

    a = ap.parse_args(argv)
    if a.cmd == "build":
        plan = _build(_source(a.source), out=a.out, kml=not a.no_kml, template=a.template,
                      geocode=a.geocode, elevation=a.elevation, **_overrides(a))
        for f in plan.esp_files:
            print(f"wrote {f}")
    elif a.cmd == "preview":
        from .preview import plot_plan
        settings, stops = load(_source(a.source), **_overrides(a))
        if a.geocode or a.elevation:
            from .geocode import resolve
            resolve(stops, need_coords=a.geocode, need_elev=a.elevation)
        plan = plan_flyover(stops, settings)
        print(plan.summary())
        plot_plan(plan, a.out, show=False)
        print(f"wrote {a.out}")
    elif a.cmd == "annotate":
        from .overlay import annotate_video, OverlayStyle
        st = OverlayStyle(accent=a.accent, show_coords=not a.no_coords, show_counter=not a.no_counter,
                          attribution=a.attribution)
        annotate_video(a.render if len(a.render) > 1 else a.render[0], a.plan, a.out, st)
        print(f"wrote {a.out}")
    elif a.cmd == "layer":
        from .layers import Layer, convert_layer
        ex = a.exaggeration if str(a.exaggeration).lower() == "auto" else float(a.exaggeration)
        lay = Layer(source=a.source, name=a.name, mode=a.mode, band=a.band, cmap=a.cmap, vmin=a.vmin, vmax=a.vmax,
                    min_value=a.min_value, units=a.units, opacity=a.opacity, exaggeration=ex, levels=a.levels,
                    style=a.style, max_cells=a.max_cells, legend=not a.no_legend)
        res = convert_layer(lay, a.out_dir, a.drive_dir)
        for f, d in zip(res.files, res.drive_ids):
            print(f"wrote {f}" + (f"  (Drive id {d})" if d else ""))
    elif a.cmd == "gedi":
        from .gedi import GediLayer, convert_gedi
        ex = a.exaggeration if str(a.exaggeration).lower() == "auto" else float(a.exaggeration)
        if not (a.aoi or a.bbox):
            raise SystemExit("give an AOI ('sewanee', a GeoJSON) or --bbox=w,s,e,n")
        gl = GediLayer(aoi=a.bbox or a.aoi, source=a.source, product=a.product, viz=a.viz, color=a.color, height=a.height,
                       cmap=a.cmap, by=a.by, t0=a.t0, t1=a.t1, exaggeration=ex, radius=a.radius,
                       max_shots=a.max_shots, quality=not a.no_quality, name=a.name)
        res = convert_gedi(gl, a.out_dir, a.drive_dir)
        for f in res.files:
            print(f"wrote {f}")
    elif a.cmd == "simulate":
        import json
        from .simulate import render_preview, PlanWindows
        with open(a.esp) as f:
            esp = json.load(f)
        render_preview(esp, PlanWindows(a.plan), a.out, a.width, a.height, a.fps, a.seconds, a.start)
        print(f"wrote {a.out}")
    elif a.cmd == "smoketest":
        plan = _build("- Huntsville, AL | 34.7304, -86.5861, 190 | orbit 45 + zoom 7km>3.5km @10s",
                      out=a.out, kml=False, plan_json=False, intro=False, outro=False, verbose=False,
                      title="CinematicEarth smoke test")
        print(f"wrote {a.out}: {plan.frames} frames, {len(plan.keyframes()[0])} keyframes")
    elif a.cmd == "moves":
        from . import model
        src = model.__file__
        with open(src) as f:
            txt = f.read()
        start = txt.index("# ---------------- move language")
        end = txt.index("_DUR =")
        print("\n".join(l[2:] if l.startswith("# ") else l.lstrip("#") for l in txt[start:end].splitlines()[1:]))
    elif a.cmd == "init":
        with open(a.path, "w") as f:
            f.write(EXAMPLE)
        print(f"wrote {a.path}")


if __name__ == "__main__":
    main()
