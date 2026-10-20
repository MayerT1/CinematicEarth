"""Geodesy helpers: spherical-earth great circles, ENU frames, LookAt <-> camera."""
from __future__ import annotations

import math
from typing import Tuple

R_E = 6_371_000.0
rad, deg = math.radians, math.degrees


def wrap180(a: float) -> float:
    return (a + 180.0) % 360.0 - 180.0


def unwrap_to(a: float, ref: float) -> float:
    """Return angle equal to `a` (mod 360) closest to `ref` (continuous headings)."""
    return ref + wrap180(a - ref)


def haversine(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = rad(lat1), rad(lat2)
    dp, dl = p2 - p1, rad(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R_E * math.asin(min(1.0, math.sqrt(h)))


def bearing(lat1, lon1, lat2, lon2) -> float:
    p1, p2, dl = rad(lat1), rad(lat2), rad(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return deg(math.atan2(y, x)) % 360.0


def destination(lat, lon, brg, dist) -> Tuple[float, float]:
    p1, l1, b, d = rad(lat), rad(lon), rad(brg), dist / R_E
    p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(b))
    l2 = l1 + math.atan2(math.sin(b) * math.sin(d) * math.cos(p1),
                         math.cos(d) - math.sin(p1) * math.sin(p2))
    return deg(p2), wrap180(deg(l2))


def gc_interp(lat1, lon1, lat2, lon2, f) -> Tuple[float, float]:
    """Point at fraction f along the great circle."""
    p1, l1, p2, l2 = rad(lat1), rad(lon1), rad(lat2), rad(lon2)
    d = haversine(lat1, lon1, lat2, lon2) / R_E
    if d < 1e-12:
        return lat1, lon1
    a = math.sin((1 - f) * d) / math.sin(d)
    b = math.sin(f * d) / math.sin(d)
    x = a * math.cos(p1) * math.cos(l1) + b * math.cos(p2) * math.cos(l2)
    y = a * math.cos(p1) * math.sin(l1) + b * math.cos(p2) * math.sin(l2)
    z = a * math.sin(p1) + b * math.sin(p2)
    return deg(math.atan2(z, math.hypot(x, y))), deg(math.atan2(y, x))


def gc_crosses_antimeridian(lat1, lon1, lat2, lon2, n=64) -> bool:
    prev = lon1
    for k in range(1, n + 1):
        _, lo = gc_interp(lat1, lon1, lat2, lon2, k / n)
        if abs(lo - prev) > 180:
            return True
        prev = lo
    return False


# ---------- ECEF / ENU (spherical) ----------
def ecef(lat, lon, alt):
    r = R_E + alt
    p, l = rad(lat), rad(lon)
    return (r * math.cos(p) * math.cos(l), r * math.cos(p) * math.sin(l), r * math.sin(p))


def enu_basis(lat, lon):
    p, l = rad(lat), rad(lon)
    e = (-math.sin(l), math.cos(l), 0.0)
    n = (-math.sin(p) * math.cos(l), -math.sin(p) * math.sin(l), math.cos(p))
    u = (math.cos(p) * math.cos(l), math.cos(p) * math.sin(l), math.sin(p))
    return e, n, u


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def look_rotation(cam_lat, cam_lon, cam_alt, tgt_lat, tgt_lon, tgt_alt) -> Tuple[float, float]:
    """Exact (heading, tilt) for a camera at cam_* to centre the target point.

    heading: compass degrees (0 = north, clockwise). tilt: 0 = straight down, 90 = horizon.
    """
    c = ecef(cam_lat, cam_lon, cam_alt)
    t = ecef(tgt_lat, tgt_lon, tgt_alt)
    v = (t[0] - c[0], t[1] - c[1], t[2] - c[2])
    e, n, u = enu_basis(cam_lat, cam_lon)
    ve, vn, vu = _dot(v, e), _dot(v, n), _dot(v, u)
    horiz = math.hypot(ve, vn)
    if horiz < 1e-4 * math.sqrt(ve * ve + vn * vn + vu * vu):   # looking straight down
        return None, deg(math.atan2(horiz, -vu))
    heading = deg(math.atan2(ve, vn)) % 360.0
    tilt = deg(math.atan2(horiz, -vu))
    return heading, tilt


def lookat_to_camera(lat, lon, elev, rng, tilt, heading):
    """LookAt (target + range/tilt/heading) -> camera lat, lon, alt (spherical earth).

    Solves the triangle earth-centre / target / camera so it stays valid from
    street level to orbit.
    """
    rt = R_E + elev
    tr = rad(tilt)
    # camera = target + rng * (sin(tilt) * back-horizontal + cos(tilt) * up), in target ENU
    back = rad(heading + 180.0)
    e, n, u = enu_basis(lat, lon)
    t = ecef(lat, lon, elev)
    h = rng * math.sin(tr)
    vu = rng * math.cos(tr)
    ve, vn = h * math.sin(back), h * math.cos(back)
    c = tuple(t[i] + ve * e[i] + vn * n[i] + vu * u[i] for i in range(3))
    r = math.sqrt(_dot(c, c))
    clat = deg(math.asin(c[2] / r))
    clon = deg(math.atan2(c[1], c[0]))
    return clat, clon, r - R_E


def enu_offset(lat, lon, de, dn):
    """Small local offset (metres east/north) -> lat, lon."""
    dist = math.hypot(de, dn)
    if dist == 0:
        return lat, lon
    return destination(lat, lon, deg(math.atan2(de, dn)), dist)
