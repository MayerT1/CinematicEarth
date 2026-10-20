"""Decode an .esp the way Earth Studio would (per-channel interpolation between
keyframes) and render a low-res wireframe preview, so camera motion can be
checked before opening Earth Studio.  Also used by the tests to prove the
camera stays locked on each city.
"""
from __future__ import annotations

import math
import subprocess
from typing import Optional

import numpy as np

from . import geo
from .esp import decode_tracks


class PlanWindows:
    """Minimal stand-in for a Plan, loaded from a .plan.json (stop windows only)."""

    def __init__(self, path_or_dict):
        if isinstance(path_or_dict, dict):
            self._d = path_or_dict
        else:
            import json
            with open(path_or_dict) as f:
                self._d = json.load(f)

    def stop_windows(self):
        return self._d["stops"]


def tracks_from_esp(esp: dict):
    t, cam, rot = decode_tracks(esp)
    fps = esp["settings"]["frameRate"]
    frames = esp["settings"]["duration"]
    return t, cam, rot, fps, frames


def interp_camera(t, cam, rot, tq):
    return (np.interp(tq, t, cam[:, 0]), np.interp(tq, t, cam[:, 1]), np.interp(tq, t, cam[:, 2]),
            np.interp(tq, t, rot[:, 0]), np.interp(tq, t, rot[:, 1]))


class Projector:
    def __init__(self, lat, lon, alt, heading, tilt, width, height, vfov=35.0):
        self.c = np.array(geo.ecef(lat, lon, alt))
        e, n, u = (np.array(v) for v in geo.enu_basis(lat, lon))
        h, t = math.radians(heading), math.radians(tilt)
        self.f = math.sin(t) * math.sin(h) * e + math.sin(t) * math.cos(h) * n - math.cos(t) * u
        self.r = math.cos(h) * e - math.sin(h) * n
        self.u = np.cross(self.r, self.f)
        self.W, self.H = width, height
        self.fpx = (height / 2) / math.tan(math.radians(vfov) / 2)

    def project(self, P):
        """P: (N,3) ECEF -> (N,2) pixels, visible mask."""
        v = P - self.c
        z = v @ self.f
        x = v @ self.r
        y = v @ self.u
        # horizon test: surface point visible if camera is on its outward side
        facing = np.einsum("ij,ij->i", P, -v) > 0
        vis = (z > 1.0) & facing
        with np.errstate(divide="ignore", invalid="ignore"):
            px = self.W / 2 + self.fpx * x / z
            py = self.H / 2 - self.fpx * y / z
        return np.c_[px, py], vis


def centering_error(plan_or_esp, plan=None, width=1920, height=1080, step=None):
    """Max/mean pixel offset of each stop from screen centre during its stop window,
    using Earth Studio-style linear interpolation of the written .esp tracks."""
    esp = plan_or_esp
    t, cam, rot, fps, frames = tracks_from_esp(esp)
    out = []
    for w in plan.stop_windows():
        ts = np.arange(w["t_start"], w["t_end"], step or 1.0 / fps)
        P = np.array([geo.ecef(w["lat"], w["lon"], w["elev"])])
        errs = []
        for tq in ts:
            pr = Projector(*interp_camera(t, cam, rot, tq), width, height)
            (px, py), = pr.project(P)[0]
            errs.append(math.hypot(px - width / 2, py - height / 2))
        out.append((w["name"], float(np.max(errs)), float(np.mean(errs))))
    return out


def _sphere_lines(lat0, lon0, span_deg, step_deg, alt=0.0, n=60):
    lines = []
    for la in np.arange(math.floor((lat0 - span_deg) / step_deg) * step_deg, lat0 + span_deg + 1e-9, step_deg):
        lo = np.linspace(lon0 - span_deg, lon0 + span_deg, n)
        lines.append(np.array([geo.ecef(la, x, alt) for x in lo]))
    for lo in np.arange(math.floor((lon0 - span_deg) / step_deg) * step_deg, lon0 + span_deg + 1e-9, step_deg):
        la = np.clip(np.linspace(lat0 - span_deg, lat0 + span_deg, n), -89.9, 89.9)
        lines.append(np.array([geo.ecef(x, lo, alt) for x in la]))
    return lines


def render_preview(esp: dict, plan, out="flyover_preview.mp4", width=640, height=360, fps=None,
                   max_seconds: Optional[float] = None, start: float = 0.0):
    """Wireframe preview: global graticule + local grid around each stop + stop markers."""
    import cv2
    t, cam, rot, efps, frames = tracks_from_esp(esp)
    fps = fps or efps
    T = frames / efps - start if max_seconds is None else min(frames / efps - start, max_seconds)
    glob_lines = _sphere_lines(0, 0, 180, 10, n=181)
    stops = plan.stop_windows()
    local = [(_sphere_lines(s["lat"], s["lon"], 0.15, 0.01, s["elev"], n=31),
              _sphere_lines(s["lat"], s["lon"], 2.0, 0.1, s["elev"], n=41)) for s in stops]
    pts = np.array([geo.ecef(s["lat"], s["lon"], s["elev"]) for s in stops])
    enc = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24",
                            "-s", f"{width}x{height}", "-r", str(fps), "-i", "-", "-c:v", "libx264",
                            "-pix_fmt", "yuv420p", "-crf", "23", out], stdin=subprocess.PIPE)
    for k in range(int(T * fps)):
        tq = start + k / fps
        lat, lon, alt, h, tl = interp_camera(t, cam, rot, tq)
        pr = Projector(lat, lon, alt, h, tl, width, height)
        img = np.full((height, width, 3), (40, 22, 12), np.uint8)
        # earth disc / ground tint
        agl = alt
        groups = [(glob_lines, (90, 90, 90))]
        for i, s in enumerate(stops):
            d = geo.haversine(lat, lon, s["lat"], s["lon"])
            if d < 400_000:
                groups.append((local[i][1], (60, 140, 60)))
            if d < 40_000:
                groups.append((local[i][0], (80, 200, 200)))
        for lines, col in groups:
            for L in lines:
                p, v = pr.project(L)
                seg = []
                for q, ok in zip(p, v):
                    if ok and abs(q[0]) < 4 * width and abs(q[1]) < 4 * height:
                        seg.append(q)
                    elif len(seg) > 1:
                        cv2.polylines(img, [np.int32(seg)], False, col, 1, cv2.LINE_AA)
                        seg = []
                    else:
                        seg = []
                if len(seg) > 1:
                    cv2.polylines(img, [np.int32(seg)], False, col, 1, cv2.LINE_AA)
        p, v = pr.project(pts)
        for i, (q, ok) in enumerate(zip(p, v)):
            if ok and 0 <= q[0] < width and 0 <= q[1] < height:
                cv2.circle(img, (int(q[0]), int(q[1])), 4, (0, 176, 255), -1, cv2.LINE_AA)
                cv2.putText(img, stops[i]["title"].split(",")[0], (int(q[0]) + 6, int(q[1]) - 6),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1, cv2.LINE_AA)
        cv2.drawMarker(img, (width // 2, height // 2), (255, 255, 255), cv2.MARKER_CROSS, 10, 1)
        cv2.putText(img, f"t={tq:5.1f}s  alt={alt / 1000:8.1f} km  pan={h % 360:5.1f}  tilt={tl:4.1f}",
                    (8, height - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (220, 220, 220), 1, cv2.LINE_AA)
        enc.stdin.write(img.tobytes())
    enc.stdin.close()
    enc.wait()
    return out
