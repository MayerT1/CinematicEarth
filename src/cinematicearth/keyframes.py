"""Error-bounded keyframe reduction.

The planner samples the camera densely (default 10 Hz). Earth Studio gets slow,
or crashes the browser tab, when a project carries thousands of keyframes per
track. This module keeps only the keyframes needed for Earth Studio's own
linear interpolation between them to reproduce the dense path:

* each frame's look-at target stays within ``tol_px`` of screen centre
* the camera position stays within ``pos_tol`` x range of the dense path
* pan and tilt stay within ``ang_tol`` degrees

The result is typically 80-95% fewer keyframes.
"""
from __future__ import annotations

import math
from typing import Iterable, List, Optional

import numpy as np

R_E = 6_371_000.0


def _ecef(lat, lon, alt):
    p, l = np.radians(lat), np.radians(lon)
    r = R_E + alt
    return np.stack([r * np.cos(p) * np.cos(l), r * np.cos(p) * np.sin(l), r * np.sin(p)], -1)


def center_offset_px(cam, rot, tgt_ecef, height=1080, vfov=35.0):
    """Vectorised: pixel distance of target from screen centre. cam (N,3) lat/lon/alt, rot (N,2) pan/tilt."""
    lat, lon = np.radians(cam[:, 0]), np.radians(cam[:, 1])
    C = _ecef(cam[:, 0], cam[:, 1], cam[:, 2])
    e = np.stack([-np.sin(lon), np.cos(lon), np.zeros_like(lon)], -1)
    n = np.stack([-np.sin(lat) * np.cos(lon), -np.sin(lat) * np.sin(lon), np.cos(lat)], -1)
    u = np.stack([np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat)], -1)
    h, t = np.radians(rot[:, 0])[:, None], np.radians(rot[:, 1])[:, None]
    f = np.sin(t) * np.sin(h) * e + np.sin(t) * np.cos(h) * n - np.cos(t) * u
    r = np.cos(h) * e - np.sin(h) * n
    up = np.cross(r, f)
    v = tgt_ecef - C
    z = np.einsum("ij,ij->i", v, f)
    x = np.einsum("ij,ij->i", v, r)
    y = np.einsum("ij,ij->i", v, up)
    fpx = (height / 2) / math.tan(math.radians(vfov) / 2)
    with np.errstate(divide="ignore", invalid="ignore"):
        off = fpx * np.hypot(x, y) / z
    off[~(z > 0)] = 1e9
    return off


def reduce_keyframes(times, cam, rot, target, keep: Iterable[float] = (), tol_px=3.0,
                     pos_tol=0.004, ang_tol=0.75, max_gap=4.0, height=1080) -> np.ndarray:
    """Return indices of the keyframes to keep. Tolerances may be scalars or per-sample arrays."""
    times = np.asarray(times)
    n = len(times)
    if n <= 2:
        return np.arange(n)
    T = _ecef(target[:, 0], target[:, 1], target[:, 2])
    C = _ecef(cam[:, 0], cam[:, 1], cam[:, 2])
    rng = np.linalg.norm(C - T, axis=1)
    PX = np.broadcast_to(np.asarray(tol_px, float), (n,))
    POS = np.broadcast_to(np.asarray(pos_tol, float), (n,))
    ANG = np.broadcast_to(np.asarray(ang_tol, float), (n,))
    must = {0, n - 1}
    for tk in keep:
        must.add(int(np.argmin(np.abs(times - tk))))
    must = sorted(must)

    def ok(i, j):
        if times[j] - times[i] > max_gap:
            return False
        if j - i < 2:
            return True
        k = np.arange(i + 1, j)
        w = ((times[k] - times[i]) / (times[j] - times[i]))[:, None]
        ci = cam[i] + (cam[j] - cam[i]) * w
        ri = rot[i] + (rot[j] - rot[i]) * w
        if (np.abs(ri - rot[k]).max(axis=1) > ANG[k]).any():
            return False
        Ci = _ecef(ci[:, 0], ci[:, 1], ci[:, 2])
        if (np.linalg.norm(Ci - C[k], axis=1) / rng[k] > POS[k]).any():
            return False
        return (center_offset_px(ci, ri, T[k], height) <= PX[k]).all()

    out: List[int] = [0]
    for a, b in zip(must[:-1], must[1:]):
        i = a
        while i < b:
            # exponential then binary search for the farthest valid j <= b
            step, j = 1, i + 1
            while j + step <= b and ok(i, j + step):
                j += step
                step *= 2
            lo, hi = j, min(b, j + step)
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if ok(i, mid):
                    lo = mid
                else:
                    hi = mid - 1
            j = max(i + 1, lo)
            out.append(j)
            i = j
    return np.array(sorted(set(out)))
