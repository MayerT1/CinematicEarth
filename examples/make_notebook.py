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
# CinematicEarth: 18-stop cinematic flyover for Google Earth Studio

1. Write a stop list (Markdown), optionally with camera moves per stop.
2. `cinematicearth` plans a slow, tilted 45° orbit at every city and paced hops between them, then writes **`flyover.esp`**.
3. Open it in **Earth Studio**, render, upload the render here, and get an annotated **`flyover_final.mp4`**.
""")

code("""
# 1 | install (set to the GitHub account that hosts the repo)
GITHUB_USER = "YOUR_GITHUB_USER"
!pip install -q "CinematicEarth[all] @ git+https://github.com/{GITHUB_USER}/CinematicEarth.git"
import cinematicearth as ce
print("cinematicearth", ce.__version__)
""")

md("""
## Stops + camera moves
One line per stop: `name | lat, lon, elevation_m | moves | key=value`.
Leave moves blank for the default: `orbit 45 + zoom 7km>3.5km` over `stop_duration`.

| move | effect |
|---|---|
| `orbit 45` / `pan 45` | circle the city (negative = other way) |
| `zoom 8km>3km` / `zoom in` | pull in / push out |
| `tilt 55>70` | tilt (0 = down, 90 = horizon) |
| `truck 3km` / `flyby 3km` | sideways parallax slide past the city |
| `rise 1km` | crane up/down |
| `hold` | pause |
| `slow 1.5` / `fast 2` | stretch / shrink this stop |

`+` = moves at the same time, `;` = one after another, `@5s` = segment duration.
""")

code("%%writefile stops.md\n" + stops_md)

code("""
# 2 | plan + write flyover.esp / flyover.kml / flyover.plan.json
plan = ce.build("stops.md", out="flyover.esp",
                 # override anything from the file here, e.g.:
                 # speed="medium", stop_duration=6, orbit=45, duration=300, cut_km=5000,
                 )
""")

code("""
# 3 | check the path: ground track, height, on-screen speed (red line = limit), pan/tilt
from cinematicearth.preview import plot_plan
plot_plan(plan);
""")

code("""
# 4 | (optional) wireframe motion check of the first ~45 s, decoded from the .esp itself
from cinematicearth.simulate import render_preview
from IPython.display import Video
render_preview(ce.build_esp(plan), plan, "wire.mp4", 640, 360, fps=15, max_seconds=45)
Video("wire.mp4", embed=True, width=640)
""")

code("""
# 5 | download the Earth Studio project (+ KML tour fallback)
from google.colab import files
files.download("flyover.esp"); files.download("flyover.kml"); files.download("flyover.plan.json")
""")

md("""
## In Earth Studio
1. Go to [earth.google.com/studio](https://earth.google.com/studio/) and choose **File → Import**, then pick `flyover.esp`.
2. Scrub the timeline. Each city should sit at the centre of the frame while the camera circles it.
3. Choose **Render → Advanced** for full-quality JPEG frames, which download as a `.zip`. Quick render gives an `.mp4` and works too.

If Earth Studio rejects the project:
1. In Earth Studio, export any small project as `template.esp`.
2. Run `ce.build("stops.md", out="flyover.esp", template="template.esp")`.
""")

code("""
# 6 | upload the render -> annotated MP4 (pin + card per city, Google Earth credit, dips at cuts)
from cinematicearth.overlay import annotate_video, OverlayStyle, preview_frame
import matplotlib.pyplot as plt
w = plan.stop_windows()[11]
plt.figure(figsize=(12, 3.5)); plt.imshow(preview_frame(plan, w["t_start"] + 3)[..., ::-1]); plt.axis("off"); plt.show()

up = files.upload()
render = next(iter(up))
style = OverlayStyle(accent="#FFB000", show_coords=True, show_counter=True, attribution="Google Earth")
annotate_video(render, "flyover.plan.json", "flyover_final.mp4", style)
files.download("flyover_final.mp4")
""")

md("""
## The same thing from the command line
```bash
cinematicearth build stops.md -o flyover.esp --speed slow --stop-duration 8
cinematicearth annotate render.zip flyover.plan.json -o flyover_final.mp4
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
