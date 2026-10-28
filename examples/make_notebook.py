"""Generates examples/CinematicEarth_colab.ipynb (run: python examples/make_notebook.py)."""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
stops_md = open(os.path.join(HERE, "stops_18.md")).read()

cells = []
md = lambda s: cells.append({"cell_type": "markdown", "metadata": {}, "source": s.strip()})
code = lambda s: cells.append({"cell_type": "code", "metadata": {}, "execution_count": None,
                               "outputs": [], "source": s.strip()})

md("""
# CinematicEarth: cinematic Google Earth Studio flyovers, with GeoTIFF products

1. Write a stop list (Markdown), optionally with camera moves per stop.
2. *(new in 0.3)* Add **GeoTIFF products** from Google Drive, a Drive link, or an upload. Each becomes a **2D draped overlay** or a **3D extruded model** (KMZ), and can get its own orbiting stop.
3. `cinematicearth` plans a slow, tilted 45° orbit at every stop and paced hops between them, then writes the Earth Studio project (**`.esp`**).
4. Open it in **Earth Studio**, render, upload the render here, and get an annotated **`flyover_final.mp4`**.
""")

code("""
# 1 | install from PyPI  (latest dev: !pip install -q "CinematicEarth[all] @ git+https://github.com/MayerT1/CinematicEarth.git")
!pip install -q "CinematicEarth[all]"
import cinematicearth as ce
print("cinematicearth", ce.__version__)
""")

md("""
## Stops + camera moves
One line per stop: `name | lat, lon, elevation_m | moves | key=value`.
Leave moves blank for the default: `orbit 45 + zoom 7km>3.5km` over `stop_duration`.

| move | effect |
|---|---|
| `orbit 45` / `pan 45` | circle the place (negative = other way) |
| `zoom 8km>3km` / `zoom in` | pull in / push out |
| `tilt 55>70` | tilt (0 = down, 90 = horizon) |
| `truck 3km` / `flyby 3km` | sideways parallax slide past the place |
| `rise 1km` | crane up/down |
| `hold` | pause |
| `slow 1.5` / `fast 2` | stretch / shrink this stop |

`+` = moves at the same time, `;` = one after another, `@5s` = segment duration.
""")

code("%%writefile stops.md\n" + stops_md)

md("""
## GeoTIFF products (optional)
Earth Studio draws KML **GroundOverlays** (flat images) and **Polygons**, so each GeoTIFF becomes:

| mode | result in the flyover |
|---|---|
| `2d` | colour-mapped image draped on the terrain, with a legend |
| `3d` | values extruded into 3D shapes (height = value × exaggeration), colour-mapped |
| `both` | both of the above |

Products can come from **your Google Drive** (mounted), a **Drive share link**, or an **upload**. Mix them freely in `PRODUCTS`.
`fly=True` adds a stop that frames and orbits the product. `after="Huntsville"` places that stop after a named stop (default: the end).

Other options: `cmap`, `vmin`/`vmax`, `min_value` (lower values are transparent), `units`, `opacity`, `exaggeration` (number or `"auto"`), `levels`, `style` (`terraces` or `prisms`), `band`, `legend`.
""")

code("""
# 2a | (optional) mount Google Drive: read TIFFs from it, and save the KMZs there so they can be linked into the .esp
USE_DRIVE = True
DRIVE_OUT = "/content/drive/MyDrive/CinematicEarth"        # converted .kmz files go here
if USE_DRIVE:
    from google.colab import drive
    drive.mount("/content/drive")
""")

code("""
# 2b | (optional) upload GeoTIFFs from your computer -> /content/tifs   (set UPLOAD = True)
import os
from google.colab import files
UPLOAD = False
UPLOADED = []
if UPLOAD:
    os.makedirs("/content/tifs", exist_ok=True)
    for name, data in files.upload().items():
        p = os.path.join("/content/tifs", name)
        with open(p, "wb") as f:
            f.write(data)
        UPLOADED.append(p)
print(UPLOADED)
""")

code("""
# 2c | list the products: "source" = Drive path, uploaded file, Drive share link, or drive:<file id>
PRODUCTS = [
    dict(source="/content/drive/MyDrive/Stage3_transformer_rh.tif",     # <- your file in Drive
         name="Canopy height (rh)", mode="3d", units="m", cmap="viridis", min_value=2,
         fly=True, after="Huntsville"),
    # dict(source="https://drive.google.com/file/d/<FILE_ID>/view", name="Product B", mode="2d", units="m"),
    # dict(source="drive:<FILE_ID>", name="Product C", mode="both"),
]
PRODUCTS += [dict(source=p, mode="both", fly=True) for p in UPLOADED]   # uploads: 2D + 3D, orbited at the end
missing = [p["source"] for p in PRODUCTS if p["source"].startswith("/content/") and not os.path.exists(p["source"])]
PRODUCTS = [p for p in PRODUCTS if p["source"] not in missing]
print(len(PRODUCTS), "product(s)", "| not found (skipped):" if missing else "", *missing)
""")

code("""
# 2d | (optional) preview the first product: draped 2D image + legend + 3D stats
from cinematicearth.layers import Layer, convert_layer
import zipfile, io
from PIL import Image
import matplotlib.pyplot as plt
if PRODUCTS:
    res = convert_layer(Layer(**{**PRODUCTS[0], "mode": "both", "fly": False}), out_dir="layer_preview")
    z = zipfile.ZipFile(res.files[0])
    fig, ax = plt.subplots(1, 2, figsize=(14, 5), gridspec_kw={"width_ratios": [3, 2]})
    ax[0].imshow(Image.open(io.BytesIO(z.read("overlay.png")))); ax[0].set_title(res.name); ax[0].axis("off")
    ax[1].imshow(Image.open(io.BytesIO(z.read("legend.png")))); ax[1].axis("off")
    plt.show()
    print(f"3D: heights x{res.exaggeration:.3g}, {res.n_polygons} polygons, "
          f"{res.extent_m[0] / 1000:.1f} x {res.extent_m[1] / 1000:.1f} km")
""")

code("""
# 3 | plan + convert products + write flyover_partNN.esp / flyover.kml / flyover.plan.json
plan = ce.build("stops.md", out="flyover.esp",
                layers=PRODUCTS,                                  # GeoTIFF products ([] for none)
                drive_dir=DRIVE_OUT if USE_DRIVE else None,       # save KMZ to Drive + link into the .esp
                # override anything from the file here, e.g.:
                # speed="medium", stop_duration=6, orbit=45, duration=300, cut_km=5000,
                )
""")

code("""
# 4 | check the path: ground track (green boxes = products), height, on-screen speed (red = limit), pan/tilt
from cinematicearth.preview import plot_plan
plot_plan(plan);
""")

code("""
# 5 | (optional) wireframe motion check of the first ~45 s, decoded from the .esp itself
from cinematicearth.simulate import render_preview
from IPython.display import Video
render_preview(ce.build_esp(plan), plan, "wire.mp4", 640, 360, fps=15, max_seconds=45)
Video("wire.mp4", embed=True, width=640)
""")

code("""
# 6 | download the Earth Studio project(s), product KMZs, KML tour and plan
from google.colab import files
for f in plan.esp_files + ["flyover.kml", "flyover.plan.json"] + [k for r in plan.layers for k in r.files]:
    files.download(f)
""")

md("""
## In Earth Studio
1. Go to [earth.google.com/studio](https://earth.google.com/studio/), choose **File → Import**, and pick `flyover_part01.esp`. Do the same for each part (`max_part_seconds: 90` keeps every project light enough for the browser).
2. **Products.** If the build printed *"layers linked into the .esp"*, the KMZs from your Drive are already listed in the project's **Overlays** panel. Otherwise, or if one shows as missing, open **Overlays → Import** in each project and pick the `.kmz` files from your computer or from Drive (`DRIVE_OUT`).
   - 3D products are extruded polygons, so they render as solid shapes as the camera orbits.
   - Use the overlay's **Keyframe Opacity** to fade a product in or out.
3. Scrub the timeline. Each stop should sit at the centre of the frame while the camera circles it.
4. Choose **Render → Advanced** for full-quality JPEG frames, which download as a `.zip`. Quick render gives an `.mp4` and works too. Render every part.

If an import hangs, run `!cinematicearth smoketest` and try `test_tiny.esp` (10 s) first.

If Earth Studio rejects the project:
1. In Earth Studio, export any small project as `template.esp`.
2. Run `ce.build("stops.md", out="flyover.esp", template="template.esp", layers=PRODUCTS)`.
""")

code("""
# 7 | upload the renders -> annotated MP4 (pin + card per stop, Google Earth credit, dips at cuts)
from cinematicearth.overlay import annotate_video, OverlayStyle, preview_frame
import matplotlib.pyplot as plt
w = plan.stop_windows()[0]
plt.figure(figsize=(12, 3.5)); plt.imshow(preview_frame(plan, w["t_start"] + 3)[..., ::-1]); plt.axis("off"); plt.show()

up = files.upload()                      # select ALL part renders at once
renders = sorted(up)                     # part01, part02, ... (name them so they sort in order)
style = OverlayStyle(accent="#FFB000", show_coords=True, show_counter=True, attribution="Google Earth")
annotate_video(renders, "flyover.plan.json", "flyover_final.mp4", style)
files.download("flyover_final.mp4")
""")

md("""
## The same thing from the command line
```bash
cinematicearth layer Stage3_transformer_rh.tif --mode 3d --units m --min-value 2   # one product -> .kmz
cinematicearth build examples/stops_layers.md -o flyover.esp                        # stops + products
cinematicearth annotate flyover.plan.json part01.zip part02.zip -o flyover_final.mp4
```
""")

nb = {"cells": cells, "metadata": {"colab": {"provenance": []},
                                   "kernelspec": {"name": "python3", "display_name": "Python 3"}},
      "nbformat": 4, "nbformat_minor": 0}
for c in nb["cells"]:
    lines = c["source"].split("\n")
    c["source"] = [l + "\n" for l in lines[:-1]] + [lines[-1]]
with open(os.path.join(HERE, "CinematicEarth_colab.ipynb"), "w") as f:
    json.dump(nb, f, indent=1)
print("wrote CinematicEarth_colab.ipynb")
