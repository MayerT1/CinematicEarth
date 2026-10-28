"""Generates examples/CinematicEarth_GEDI_colab.ipynb (run: python examples/make_gedi_notebook.py)."""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
cells = []
md = lambda s: cells.append({"cell_type": "markdown", "metadata": {}, "source": s.strip()})
code = lambda s: cells.append({"cell_type": "code", "metadata": {}, "execution_count": None,
                               "outputs": [], "source": s.strip()})

md("""
# CinematicEarth × GEDI: lidar forest structure over Sewanee, TN in a Google Earth Studio flyover

This notebook takes the stop list from the main CinematicEarth example and adds a stop over the **Sewanee Domain**, Tennessee. The camera orbits **GEDI spaceborne-lidar** observations, which are drawn as 3D KML layers:

| Data | Source | What you see |
|---|---|---|
| **L2A** canopy height + ground elevation | [SlideRule](https://slideruleearth.io) (no login) | 3D columns / gridded canopy height |
| **L4A** aboveground biomass (AGBD) | SlideRule (no login) | 3D columns coloured by biomass |
| **L2B foliage height diversity (FHD)**, cover, PAI, RH100 | NASA Harmony subset of GEDI02_B (free [Earthdata login](https://urs.earthdata.nasa.gov/)), the method from the [EarthRISE GEDI L2B tutorial](https://github.com/NASA-EarthRISE/training_Getting_started_with_GEDI_spaceborne_lidar/blob/main/tutorials/Exploring_forest_structure_with_GEDI_L2B.ipynb) | columns (height = RH100, colour = FHD) and canopy **curtains** along each track, **one layer per year** |

> SlideRule serves GEDI L1B / L2A / L4A but **not L2B**. FHD therefore comes from Harmony, or from GEDI02_B `.h5` / CSV files you already have (upload them or point to Drive).

**Time series:** with `by="year"` each year becomes its own KMZ. In Earth Studio, use each overlay's **Keyframe Opacity** to fade the years in one after another while the camera orbits.
""")

code("""
# 1 | install  (CinematicEarth[all] includes SlideRule, h5py, earthaccess, harmony-py, geopandas)
!pip install -q "CinematicEarth[all]"
import cinematicearth as ce
from cinematicearth import gedi as G
import matplotlib.pyplot as plt, pandas as pd, os
print("cinematicearth", ce.__version__)
""")

code("""
# 2 | the current stop list from the CinematicEarth repo (edit freely)
!wget -q -O stops.md https://raw.githubusercontent.com/MayerT1/CinematicEarth/main/examples/stops_18.md
print(open("stops.md").read())
""")

code("""
# 3 | area of interest: the Sewanee Domain (same GeoJSON as the EarthRISE GEDI tutorial)
AOI = "sewanee"                         # or a GeoJSON path / URL, or "west,south,east,north"
T0, T1 = "2019-04-18", "2024-12-31"     # GEDI mission period to use
aoi = G.load_aoi(AOI)
print(aoi.name, "bbox:", [round(v, 4) for v in aoi.bbox], "centre:", [round(v, 4) for v in aoi.center])
xs, ys = zip(*aoi.ring); plt.figure(figsize=(5, 5)); plt.plot(xs, ys); plt.title(aoi.name); plt.gca().set_aspect(1.2); plt.show()
""")

md("""
## A. SlideRule: GEDI L2A canopy height and L4A biomass (no login)
""")

code("""
# 4 | L2A: elevation of the lowest mode (ground) and highest return (canopy top) -> canopy height
l2a = G.sliderule_gedi(aoi, "l2a", t0=T0, t1=T1, quality=True)    # degraded + low-quality shots removed
print(len(l2a), "L2A shots;", l2a["year"].value_counts().sort_index().to_dict())
l2a.to_csv("gedi_l2a_sewanee.csv", index=False)

# 4b | (optional) L4A aboveground biomass density
l4a = G.sliderule_gedi(aoi, "l4a", t0=T0, t1=T1, quality=True)
print(len(l4a), "L4A shots")
l4a.to_csv("gedi_l4a_sewanee.csv", index=False)

fig, ax = plt.subplots(1, 2, figsize=(14, 5))
s = ax[0].scatter(l2a.lon, l2a.lat, c=l2a.canopy_height, s=2, cmap="YlGn", vmax=l2a.canopy_height.quantile(.98)); plt.colorbar(s, ax=ax[0], label="canopy height (m)")
s = ax[1].scatter(l4a.lon, l4a.lat, c=l4a.agbd, s=2, cmap="YlOrBr", vmax=l4a.agbd.quantile(.98)); plt.colorbar(s, ax=ax[1], label="AGBD (Mg/ha)")
for a_ in ax: a_.plot(*zip(*aoi.ring), "k-", lw=.8); a_.set_aspect(1.2)
plt.show()
""")

md("""
## B. GEDI L2B foliage height diversity (FHD)
Pick **one** option. Option 1 needs a free NASA Earthdata login, which is prompted once.
""")

code("""
# 5 | L2B source: "harmony" (download a Sewanee subset) | "upload" (.h5 or .csv) | "drive" (path in Drive) | None
L2B_SOURCE = "harmony"
DRIVE_L2B = "/content/drive/MyDrive/GEDI_L2b/Sewanee_Domain"     # folder of GEDI02_B .h5 files, or a .csv

l2b = None
if L2B_SOURCE == "harmony":
    files = G.harmony_l2b(aoi, T0, T1, out_dir="gedi_l2b_sewanee")         # Earthdata login prompt
    l2b = G.read_l2b_h5(files, aoi)
elif L2B_SOURCE == "upload":
    from google.colab import files as _f
    up = _f.upload()
    h5 = [k for k in up if k.endswith(".h5")]
    l2b = G.read_l2b_h5(h5, aoi) if h5 else G.read_table([k for k in up][0], aoi)
elif L2B_SOURCE == "drive":
    from google.colab import drive; drive.mount("/content/drive")
    l2b = G.read_l2b_h5(DRIVE_L2B, aoi) if os.path.isdir(DRIVE_L2B) else G.read_table(DRIVE_L2B, aoi)

if l2b is not None:
    print(len(l2b), "L2B shots before screening")
    l2b = G.filter_l2b(l2b, min_sensitivity=0.9)   # quality flag = 1, not degraded, sensitivity >= 0.9, valid FHD
    print(len(l2b), "after screening;", l2b["year"].value_counts().sort_index().to_dict())
    l2b.to_csv("gedi_l2b_sewanee.csv", index=False)
    fig, ax = plt.subplots(1, 2, figsize=(14, 5))
    s = ax[0].scatter(l2b.lon, l2b.lat, c=l2b.fhd_normal, s=3, cmap="viridis"); plt.colorbar(s, ax=ax[0], label="FHD")
    ax[1].scatter(l2b.rh100, l2b.fhd_normal, s=2, alpha=.3); ax[1].set_xlabel("RH100 (m)"); ax[1].set_ylabel("FHD")
    plt.show()
""")

md("""
## C. Turn the GEDI shots into flyover layers
Each `GediLayer` becomes one or more KMZ overlays:

| `viz` | Result |
|---|---|
| `columns` | one extruded column per shot (height = `height` × exaggeration, colour = `color`) |
| `curtains` | vertical walls along each ground track showing the canopy profile |
| `grid2d` / `grid3d` | shots averaged on a `cell`-metre grid, draped flat / extruded |

- `by="year"` gives one KMZ per year (the time series).
- `fly=True` adds a stop that orbits the AOI; `after="..."` places it after a named stop.
""")

code("""
# 6 | GEDI layers for the flyover (sources point at the CSVs saved above, so nothing is downloaded twice)
AFTER_STOP = None          # e.g. "Huntsville" to visit Sewanee right after that stop (default: at the end)

GEDI_LAYERS = []
if os.path.exists("gedi_l2b_sewanee.csv"):
    GEDI_LAYERS.append(G.GediLayer(aoi=AOI, source="table:gedi_l2b_sewanee.csv", product="l2b",
                                   name="Sewanee GEDI foliage height diversity",
                                   viz="columns,curtains", color="fhd_normal", height="rh100",
                                   by="year", fly=True, after=AFTER_STOP, duration=16,
                                   moves="orbit 90 + zoom 26km>12km + tilt 55>65"))
GEDI_LAYERS.append(G.GediLayer(aoi=AOI, source="table:gedi_l2a_sewanee.csv", product="l2a",
                               name="Sewanee GEDI canopy height", viz="grid2d", color="canopy_height",
                               cell=250, fly=not GEDI_LAYERS, after=AFTER_STOP))
GEDI_LAYERS.append(G.GediLayer(aoi=AOI, source="table:gedi_l4a_sewanee.csv", product="l4a",
                               name="Sewanee GEDI biomass", viz="columns", color="agbd",
                               height="agbd", radius=40))

# preview one layer on its own (writes KMZs to cinematicearth_layers/)
res = G.convert_gedi(GEDI_LAYERS[0], out_dir="cinematicearth_layers")
""")

code("""
# 7 | (optional) mount Drive so the KMZs can be linked into the .esp automatically
USE_DRIVE = True
DRIVE_OUT = "/content/drive/MyDrive/CinematicEarth"
if USE_DRIVE:
    from google.colab import drive; drive.mount("/content/drive")
""")

code("""
# 8 | plan the flyover: current stops + the Sewanee GEDI stop + all layers
plan = ce.build("stops.md", out="flyover.esp",
                layers=GEDI_LAYERS,
                drive_dir=DRIVE_OUT if USE_DRIVE else None,
                # speed="medium", stop_duration=6, ...
                )
""")

code("""
# 9 | check the path (green boxes = layers)
from cinematicearth.preview import plot_plan
plot_plan(plan);
""")

code("""
# 10 | download everything as one zip
import zipfile, shutil, datetime
from google.colab import files
ZIP = f"cinematicearth_gedi_{datetime.datetime.now():%Y%m%d_%H%M}.zip"
bundle = {f"esp/{os.path.basename(f)}": f for f in plan.esp_files}
bundle.update({f"layers/{os.path.basename(k)}": k for r in plan.layers for k in r.files})
bundle.update({f: f for f in ["flyover.kml", "flyover.plan.json", "stops.md",
                              "gedi_l2a_sewanee.csv", "gedi_l4a_sewanee.csv", "gedi_l2b_sewanee.csv"] if os.path.exists(f)})
with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED) as z:
    for arc, src in bundle.items():
        z.write(src, arc)
print(ZIP, f"{os.path.getsize(ZIP) / 1e6:.1f} MB,", len(bundle), "files")
if USE_DRIVE:
    shutil.copy2(ZIP, os.path.join(DRIVE_OUT, ZIP))
files.download(ZIP)
""")

md("""
## In Earth Studio
1. **File → Import** each `esp/flyover_partNN.esp`.
2. **Overlays → Import** the KMZs from `layers/`. If the build printed *"layers linked into the .esp"*, they're already listed.
   - **Time series:** for the per-year KMZs (`…_2019_columns.kmz`, `…_2020_…`), open each overlay's menu and choose **Keyframe Opacity**. Fade 2019 in, then 2020, and so on, across the Sewanee stop.
   - Hide `curtains` or `columns` with the checkboxes if both together are too busy.
3. Scrub to the Sewanee stop: the GEDI columns and curtains should rise from the Cumberland Plateau as the camera orbits.
4. **Render → Advanced**, then annotate below.

Tuning: `radius` (column width), `exaggeration` (number instead of `"auto"`), `max_shots`, `cmap`, `vmin`/`vmax`, and `moves` / `duration` on the GEDI layer that has `fly=True`.
""")

code("""
# 11 | upload the Earth Studio renders -> annotated MP4
from cinematicearth.overlay import annotate_video, OverlayStyle
up = files.upload()
annotate_video(sorted(up), "flyover.plan.json", "flyover_final.mp4", OverlayStyle(attribution="Google Earth | GEDI: NASA / UMD"))
files.download("flyover_final.mp4")
""")

md("""
### Same thing from the command line
```bash
cinematicearth gedi sewanee --source sliderule --product l2a --viz columns,curtains --by year
cinematicearth gedi sewanee --source h5:gedi_l2b_sewanee --product l2b --viz columns,curtains --height rh100 --by year
```
Or put it in `stops.md`:
```markdown
- gedi: sewanee | source=sliderule | l2a | columns curtains | by=year | fly
- gedi: sewanee | source=h5:/content/drive/MyDrive/GEDI_L2b | l2b | columns | height=rh100 | color=fhd_normal
```
""")

nb = {"cells": cells, "metadata": {"colab": {"provenance": []},
                                   "kernelspec": {"name": "python3", "display_name": "Python 3"}},
      "nbformat": 4, "nbformat_minor": 0}
for c in nb["cells"]:
    lines = c["source"].split("\n")
    c["source"] = [l + "\n" for l in lines[:-1]] + [lines[-1]]
with open(os.path.join(HERE, "CinematicEarth_GEDI_colab.ipynb"), "w") as f:
    json.dump(nb, f, indent=1)
print("wrote CinematicEarth_GEDI_colab.ipynb")
