"""CinematicEarth: cinematic multi-stop flyovers for Google Earth Studio.

    import cinematicearth as ce
    plan = ce.build("stops.md", out="flyover.esp")      # also writes .kml + .plan.json
    print(plan.summary())
"""
from __future__ import annotations

import os
from typing import Optional

from .model import Settings, Stop, parse_moves, SPEED_PRESETS
from .io import load, parse_markdown, parse_stop_line
from .planner import plan_flyover, Plan
from .esp import build_esp, write_esp, decode_tracks
from .kml import build_kml, write_kml

__version__ = "0.3.0"
__all__ = ["Settings", "Stop", "Plan", "load", "plan_flyover", "build", "write_esp", "write_kml",
           "build_esp", "decode_tracks", "parse_moves", "SPEED_PRESETS", "convert_layers", "__version__"]


def build(source, out: Optional[str] = "flyover.esp", kml: bool = True, plan_json: bool = True,
          template: Optional[str] = None, geocode: bool = False, elevation: bool = False,
          verbose: bool = True, **overrides) -> Plan:
    """Load stops (path / markdown text / list), plan the camera, write outputs.

    overrides: any Settings field, e.g. duration=150, speed="slow", stop_duration=10, orbit=45.
    """
    settings, stops = load(source, **overrides)
    results = convert_layers(settings, stops, verbose=verbose) if settings.layers else []
    if geocode or elevation:
        from .geocode import resolve
        resolve(stops, need_coords=geocode, need_elev=elevation, verbose=verbose)
    plan = plan_flyover(stops, settings)
    plan.layers = results
    plan.esp_files = []
    if out:
        plan.esp_files = write_esp(plan, out, template)
        base = os.path.splitext(out)[0]
        if kml:
            write_kml(plan, base + ".kml")
        if plan_json:
            plan.save_json(base + ".plan.json")
    if verbose:
        print(plan.summary())
        if results:
            linked = [f for r in results for f, d in zip(r.files, r.drive_ids) if d]
            unlinked = [f for r in results for f, d in zip(r.files, r.drive_ids) if not d]
            if linked:
                print("layers linked into the .esp (from your Google Drive): " + ", ".join(map(os.path.basename, linked)))
            if unlinked:
                print("add these in Earth Studio -> Overlays -> Import (once per project): "
                      + ", ".join(unlinked))
    return plan


def convert_layers(settings, stops, verbose=True):
    """Convert settings.layers (GeoTIFFs) to KMZ; place 'fly' stops on their products."""
    from .layers import convert_layer, fly_stop_for
    results = []
    for lay in settings.layers:
        res = convert_layer(lay, settings.layers_dir, settings.drive_dir, verbose)
        results.append(res)
        for k, s in enumerate(stops):
            if s.layer == lay.title and (s.lat is None or s.lon is None):
                fs = fly_stop_for(lay, res, settings)
                fs.layer = lay.title
                if s.duration is not None:
                    fs.duration = s.duration
                if s.elev is not None:
                    fs.elev = s.elev
                stops[k] = fs
    return results
