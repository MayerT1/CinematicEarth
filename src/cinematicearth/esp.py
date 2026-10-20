"""Write Google Earth Studio project files (.esp).

The layout and value encodings follow a real Earth Studio export
(modelVersion 17) as documented by mkatzef/google-studio-utils:

* keyframe ``time`` is a fraction 0..1 of the project duration
* longitude: value = (lon - min) / (180 - min), ``minValueRange`` = min
* latitude:  value = (lat - min) / (90 - min),  ``minValueRange`` = min
* altitude:  value = alt_m * 1.5356706349899208e-08 (linear, not logarithmic)
* rotationX (pan / heading, compass deg): value = (pan - min) / (max - min), with
  ``minValueRange`` / ``maxValueRange``; pans may be unwrapped beyond 0..360
* rotationY (tilt, 0 = down, 90 = horizon): value = tilt / 180

Camera Target is written disabled: pan/tilt are computed exactly per keyframe,
so the camera always aims at the city without relying on target influence.
"""
from __future__ import annotations

import copy
import json
from typing import Optional

import numpy as np

ALT_SCALE = 1.5356706349899208e-08


def _block(label, vals, times, min_val=None, max_val=None):
    blk = {
        "type": label,
        "value": {"relative": 0},
        "keyframes": [{"time": float(t), "value": float(v)} for t, v in zip(times, vals)],
        "intimeline": True,
    }
    if min_val is not None:
        blk["value"]["minValueRange"] = float(min_val)
    if max_val is not None:
        blk["value"]["maxValueRange"] = float(max_val)
    if label == "altitude":
        blk["value"]["logarithmic"] = False
    return blk


def encode_tracks(times, cam, rot, duration):
    """Return (position_blocks, rotation_blocks) in Earth Studio encoding."""
    tn = np.clip(np.asarray(times) / duration, 0.0, 1.0)
    lat, lon, alt = cam[:, 0], cam[:, 1], cam[:, 2]
    pan, tilt = rot[:, 0], rot[:, 1]
    lon_min = float(lon.min()) - 1e-6
    lat_min = float(lat.min()) - 1e-6
    pmin, pmax = float(pan.min()), float(pan.max())
    if pmax - pmin < 1e-3:
        pmin, pmax = pmin - 1.0, pmax + 1.0
    pos = [
        _block("longitude", (lon - lon_min) / (180.0 - lon_min), tn, lon_min),
        _block("latitude", (lat - lat_min) / (90.0 - lat_min), tn, lat_min),
        _block("altitude", alt * ALT_SCALE, tn),
    ]
    rotb = [
        _block("rotationX", (pan - pmin) / (pmax - pmin), tn, pmin, pmax),
        _block("rotationY", tilt / 180.0, tn),
        {"type": "rotationZ", "value": {}},
    ]
    return pos, rotb


def decode_tracks(esp: dict):
    """Inverse of encode_tracks (for verification / round-trip tests)."""
    found = {}

    def walk(o):
        if isinstance(o, dict):
            if o.get("type") in ("longitude", "latitude", "altitude", "rotationX", "rotationY") and "keyframes" in o:
                found[o["type"]] = o
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(esp)
    dur = esp["settings"]["duration"] / esp["settings"]["frameRate"]
    t = np.array([k["time"] for k in found["longitude"]["keyframes"]]) * dur
    g = lambda k: np.array([x["value"] for x in found[k]["keyframes"]])
    lon_min = found["longitude"]["value"]["minValueRange"]
    lat_min = found["latitude"]["value"]["minValueRange"]
    lon = lon_min + g("longitude") * (180 - lon_min)
    lat = lat_min + g("latitude") * (90 - lat_min)
    alt = g("altitude") / ALT_SCALE
    rx = found["rotationX"]["value"]
    pan = rx["minValueRange"] + g("rotationX") * (rx["maxValueRange"] - rx["minValueRange"])
    tilt = g("rotationY") * 180
    return t, np.c_[lat, lon, alt], np.c_[pan, tilt]


def _template(name, fps, width, height, frames, pos, rotb):
    return {
        "modelVersion": 17,
        "settings": {"name": name, "frameRate": fps,
                     "dimensions": {"width": width, "height": height},
                     "duration": frames, "timeFormat": "frames"},
        "scenes": [{
            "animationModel": {"roving": False, "logarithmic": False, "groupedPosition": True},
            "duration": frames,
            "attributes": [
                {"type": "cameraGroup", "inTimeline": True, "attributes": [
                    {"type": "cameraPositionGroup", "inTimeline": True, "attributes": pos},
                    {"type": "cameraTargetEffect", "attributes": [
                        {"type": "enabled", "value": {}},
                        {"type": "poi", "attributes": [
                            {"type": "longitudePOI", "value": {}},
                            {"type": "latitudePOI", "value": {}},
                            {"type": "altitudePOI", "value": {"logarithmic": False}}]},
                        {"type": "influence", "value": {}}]},
                    {"type": "cameraRotationGroup", "inTimeline": True, "attributes": rotb},
                    {"type": "cameraLensGroup", "attributes": [
                        {"type": "fov", "value": {}}, {"type": "exposure", "value": {}},
                        {"type": "aperture", "value": {}}, {"type": "minFocusLength", "value": {}}]},
                ]},
                {"type": "environmentGroup", "attributes": [
                    {"type": "sunGroup", "attributes": [
                        {"type": "sunVisibility", "value": {}},
                        {"type": "worldTime", "value": {"relative": 0.5}}]},
                    {"type": "cloudGroup", "attributes": [
                        {"type": "cloudVisibility", "value": {}}, {"type": "cloudopacity", "value": {}},
                        {"type": "cloudheight", "value": {}}, {"type": "clouddate", "value": {"relative": 0.95}}]},
                    {"type": "starsPlanetsGroup", "attributes": [{"type": "starsEnabled", "value": {}}]},
                    {"type": "seawaterGroup", "attributes": [
                        {"type": "seawater", "value": {}}, {"type": "influence", "value": {"relative": 1}}]},
                    {"type": "buildingsEnabled", "value": {}},
                ]},
            ],
            "cameraExport": {"logarithmic": False, "modelVersion": 2},
        }],
        "playbackManager": {"range": {"start": 0, "end": frames}},
    }


def _inject(template: dict, pos, rotb, frames, fps, width, height, name):
    esp = copy.deepcopy(template)
    hit = {"pos": False, "rot": False}

    def walk(o):
        if isinstance(o, dict):
            if o.get("type") == "cameraPositionGroup":
                o["attributes"] = pos
                hit["pos"] = True
            elif o.get("type") == "cameraRotationGroup":
                o["attributes"] = rotb
                hit["rot"] = True
            elif o.get("type") == "cameraTargetEffect":
                for a in o.get("attributes", []):          # make sure target is OFF
                    if a.get("type") == "enabled":
                        a["value"] = {}
                        a.pop("keyframes", None)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(esp)
    if not (hit["pos"] and hit["rot"]):
        raise ValueError("template has no cameraPositionGroup/cameraRotationGroup")
    esp.setdefault("settings", {}).update(name=name, frameRate=fps, duration=frames, timeFormat="frames",
                                          dimensions={"width": width, "height": height})
    for sc in esp.get("scenes", []):
        sc["duration"] = frames
    esp["playbackManager"] = {"range": {"start": 0, "end": frames}}
    return esp


def build_esp(plan, template: Optional[dict] = None, part: Optional[int] = None) -> dict:
    """Project dict for the whole plan, or for one part (see Settings.max_part_seconds)."""
    st = plan.settings
    parts = plan.parts()
    a, b = parts[part or 0] if part is not None or len(parts) == 1 else (0.0, plan.frames / st.fps)
    t, cam, rot, _ = plan.keyframes(a, b)
    frames = int(round((b - a) * st.fps))
    pos, rotb = encode_tracks(t, cam, rot, frames / st.fps)
    name = st.title if len(parts) == 1 or part is None else f"{st.title} part {part + 1}"
    if template is not None:
        return _inject(template, pos, rotb, frames, st.fps, st.width, st.height, name)
    return _template(name, st.fps, st.width, st.height, frames, pos, rotb)


def write_esp(plan, path, template_path: Optional[str] = None):
    """Write path (or path_part01.esp, ... when the plan is split). Returns list of files."""
    import os
    tpl = None
    if template_path:
        with open(template_path) as f:
            tpl = json.load(f)
    parts = plan.parts()
    if len(parts) == 1:
        with open(path, "w") as f:
            json.dump(build_esp(plan, tpl, 0), f, separators=(",", ":"))
        return [path]
    base, ext = os.path.splitext(path)
    out = []
    for k in range(len(parts)):
        p = f"{base}_part{k + 1:02d}{ext or '.esp'}"
        with open(p, "w") as f:
            json.dump(build_esp(plan, tpl, k), f, separators=(",", ":"))
        out.append(p)
    return out
