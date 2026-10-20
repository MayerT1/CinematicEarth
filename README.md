# CinematicEarth

[![PyPI](https://img.shields.io/pypi/v/CinematicEarth.svg)](https://pypi.org/project/CinematicEarth/) [![tests](https://github.com/MayerT1/CinematicEarth/actions/workflows/tests.yml/badge.svg)](https://github.com/MayerT1/CinematicEarth/actions/workflows/tests.yml) [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/MayerT1/CinematicEarth/blob/main/examples/CinematicEarth_colab.ipynb)

Cinematic multi-stop flyovers for **Google Earth Studio**. You give it a list of stops (and, if you want, camera moves per stop). It writes:

- **`.esp`**: an Earth Studio project. Open it, check it, render.
- **`.kml`**: the same camera path as a Google Earth Pro tour (fallback renderer).
- **`.plan.json`**: timing for each stop, used to burn animated **annotations** into the render.

What the camera does:

- **At each city:** a slow, tilted orbit (default **45°** over 8 s) that pulls in from 7 km to 3.5 km. Pan and tilt are computed per keyframe, so **the city is locked to screen centre** (< 1 px drift in tests).
- **Between nearby cities:** a low, forward-looking glide.
- **Between distant cities:** a smooth arc up toward space and a dive back into the tilted view.
- **Pacing:** every hop's duration comes from a cap on *perceived screen speed*, so nothing rockets across the map.

```text
stops.md ──► cinematicearth build ──► flyover.esp ──► Earth Studio render (.zip / .mp4)
                                  ├► flyover.kml                │
                                  └► flyover.plan.json ──► cinematicearth annotate ──► flyover_final.mp4
```

## Install

```bash
pip install "CinematicEarth[all]"        # everything: plots, YAML, annotated video (bundled ffmpeg)
pip install CinematicEarth               # core only (numpy): build .esp / .kml
pip install "git+https://github.com/MayerT1/CinematicEarth.git"   # latest from GitHub
# local dev:                   pip install -e ".[dev]"
```

The `annotate` and `simulate` commands use `ffmpeg` from your PATH, or the copy bundled with `imageio-ffmpeg`, which the `[video]`, `[all]` and `[dev]` extras install. That means it works on Windows without installing ffmpeg separately.

## Quick start

```bash
cinematicearth init stops.md                       # example file
cinematicearth build stops.md -o flyover.esp       # + flyover.kml, flyover.plan.json
cinematicearth build examples/stops_18.md --speed medium --stop-duration 6
cinematicearth build "Huntsville, AL; Santa Fe, NM; Kathmandu" --geocode --elevation
cinematicearth preview stops.md -o preview.png     # ground track / altitude / pacing plots
cinematicearth simulate flyover.esp flyover.plan.json -o wire.mp4   # wireframe motion check
cinematicearth annotate flyover.plan.json render.zip -o flyover_final.mp4
cinematicearth smoketest                         # tiny 10 s .esp to check Earth Studio import
cinematicearth moves                               # camera-move reference
```

```python
import cinematicearth as ce
plan = ce.build("examples/stops_18.md", out="flyover.esp", speed="slow", stop_duration=8)
print(plan.summary())

# or straight from Python
plan = ce.build([
    {"name": "Huntsville, AL", "lat": 34.7304, "lon": -86.5861, "elev": 190, "moves": "orbit 60 + zoom 8km>3km"},
    ("Santa Fe, NM", 35.6870, -105.9378, 2130),
], out="two.esp", duration=60)
```

## Stop files

Markdown with optional front matter for settings. Each stop is one list line, `name | lat, lon[, elev] | moves | key=value`:

```markdown
---
title: EarthRISE flyover
speed: slow          # glacial | slow | medium | fast | number
stop_duration: 8
orbit: 45
tilt: 60
# duration: 240      # force a total length; transits get re-paced to fit
---
- Huntsville, AL | 34.7304, -86.5861, 190 | orbit 60 + zoom 8km>3km; hold 1s | note=NASA EarthRISE / UAH
- Santa Fe, NM   | 35.6870, -105.9378, 2130
- Kathmandu, Nepal                       # no coords -> needs --geocode
```

Other accepted inputs:

- A Markdown pipe table (`| name | lat | lon | elev | duration | moves | transit | note |`)
- `.csv` with the same columns
- `.json` / `.yaml` (`{"settings": {...}, "stops": [...]}`)
- `.txt` with one stop per line
- An inline string `"A; B; C"`
- A Python list

Per-stop keys:

| key | meaning |
|---|---|
| `elev` | ground elevation (m) of the city. Keeps the camera height right in Santa Fe, Thimphu and other high places. Use `--elevation` to fetch it. |
| `duration` | seconds at this stop (overrides `stop_duration`) |
| `transit` | how to **arrive** here: `auto` / `glide` / `hop` / `cut` |
| `heading` | start pan direction (default: the direction of travel) |
| `label` | on-screen title |
| `note` | extra annotation line |

## Camera moves

Segments are separated by `;` and run one after another. Moves joined by `+` run at the same time. A segment can take a duration (`@6s`). Untimed segments share whatever is left of the stop's duration.

| move | effect |
|---|---|
| `orbit 45` (`pan`, `circle`, `spin`) | circle the city 45°. Negative = the other direction |
| `zoom 8km>3km`, `zoom 2.5km`, `zoom in/out` | change the LookAt range (pull in / push out) |
| `tilt 55>70` | change the tilt (0 = straight down, 90 = horizon) |
| `truck 2km` (`flyby`, `slide`) | slide the camera sideways past the city, keeping it centred (parallax flyby) |
| `rise 1km` (`crane`) | raise or lower the camera, keeping the city centred |
| `hold` | no motion |
| `slow 1.5` / `fast 2` | stretch or shrink this stop's time |

Example: `orbit 30 + zoom 9km>5km @5s; orbit 30 + tilt 60>72 + zoom 2.5km; hold 1s`

## Pacing (the "not too fast" part)

Each transit is reparameterised by perceived on-screen motion: sideways ground motion relative to range, zoom rate, pan rate and tilt rate. Its duration is then set so the **peak** never goes above `speed`.

| preset | 18-stop example |
|---|---|
| `glacial` | ~8.5 min |
| `slow` | ~6.5 min (default) |
| `medium` | ~5 min |
| `fast` | ~4.3 min |

If you set `duration`, all transits share the remaining time at the same speed, so no single hop is singled out to be rushed. You get a warning if that forces them past the preset.

For a short cut of many far-apart stops, use `cut_km: 5000`: long hops become hard cuts, and `annotate` adds a dip to black. The 18-stop example with `speed: medium`, `stop_duration: 6` and `cut_km: 5000` runs about 4 min.

## Earth Studio workflow

1. `cinematicearth build stops.md --split 90`. This writes `flyover_part01.esp`, `flyover_part02.esp` and so on, each about 90 s with about 130 keyframes.
2. Earth Studio: **File → Import** each part, scrub the timeline to check it, then **Render**. Advanced render gives JPEG frames as a `.zip`.
3. `cinematicearth annotate flyover.plan.json part01.zip part02.zip ...` joins the parts into one annotated MP4.

Parts are split at the end of a stop, where the camera is momentarily still, so they join seamlessly.

**Keep projects light.** A browser tab running Earth Studio can hang or crash on very large projects. Version 0.1.0 wrote about 2,400 keyframes per track over 6.5 min, and Chrome crashed on import.

The planner now samples the camera densely, then keeps only the keyframes Earth Studio needs for its own linear interpolation to reproduce the path:
- **At stops:** the city stays within 3 px of screen centre (`--keyframe-tol`).
- **In transit:** looser limits, since nothing is pinned to the centre there.

If an import still hangs, run `cinematicearth smoketest` and import `test_tiny.esp`. It's 10 s with 15 keyframes. If that works, use a smaller `--split`. If it doesn't, use the template route below.

You need to credit **Google Earth** on screen when you publish Earth Studio footage. `annotate` adds the credit by default. Turn it off with `--attribution ""`.

If Earth Studio ever refuses the generated project, use one it made itself:

1. Export any small project from your Earth Studio as `template.esp`.
2. Run `cinematicearth build stops.md --template template.esp`.

The camera tracks are written into your file's own structure, keeping everything else in it.

## How the .esp is written

Earth Studio's project format isn't documented. The encodings here match a real Earth Studio export (`modelVersion` 17) as reverse-engineered by [mkatzef/google-studio-utils](https://github.com/mkatzef/google-studio-utils):

- Keyframe time is a fraction of the project duration.
- Longitude and latitude are normalised from a `minValueRange`.
- Altitude is `m × 1.5357e-8`.
- `rotationX` (pan / compass heading) is normalised to `minValueRange`..`maxValueRange`.
- `rotationY` (tilt) is `deg / 180`.

Pan and tilt are written for every keyframe. Keyframes are error-bounded and reduced (see `cinematicearth/keyframes.py`). Pan is re-centred per project to stay within about ±200°, and orbit direction alternates between stops by default (`direction: alternate`). Camera Target is left off, so nothing depends on how target influence behaves.

## License

MIT
