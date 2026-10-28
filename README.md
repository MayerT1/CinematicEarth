# CinematicEarth

[![PyPI](https://img.shields.io/pypi/v/CinematicEarth.svg)](https://pypi.org/project/CinematicEarth/) [![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.23746921.svg)](https://doi.org/10.5281/zenodo.23746921)
[![Python](https://img.shields.io/pypi/pyversions/CinematicEarth.svg)](https://pypi.org/project/CinematicEarth/) [![tests](https://github.com/MayerT1/CinematicEarth/actions/workflows/tests.yml/badge.svg)](https://github.com/MayerT1/CinematicEarth/actions/workflows/tests.yml) [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/MayerT1/CinematicEarth/blob/main/examples/CinematicEarth_colab.ipynb)

**Turn a list of places, and your GeoTIFF products, into a cinematic Google Earth Studio flyover.**

Write your stops in a short text file and run one command. You get a Google Earth Studio project where the camera:

- slowly circles each place in a tilted 3D view, pulling in as it goes;
- glides low between nearby places;
- arcs up toward space between distant ones;
- shows your GeoTIFF products as flat colour overlays or as 3D extruded models, and can orbit them;
- pulls in **GEDI spaceborne lidar** (via [SlideRule](https://slideruleearth.io) or NASA Harmony) and draws canopy height, biomass and foliage height diversity as 3D columns, canopy curtains and yearly time-series layers.

Render the project in Earth Studio, then run one more command. You get an MP4 with an animated label for every place.

## Demo

[![CinematicEarth demo flyover (5x speed). Click for the full video](https://raw.githubusercontent.com/MayerT1/CinematicEarth/main/examples/demo.gif)](https://github.com/MayerT1/CinematicEarth/blob/main/examples/Demo_vid_small.mp4)

**▶ [Watch the full flyover at normal speed (MP4)](https://github.com/MayerT1/CinematicEarth/blob/main/examples/Demo_vid_small.mp4)**

*The whole flyover at 5× speed, rendered with CinematicEarth and Google Earth Studio. Each stop gets a slow, tilted 45° orbit that pulls in toward the place, and the flights between stops are paced so nothing rushes across the map.*

## How it fits together

```text
 stops.md ──► cinematicearth build ──► flyover_part01.esp … ──► Google Earth Studio ──► rendered frames
                                      └► flyover.plan.json ───────────────────────────┐        │
                                                                                      ▼        ▼
                                                                         cinematicearth annotate ──► flyover_final.mp4
```

---

## Contents

- [Demo](#demo)

1. [Install](#1-install)
2. [Your first flyover (5 minutes)](#2-your-first-flyover-5-minutes)
3. [Rendering in Google Earth Studio](#3-rendering-in-google-earth-studio)
4. [Adding the annotations](#4-adding-the-annotations)
5. [Writing a stop list](#5-writing-a-stop-list)
6. [Camera moves](#6-camera-moves)
7. [GeoTIFF products: 2D and 3D layers](#7-geotiff-products-2d-and-3d-layers)
8. [GEDI lidar layers (SlideRule, L2B FHD)](#8-gedi-lidar-layers-sliderule-l2b-fhd)
9. [Pacing and length](#9-pacing-and-length)
10. [All settings](#10-all-settings)
11. [Command reference](#11-command-reference)
12. [Python API](#12-python-api)
13. [Google Colab](#13-google-colab)
14. [Troubleshooting](#14-troubleshooting)
15. [How it works](#15-how-it-works)
16. [How to cite](#16-how-to-cite)

---

## 1. Install

```bash
pip install "CinematicEarth[all]"
```

| Install | What you get |
|---|---|
| `pip install CinematicEarth` | Core only (needs only numpy): build `.esp` / `.kml` projects |
| `pip install "CinematicEarth[all]"` | Everything: GeoTIFF layers, preview plots, YAML input, and annotated video (ffmpeg bundled) |
| `pip install "CinematicEarth[gedi]"` | Core plus GEDI lidar layers (sliderule, h5py, earthaccess, harmony-py, geopandas) |
| `pip install "CinematicEarth[layers]"` | Core plus GeoTIFF → 2D/3D KMZ (rasterio, matplotlib, pillow, gdown) |
| `pip install "git+https://github.com/MayerT1/CinematicEarth.git"` | Latest development version |

It needs Python 3.9 or newer and runs on Windows, macOS, Linux and Colab. Check the install with:

```bash
cinematicearth --version
```

You also need a Google account to use **[Google Earth Studio](https://earth.google.com/studio/)** in Chrome. It's free, but you have to sign up first.

---

## 2. Your first flyover (5 minutes)

**Step 1: write a stop list.** Save this as `stops.md`:

```markdown
---
title: My first flyover
speed: slow
stop_duration: 8
max_part_seconds: 90
---
- Huntsville, AL     | 34.7304, -86.5861, 190
- Santa Fe, NM       | 35.6870, -105.9378, 2130
- Fort Collins, CO   | 40.5853, -105.0844, 1525
```

Each line is `name | latitude, longitude, ground elevation in metres`. Or let the tool write an example for you with `cinematicearth init stops.md`.

**Step 2: build the project.**

```bash
cinematicearth build stops.md -o flyover.esp
```

It prints a table of each flight between stops and the total length. It writes:

| File | What it is |
|---|---|
| `flyover.esp`, or `flyover_part01.esp`, `flyover_part02.esp` … | Earth Studio project(s) |
| `flyover.kml` | The same flight as a Google Earth Pro tour (backup option) |
| `flyover.plan.json` | Timing of each stop, used later to add the annotations |

**Step 3: check the path (optional).**

```bash
cinematicearth preview stops.md -o preview.png
```

This draws the ground track, the camera height over time, and the on-screen speed.

**Step 4: render in Earth Studio** (next section), then **add annotations** (section 4).

---

## 3. Rendering in Google Earth Studio

1. Open **https://earth.google.com/studio/** in Chrome and sign in.
2. **File → Import** (or drag the file onto the page) and choose `flyover_part01.esp`.
3. Press play or scrub the timeline. Each place should stay in the middle of the frame while the camera circles it.
4. Click **Render** and choose:
   - **Advanced**: full-quality JPEG frames, downloaded as a `.zip`. Recommended.
   - **Quick**: an `.mp4` straight away, at lower quality.
5. Repeat for `flyover_part02.esp`, `part03` and so on. Name the downloads so they sort in order, for example `part01.zip`, `part02.zip`.

> **Why parts?** Earth Studio runs inside a browser tab, and very long or keyframe-heavy projects can freeze or crash Chrome. `max_part_seconds: 90` (or `--split 90`) cuts the flyover into projects of about 90 s. Each cut falls at the end of a stop, where the camera is momentarily still, so the parts join seamlessly in the final video.

---

## 4. Adding the annotations

```bash
cinematicearth annotate flyover.plan.json part01.zip part02.zip part03.zip -o flyover_final.mp4
```

The plan file comes first, then each render in order. A render can be a `.zip` of frames, a folder of frames, or an `.mp4`. The result is one joined video. While the camera circles each place, the video shows:

- a pulsing pin on the place, with a line to a label card;
- the stop number (`07 / 18`), place name, region, coordinates, and an optional note;
- the **Google Earth** credit in the corner.

Earth Studio's terms require that credit on anything you publish. You can turn it off with `--attribution ""`, but only if your render already has the credit burned in.

| Option | Effect |
|---|---|
| `--accent "#00C2FF"` | Colour of the pin, card bar and stop counter |
| `--no-coords` | Hide coordinates |
| `--no-counter` | Hide the `07 / 18` counter |
| `--attribution "Google Earth"` | Credit text in the corner |

---

### Sharing a demo (GitHub / PyPI)

A full-quality render is usually too big to share (GitHub's upload limit is 10 MB on free accounts). [`examples/make_demo_media.py`](https://github.com/MayerT1/CinematicEarth/blob/main/examples/make_demo_media.py) uses CinematicEarth's bundled ffmpeg, so there's nothing extra to install. It makes:

- `Demo_vid_small.mp4`: the whole video at 960 px, sized to about 9 MB;
- `demo.gif`: the whole flyover sped up (5× by default), which plays in READMEs and on PyPI.

```bash
python examples/make_demo_media.py --src flyover_final.mp4            # MP4 + GIF
python examples/make_demo_media.py --src flyover_final.mp4 --no-mp4 --speed 4 --gif-mb 15
```

---

## 5. Writing a stop list

### Markdown (recommended)

```markdown
---
title: Partner sites           # settings go here (see section 10)
speed: slow
stop_duration: 8
orbit: 45
max_part_seconds: 90
---

# Anything that isn't a list item is ignored, so notes and headings are fine.
# The last stop has no coordinates, so build this one with --geocode.

- Huntsville, AL   | 34.7304, -86.5861, 190  | orbit 60 + zoom 8km>3km; hold 1s | note=NASA EarthRISE
- Santa Fe, NM     | 35.6870, -105.9378, 2130 | duration=10
- Kathmandu, Nepal | 27.7172, 85.3240, 1400   | label=Kathmandu Valley
- Enschede, Netherlands
```

Each line has up to four parts, separated by ` | ` (a space on each side of the bar):

1. **Name** (required). It's also the on-screen title. Text after a comma becomes the region line on the card.
2. **`lat, lon[, elev]`**: decimal degrees, plus the ground elevation in metres.
3. **Camera moves** (optional, see section 6).
4. **`key=value` options**:

| Key | Meaning |
|---|---|
| `elev=` | Ground elevation in metres. Matters in high places (Santa Fe, Thimphu, Denver…) so the camera height is right. |
| `duration=` | Seconds at this stop (overrides `stop_duration`) |
| `transit=` | How to arrive here: `auto`, `glide`, `hop` or `cut` |
| `heading=` | Compass direction to start the orbit from (default: the direction of travel) |
| `label=` | Different on-screen title |
| `note=` | Extra highlighted line on the card |

**Missing coordinates or elevations?** Add `--geocode`, `--elevation` or both. Coordinates are looked up with OpenStreetMap Nominatim and elevations with Open-Meteo. Both need internet access, and the results are cached.

```bash
cinematicearth build "Huntsville, AL; Santa Fe, NM; Thimphu, Bhutan" --geocode --elevation -o trip.esp
```

### Other formats

| Format | Example |
|---|---|
| Markdown table | `\| name \| lat \| lon \| elev \| moves \| note \|` with one row per stop |
| CSV | columns `name,lat,lon,elev,duration,moves,transit,heading,label,note` |
| JSON / YAML | `{"settings": {...}, "stops": [{"name": ..., "lat": ..., "lon": ...}]}` |
| Plain text | one stop per line, same `name \| lat, lon` format |
| Inline | `cinematicearth build "Place A \| 10, 20; Place B \| 11, 21"` |

---

## 6. Camera moves

By default every stop gets `orbit 45 + zoom 7km>3.5km`: a 45° circle around the place that pulls in from 7 km to 3.5 km over `stop_duration` seconds. Orbit direction alternates between stops. To customise a stop, write a move script in its third field.

| Move | Also accepts | What it does |
|---|---|---|
| `orbit 45` | `pan`, `circle`, `spin` | Circle the place by 45°. A negative value circles the other way. |
| `zoom 8km>3km` | `range`, `dolly`, `push` | Change the distance to the place, from 8 km to 3 km. `zoom 3km` starts from the current distance. `zoom in` halves the distance and `zoom out` doubles it. |
| `tilt 55>70` | `pitch` | Change the camera tilt. 0 looks straight down; 90 looks at the horizon. |
| `truck 3km` | `flyby`, `slide` | Slide the camera sideways past the place while staying locked on it, for a parallax flyby. Negative slides left. |
| `rise 1km` | `crane`, `lift` | Raise the camera, or lower it with a negative value, while staying locked on the place. |
| `hold` | `pause`, `wait` | Stay still. |
| `slow 1.5` / `fast 2` | | Stretch or shrink this stop's time. |

**Combining moves:**

- `+` runs moves **together**: `orbit 60 + zoom 9km>3km`
- `;` runs them **one after another**: `orbit 30; hold 1s`
- `@5s` (or `5s`) sets a segment's duration. Segments without a time share what's left of the stop.

**Recipes:**

```text
orbit 45 + zoom 7km>3.5km                         # default slow pull-in orbit
orbit 90 + zoom 10km>4km @12s                     # long, wide reveal
orbit 30 + tilt 50>70 + zoom 8km>3km              # orbit while the horizon rises into view
truck 3km + zoom 6km>4km @5s; orbit 30            # side flyby, then settle into an orbit
tilt 20>65 + zoom 20km>5km @6s; orbit 45          # drop in from above, then circle
orbit 60 + zoom 8km>3km; hold 1.5s                # orbit, then pause for the title card
rise 2km + orbit -40                              # crane up while circling the other way
slow 2                                            # default move at half speed
```

To see this reference in the terminal, run `cinematicearth moves`.

---

## 7. GeoTIFF products: 2D and 3D layers

List GeoTIFF products in the same file as your stops. Each one is converted to a **KMZ** that Earth Studio renders in the flyover:

| `mode` | What you see |
|---|---|
| `2d` | The raster, colour-mapped, **draped flat on the terrain** (a KML GroundOverlay), plus an on-screen colour-bar legend |
| `3d` | The raster values **extruded into 3D shapes**: height = value × exaggeration, colour = value. Good for canopy height, elevation, biomass and similar. |
| `both` | Both of the above |

```markdown
---
title: Products flyover
max_part_seconds: 90
---
- Huntsville, AL | 34.7304, -86.5861, 190

- layer: Stage3_transformer_rh.tif | 3d fly | name=Canopy height (rh) | units=m | cmap=viridis | min_value=2
- layer: Stage3_transformer_rh.tif | 2d | name=Canopy height 2D | units=m | opacity=0.8

- Santa Fe, NM | 35.6870, -105.9378, 2130
```

A product line starts with `layer:`. A line whose first field is a `.tif` path or a Google Drive link counts too. **`fly`** adds a stop that frames the product and slowly orbits it, at that point in the flight. A ready-made example is in [`examples/stops_layers.md`](https://github.com/MayerT1/CinematicEarth/blob/main/examples/stops_layers.md).

**Where the TIFF can come from:**

- a local path: `Stage3_transformer_rh.tif`
- a mounted Google Drive path in Colab: `/content/drive/MyDrive/…/file.tif`
- a Drive share link: `https://drive.google.com/file/d/<id>/view` (downloaded with gdown; the file must be shared by link)
- `drive:<id>`, or any `https://` URL

Any projection works; it's reprojected to latitude/longitude automatically.

| Option | Default | Meaning |
|---|---|---|
| `name=` | file name | Title (legend, stop card) |
| `band=` | `1` | Band to use |
| `cmap=` | `viridis` | Any matplotlib colour map (`YlGn`, `magma`, `terrain`, …) |
| `vmin=` / `vmax=` | 2nd / 98th percentile | Colour (and height) range |
| `min_value=` | none | Values below this are transparent / not extruded (e.g. `2` for canopy) |
| `units=` | | Shown in the legend |
| `opacity=` | `0.85` | |
| `exaggeration=` | `auto` | 3D height multiplier. `auto` makes the tallest shape about 5% of the product's width. |
| `levels=` | `12` | Number of 3D colour/height steps |
| `style=` | `terraces` | `terraces` merges equal steps into stepped 3D shapes (light); `prisms` makes one column per cell (blockier, heavier) |
| `max_cells=` | `30000` | 3D detail budget: the raster is averaged down to about this many cells |
| `legend=` | `yes` | On-screen colour bar |
| `fly` / `after=` | off | Add an orbiting stop; `after=Huntsville` places it after that stop |
| `moves=` / `duration=` / `elev=` | auto | Camera moves, time and ground elevation for the fly stop |

**Getting the products into Earth Studio.** Earth Studio doesn't store KML inside the `.esp`; it references KML/KMZ files in your **Google Drive**. There are two ways in:

1. **Automatic (Colab):** set `drive_dir: /content/drive/MyDrive/CinematicEarth` (or `ce.build(..., drive_dir=...)`). The KMZs are copied to your Drive and linked into every `.esp` part by file ID. The build prints *"layers linked into the .esp"*.
2. **Manual (always works):** in Earth Studio, open **Overlays → Import** and pick the `.kmz` files (from `cinematicearth_layers/` or your Drive). Do this once in each project part. The build prints the files to import.

In the Overlays panel, you can **Keyframe Opacity** to fade a product in as the camera arrives.

Convert a single TIFF without a flyover:

```bash
cinematicearth layer Stage3_transformer_rh.tif --mode both --units m --min-value 2 --cmap viridis
```

---

## 8. GEDI lidar layers (SlideRule, L2B FHD)

[![Open the GEDI notebook in Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/MayerT1/CinematicEarth/blob/main/examples/CinematicEarth_GEDI_colab.ipynb)

CinematicEarth can fetch **GEDI** lidar footprints for an area and draw them as 3D KML layers in the flyover. The worked example is the **Sewanee Domain, Tennessee**. It uses the same AOI as the [EarthRISE GEDI L2B tutorial](https://github.com/NASA-EarthRISE/training_Getting_started_with_GEDI_spaceborne_lidar/blob/main/tutorials/Exploring_forest_structure_with_GEDI_L2B.ipynb), built in as `aoi=sewanee`.

| Product | Variables | Source | Login |
|---|---|---|---|
| **L2A** | ground elevation, canopy top → `canopy_height`, `elev_ground` | [SlideRule](https://slideruleearth.io) (`source=sliderule`) | none |
| **L4A** | aboveground biomass density `agbd` (Mg/ha) | SlideRule | none |
| **L2B** | **foliage height diversity `fhd_normal`**, `cover`, `pai`, `rh100` | NASA Harmony subset of GEDI02_B (`source=harmony`), or your own files (`source=h5:<dir>` / `table:<csv>`) | free [Earthdata](https://urs.earthdata.nasa.gov/) |

SlideRule serves GEDI L1B, L2A and L4A, but not L2B. Foliage height diversity therefore comes from GEDI02_B files, downloaded for just your area by Harmony or supplied by you. That's the same route as the EarthRISE tutorial.

**Visualisations** (`viz=`, combine with commas):

| `viz` | Result |
|---|---|
| `columns` | one extruded column per GEDI shot; height = `height` variable × exaggeration, colour = `color` variable |
| `curtains` | vertical walls along each ground track, tracing the canopy profile |
| `grid2d` / `grid3d` | shots averaged on a `cell`-metre grid, draped flat or extruded (via the GeoTIFF layer pipeline) |
| `by=year` | one KMZ per year. In Earth Studio, **Keyframe Opacity** each year in turn for a time series. |

**In `stops.md`:**

```markdown
- Huntsville, AL | 34.7304, -86.5861, 190
- gedi: sewanee | source=sliderule | l2a | columns curtains | by=year | fly
- gedi: sewanee | source=harmony | l2b | columns | color=fhd_normal | height=rh100 | by=year
- gedi: sewanee | source=sliderule | l4a | columns | color=agbd | height=agbd
```

`fly` adds a stop that frames the AOI and orbits it, placed at the ground elevation reported by GEDI.

**Command line:**

```bash
cinematicearth gedi sewanee --product l2a --viz columns,curtains --by year
cinematicearth gedi sewanee --source h5:gedi_l2b/ --product l2b --height rh100 --viz columns --by year
cinematicearth gedi --bbox=-85.99,35.13,-85.86,35.24 --product l4a --color agbd --height agbd
```

**Python:**

```python
from cinematicearth import gedi as G
l2a = G.sliderule_gedi("sewanee", "l2a", t0="2019-04-18")              # DataFrame of shots
l2b = G.filter_l2b(G.read_l2b_h5(G.harmony_l2b("sewanee", "2019-04-18", "2024-12-31"), "sewanee"))
layer = G.GediLayer(aoi="sewanee", source="harmony", product="l2b", viz="columns,curtains",
                    color="fhd_normal", height="rh100", by="year", fly=True, after="Huntsville")
plan = ce.build("stops.md", out="flyover.esp", layers=[layer])
```

| Option | Default | Meaning |
|---|---|---|
| `aoi` | `sewanee` | Preset, GeoJSON path/URL, or `w,s,e,n` |
| `source` | `sliderule` | `sliderule`, `harmony`, `h5:<file or dir>`, `table:<csv/parquet/geojson>` |
| `product` | `l2a` | `l2a`, `l4a` (SlideRule) or `l2b` |
| `color` / `height` | by product / `canopy_height` | Any column, e.g. `fhd_normal`, `rh100`, `cover`, `pai`, `agbd`, `elev_ground` |
| `t0` / `t1` | all | Date range `YYYY-MM-DD` |
| `quality` | `yes` | Drop degraded and low-quality shots (L2B: quality flag 1, sensitivity ≥ `min_sensitivity` 0.9) |
| `radius` | `35` | Column radius (m). The real GEDI footprint is about 12.5 m, so columns are drawn wider to read on screen. |
| `exaggeration` | `auto` | Height multiplier |
| `max_shots` | `20000` | Random thinning above this |
| `cell` | `250` | Grid cell for `grid2d` / `grid3d` (m) |
| `cmap`, `vmin`, `vmax`, `opacity`, `legend` | | Styling |
| `fly`, `after`, `moves`, `duration`, `elev` | | The orbiting stop |

Data credit: GEDI data are from NASA / University of Maryland (LP DAAC, ORNL DAAC). SlideRule is developed by the University of Washington and NASA.

---

## 9. Pacing and length

Between stops, the time each flight takes is calculated, not fixed. It's set from a cap on **perceived on-screen speed**, which combines:

- how fast the ground slides across the frame;
- how fast the view zooms;
- how fast it pans and tilts.

No flight can whip across the map, however far apart the places are.

| `speed` | Feel | 18-stop example |
|---|---|---|
| `glacial` | very slow, documentary | ~8.5 min |
| `slow` (default) | relaxed and cinematic | ~6.5 min |
| `medium` | brisk | ~5 min |
| `fast` | quick, still smooth | ~4.3 min |

Other controls:

- **`duration: 180`**: forces a total length. All flights share the remaining time evenly, and you get a warning if that makes them faster than your `speed` preset.
- **`stop_duration`** or per-stop `duration=`: time spent circling each place.
- **`cut_km: 5000`**: flights longer than this become **hard cuts** instead of flying across an ocean. `annotate` adds a short dip to black. The 18-stop example with `speed: medium`, `stop_duration: 6` and `cut_km: 5000` runs about 4 min.
- **`glide_km: 150`**: flights shorter than this stay low ("glide"); longer ones arc up ("hop").

---

## 10. All settings

Put settings in the stop file's front matter, pass them as command-line flags, or pass them as Python keyword arguments.

| Setting | Default | CLI flag | Meaning |
|---|---|---|---|
| `title` | `CinematicEarth flyover` | `--title` | Project name |
| `fps` | `30` | `--fps` | Frames per second |
| `width` / `height` | `1920` / `1080` | `--width` / `--height` | Render size |
| `duration` | auto | `--duration` | Force total seconds |
| `speed` | `slow` | `--speed` | `glacial` / `slow` / `medium` / `fast` / a number |
| `stop_duration` | `8` | `--stop-duration` | Seconds at each place |
| `orbit` | `45` | `--orbit` | Default orbit, in degrees |
| `tilt` | `60` | `--tilt` | Default tilt at places (0 = down, 90 = horizon) |
| `range_start` / `range_end` | `7000` / `3500` | `--range-start` / `--range-end` | Default pull-in distance, in metres |
| `direction` | `alternate` | `--direction` | Orbit direction: `alternate`, `1` (clockwise) or `-1` |
| `ease` | `smooth` | `--ease` | Acceleration curve: `smooth`, `sine` or `linear` |
| `intro` / `outro` | `true` | `--no-intro` / `--no-outro` | Descend from space at the start / pull back out at the end |
| `glide_km` | `150` | | Below this distance, fly low |
| `cut_km` | off | `--cut-km` | Above this distance, hard cut |
| `max_part_seconds` | off | `--split` | Split into Earth Studio projects of at most this length (90 recommended) |
| `keyframe_tol_px` | `3` | `--keyframe-tol` | How far (px) a place may drift from centre between keyframes |
| `layers_dir` | `cinematicearth_layers` | `--layers-dir` | Where product KMZs are written |
| `drive_dir` | off | `--drive-dir` | Colab: copy KMZs to this Drive folder and link them into the `.esp` |
| `layers` | none | | Product list: GeoTIFF and `gedi:` lines, front matter, or `ce.build(..., layers=[...])` |
| `glide_tilt`, `hop_tilt`, `hop_apex`, `glide_apex`, `space_range`, `min_leg`, `max_key_gap`, `sample_rate` | | | Advanced flight shape and keyframe settings |

---

## 11. Command reference

```bash
cinematicearth init stops.md                         # write an example stop list
cinematicearth build stops.md -o flyover.esp         # make the Earth Studio project(s) + .kml + .plan.json
cinematicearth build stops.md --split 90 --speed medium --stop-duration 6
cinematicearth build stops.md --template my_export.esp   # write into a project Earth Studio exported
cinematicearth preview stops.md -o preview.png       # path / height / speed plots
cinematicearth simulate flyover_part01.esp flyover.plan.json -o wire.mp4   # wireframe motion preview
cinematicearth annotate flyover.plan.json part01.zip part02.zip -o final.mp4
cinematicearth layer product.tif --mode 3d --units m # GeoTIFF -> 2D / 3D .kmz
cinematicearth build examples/stops_layers.md -o flyover.esp   # stops + GeoTIFF products
cinematicearth gedi sewanee --product l2a --viz columns,curtains --by year   # GEDI lidar -> 3D KMZ
cinematicearth smoketest                             # tiny 10 s test project for Earth Studio
cinematicearth moves                                 # camera-move reference
cinematicearth <command> --help                      # all options
```

---

## 12. Python API

```python
import cinematicearth as ce

# from a file (any format); keyword arguments override the file's settings
plan = ce.build("stops.md", out="flyover.esp", speed="slow", max_part_seconds=90)
print(plan.summary())        # flight table + total length
print(plan.esp_files)        # ['flyover_part01.esp', ...]

# straight from Python
plan = ce.build([
    {"name": "Huntsville, AL", "lat": 34.7304, "lon": -86.5861, "elev": 190,
     "moves": "orbit 60 + zoom 8km>3km", "note": "NASA EarthRISE"},
    ("Santa Fe, NM", 35.6870, -105.9378, 2130),
], out="two.esp", duration=60)

# plan without writing files
settings, stops = ce.load("stops.md", speed="medium")
plan = ce.plan_flyover(stops, settings)
plan.stop_windows()          # when each stop starts and ends (seconds)

# GeoTIFF products, passed in code (same options as the markdown lines)
plan = ce.build("stops.md", out="flyover.esp", layers=[
    dict(source="Stage3_transformer_rh.tif", name="Canopy height", mode="3d", units="m",
         min_value=2, fly=True, after="Huntsville"),
])
plan.layers                  # converted products: files, bounds, colour range, exaggeration

from cinematicearth.layers import Layer, convert_layer       # one product on its own
convert_layer(Layer("Stage3_transformer_rh.tif", mode="both", units="m"), out_dir="kmz")

# preview and annotate
from cinematicearth.preview import plot_plan
plot_plan(plan)

from cinematicearth.overlay import annotate_video, OverlayStyle
annotate_video(["part01.zip", "part02.zip"], "flyover.plan.json", "final.mp4",
               OverlayStyle(accent="#00C2FF", notes={"Santa Fe, NM": "Field campaign 2026"}))
```

---

## 13. Google Colab

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/MayerT1/CinematicEarth/blob/main/examples/CinematicEarth_colab.ipynb)

The notebook walks through the full 18-stop example:

1. Install.
2. Edit the stop list.
3. Add GeoTIFF products from your **Drive**, a **Drive link**, or an **upload**, and preview them.
4. Build and preview the path.
5. Watch a wireframe preview of the motion.
6. Download the projects and KMZs.
7. Upload your Earth Studio renders.
8. Download the annotated MP4.

Second notebook, **GEDI lidar over Sewanee, TN:**

[![Open the GEDI notebook in Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/MayerT1/CinematicEarth/blob/main/examples/CinematicEarth_GEDI_colab.ipynb)

It takes the same stop list and adds a Sewanee stop. It fetches GEDI L2A and L4A from SlideRule and L2B foliage height diversity through Harmony, or from your uploads or Drive. It then builds columns, curtains, grids and yearly time-series layers, and downloads everything as one zip.

---

## 14. Troubleshooting

| Problem | Fix |
|---|---|
| **Chrome goes black or freezes after importing** | The project is too heavy. Use `--split 90`, or go smaller with `--split 45`. Run `cinematicearth smoketest` and import `test_tiny.esp` (10 s): if even that fails, use the template route in the next row. |
| **Earth Studio won't open the file** | In Earth Studio, make any small project and export it (**File → Export**) as `my_export.esp`. Then run `cinematicearth build stops.md --template my_export.esp`. The camera path is written into Earth Studio's own file. |
| **The place drifts off centre, or the camera dips into terrain** | Give the stop its ground elevation (`elev=` or `--elevation`). |
| **Too fast / too slow** | Change `speed`, `stop_duration` and `orbit`, or use `cut_km` for very long flights. Check with `cinematicearth preview`. |
| **Labels appear at the wrong time** | Pass the renders to `annotate` in the right order, one per part, together with the `.plan.json` from the same build. |
| **`ffmpeg not found`** | `pip install "CinematicEarth[video]"` (it includes a bundled ffmpeg). |
| **A product doesn't show in Earth Studio** | Import its `.kmz` with **Overlays → Import**. If it was linked automatically but shows as missing, Earth Studio can't read that Drive file, so import it by hand. |
| **3D product is slow or too heavy** | Lower `max_cells` (e.g. `10000`) or `levels`, or use `style=terraces` |
| **3D shapes too flat or too tall** | Set `exaggeration=` (e.g. `20`) instead of `auto` |
| **Drive link won't download** | Share the file as "Anyone with the link", or mount Drive in Colab and use the `/content/drive/...` path |
| **Want Google Earth Pro instead** | Open `flyover.kml`, double-click the tour, and record it with **Tools → Movie Maker**. |

---

## 15. How it works

- **Locked-on camera.** Every moment is planned as "look at this point from this distance, tilt and direction". Each keyframe's camera position, pan and tilt are computed so the camera points exactly at the place. In tests, the place stays within 3 px of centre at every frame (`keyframe_tol_px`), even with Earth Studio interpolating between keyframes.
- **Paced flights.** Flights are reshaped so on-screen speed rises and falls smoothly and never passes the `speed` cap.
- **Light projects.** The path is sampled densely, then reduced to the fewest keyframes that keep the error within tolerance: tight at stops, looser in flight. The 18-stop example uses about 660 keyframes in total, or about 130 per 90 s part.
- **Products.** GeoTIFFs are reprojected to latitude/longitude with rasterio. 2D layers become a colour-mapped PNG in a KML GroundOverlay. 3D layers are averaged to the cell budget, binned into `levels` classes, turned into polygons per class, and written as extruded KML polygons (`relativeToGround`). Earth Studio renders KML Polygons, GroundOverlays and ScreenOverlays.
- **The `.esp` format.** Earth Studio's project format isn't documented. CinematicEarth follows the structure of a real Earth Studio export, as worked out by [mkatzef/google-studio-utils](https://github.com/mkatzef/google-studio-utils).

---

## 16. How to cite

If you use CinematicEarth in a publication, presentation or product video, please cite it:

> Mayer, T. (2026). *CinematicEarth: cinematic Google Earth Studio flyovers with GeoTIFF products* (Version 0.3.1) [Computer software]. Zenodo. https://doi.org/10.5281/zenodo.23746921

```bibtex
@software{mayer_cinematicearth_2026,
  author    = {Mayer, Timothy},
  title     = {{CinematicEarth: cinematic Google Earth Studio flyovers with GeoTIFF products}},
  year      = {2026},
  version   = {0.3.1},
  publisher = {Zenodo},
  doi       = {10.5281/zenodo.23746921},
  url       = {https://doi.org/10.5281/zenodo.23746921}
}
```

GitHub's **"Cite this repository"** button (in the repo sidebar) gives the same reference in APA and BibTeX, from [`CITATION.cff`](https://github.com/MayerT1/CinematicEarth/blob/main/CITATION.cff).

---

## Credits and license

Built by Tim Mayer (NASA EarthRISE, University of Alabama in Huntsville). MIT License.

Google Earth Studio imagery is © Google and its data providers. Credit **Google Earth** on screen when you publish footage; see the [Earth Studio terms](https://earth.google.com/studio/docs/) for details.
