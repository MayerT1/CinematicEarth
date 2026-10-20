"""Cinematic camera planner.

Everything is planned as a LookAt view (target point + range/tilt/heading), so
the city stays centred by construction. Each view is converted to a camera
position and an *exact* pan/tilt that aims at the target; that is what gets
written to the .esp.

Pacing: transit legs are reparameterised by a perceived "visual speed"
(lateral screen motion + zoom rate + rotation rate) and their duration is set
so the peak visual speed never exceeds the chosen preset. That is what keeps
the camera from rocketing across the map.
"""
from __future__ import annotations

import json
import math
import warnings
from dataclasses import dataclass, field, asdict
from typing import Callable, List, Optional, Sequence

import numpy as np

from . import geo
from .model import Settings, Stop, Move, parse_moves

W_LAT, W_ZOOM, W_ROT, W_TILT = 1.6, 0.22, 0.5, 0.6     # visual-speed weights
PEAK = {"smooth": 1.875, "sine": math.pi / 2, "linear": 1.0}


# ---------------- easing ----------------
def ease_fn(name: str) -> Callable[[float], float]:
    if name == "linear":
        return lambda s: s
    if name == "sine":
        return lambda s: 0.5 - 0.5 * math.cos(math.pi * s)
    return lambda s: s * s * s * (s * (6 * s - 15) + 10)     # smootherstep


def _smooth(x):
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


def _clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


# ---------------- view ----------------
@dataclass
class View:
    lat: float
    lon: float
    elev: float
    rng: float
    tilt: float
    heading: float

    def camera(self):
        return geo.lookat_to_camera(self.lat, self.lon, self.elev, self.rng, self.tilt, self.heading)


def view_from_camera(tlat, tlon, telev, clat, clon, calt) -> View:
    """Derive LookAt (range/tilt/heading in the target's frame) from a camera position."""
    t = geo.ecef(tlat, tlon, telev)
    c = geo.ecef(clat, clon, calt)
    v = tuple(c[i] - t[i] for i in range(3))
    e, n, u = geo.enu_basis(tlat, tlon)
    ve, vn, vu = geo._dot(v, e), geo._dot(v, n), geo._dot(v, u)
    rng = math.sqrt(ve * ve + vn * vn + vu * vu)
    tilt = math.degrees(math.atan2(math.hypot(ve, vn), vu))
    heading = (math.degrees(math.atan2(ve, vn)) + 180.0) % 360.0   # camera looks opposite to offset
    return View(tlat, tlon, telev, rng, tilt, heading)


def visual_delta(a: View, b: View) -> float:
    """Approximate on-screen motion between two views (screen-widths).

    Target motion across the view direction counts fully; motion along the view
    direction (flying "into" the picture) counts by cos(tilt), since a forward-
    looking camera sees mostly a gentle zoom rather than a sideways smear.
    """
    d = geo.haversine(a.lat, a.lon, b.lat, b.lon)
    lat = 0.0
    if d > 0:
        brg = geo.bearing(a.lat, a.lon, b.lat, b.lon)
        rel = math.radians(brg - 0.5 * (a.heading + b.heading))
        tilt = math.radians(0.5 * (a.tilt + b.tilt))
        fwd, side = d * math.cos(rel), d * math.sin(rel)
        lat = W_LAT * math.hypot(side, fwd * max(0.35, math.cos(tilt))) / max(1.0, 0.5 * (a.rng + b.rng))
    zoom = abs(math.log(b.rng / a.rng)) * W_ZOOM
    rot = abs(geo.wrap180(b.heading - a.heading)) * math.pi / 180 * W_ROT
    tl = abs(b.tilt - a.tilt) * math.pi / 180 * W_TILT
    return math.sqrt(lat * lat + zoom * zoom + rot * rot + tl * tl)


# ---------------- pieces of the timeline ----------------
@dataclass
class Piece:
    kind: str                  # stop | glide | hop | cut | intro | outro
    duration: float
    eval: Callable[[float], View]       # local progress s in [0,1] -> view (already eased)
    stop_index: Optional[int] = None
    leg_to: Optional[int] = None
    km: float = 0.0
    visual: float = 0.0        # integrated visual distance (transits)
    t0: float = 0.0

    @property
    def t1(self):
        return self.t0 + self.duration


# ---------- stop segments ----------
def _apply_moves(v0: View, moves: Sequence[Move], e: float) -> View:
    v = View(**asdict(v0))
    truck = rise = 0.0
    for m in moves:
        if m.kind == "orbit":
            v.heading = v0.heading + m.b * e
        elif m.kind == "zoom":
            a = m.a if m.a is not None else v0.rng
            if m.rel == "in":
                b = a * 0.5
            elif m.rel == "out":
                b = a * 2.0
            else:
                b = m.b
            v.rng = math.exp(math.log(a) + (math.log(b) - math.log(a)) * e)
        elif m.kind == "tilt":
            a = m.a if m.a is not None else v0.tilt
            v.tilt = a + (m.b - a) * e
        elif m.kind == "truck":
            truck = m.b * e
        elif m.kind == "rise":
            rise = m.b * e
    if truck or rise:
        clat, clon, calt = v.camera()
        if truck:
            clat, clon = geo.destination(clat, clon, v.heading + 90.0, truck) if truck > 0 else \
                geo.destination(clat, clon, v.heading - 90.0, -truck)
        calt = max(v.elev + 50.0, calt + rise)
        nv = view_from_camera(v.lat, v.lon, v.elev, clat, clon, calt)
        nv.heading = geo.unwrap_to(nv.heading, v.heading)
        v = nv
    return v


def _start_values(moves_segments, settings: Settings):
    """Initial range/tilt for a stop = first explicit 'from' value (else defaults)."""
    rng = tilt = None
    for seg in moves_segments:
        for m in seg.moves:
            if m.kind == "zoom" and rng is None and m.a is not None:
                rng = m.a
            if m.kind == "tilt" and tilt is None and m.a is not None:
                tilt = m.a
    return rng or settings.range_start, tilt if tilt is not None else settings.tilt


def build_stop_pieces(i: int, stop: Stop, start: View, settings: Settings) -> List[Piece]:
    script = parse_moves(stop.moves, settings, i)
    E = ease_fn(settings.ease)
    D = (stop.duration or settings.stop_duration) * script.stretch
    timed = sum(s.duration * script.stretch for s in script.segments if s.duration)
    untimed = [s for s in script.segments if not s.duration]
    share = max(1.0, (D - timed) / len(untimed)) if untimed else 0.0
    pieces, v = [], start
    for seg in script.segments:
        dur = seg.duration * script.stretch if seg.duration else share
        v0 = View(**asdict(v))
        f = (lambda v0, moves: (lambda s: _apply_moves(v0, moves, E(s))))(v0, seg.moves)
        pieces.append(Piece("stop", dur, f, stop_index=i))
        v = f(1.0)
    return pieces


# ---------- transits ----------
def _leg_path(a: View, b: View, kind: str, settings: Settings):
    """Return path(u) -> View for u in [0,1] (unparameterised)."""
    d = geo.haversine(a.lat, a.lon, b.lat, b.lon)
    planar = d > 1 and geo.gc_crosses_antimeridian(a.lat, a.lon, b.lat, b.lon)

    def tpos(p):
        if d < 1:
            return a.lat, a.lon
        if planar:
            return a.lat + (b.lat - a.lat) * p, a.lon + (b.lon - a.lon) * p
        return geo.gc_interp(a.lat, a.lon, b.lat, b.lon, p)

    la, lb = math.log(a.rng), math.log(b.rng)
    if kind == "hop":
        apex = min(settings.max_apex, max(4 * max(a.rng, b.rng), settings.hop_apex * d))
        tmid, lateral = settings.hop_tilt, lambda u: _smooth((u - 0.18) / 0.64)
    elif kind == "glide":
        apex = max(1.4 * max(a.rng, b.rng), settings.glide_apex * d)
        tmid, lateral = settings.glide_tilt, lambda u: _smooth((u - 0.08) / 0.84)
    else:  # intro / outro: straight log zoom, no bump
        apex, tmid, lateral = None, None, lambda u: u
    lapex = math.log(apex) if apex else None
    hb_un = geo.unwrap_to(b.heading, a.heading)

    def path(u):
        p = lateral(u)
        lat, lon = tpos(p)
        elev = a.elev + (b.elev - a.elev) * p
        lr = la + (lb - la) * u
        if lapex is not None:
            mid = 0.5 * (la + lb)
            lr += max(0.0, lapex - mid) * math.sin(math.pi * u)
        tilt = a.tilt + (b.tilt - a.tilt) * u
        if tmid is not None:
            tilt += (tmid - (a.tilt + b.tilt) / 2) * math.sin(math.pi * u)
        if d < 1 or kind in ("intro", "outro"):
            hd = a.heading + (hb_un - a.heading) * _smooth(u)
        else:
            q = min(p, 0.995)
            la1, lo1 = tpos(q)
            la2, lo2 = tpos(min(1.0, q + 0.005))
            travel = geo.unwrap_to(geo.bearing(la1, lo1, la2, lo2), a.heading)
            hd = a.heading + (travel - a.heading) * _smooth(u / 0.3)
            hd = hd + geo.wrap180(hb_un - hd) * _smooth((u - 0.7) / 0.3)
        return View(lat, lon, elev, math.exp(lr), tilt, hd)

    return path, d


def arrival_heading(a_lat, a_lon, b_lat, b_lon) -> float:
    if geo.haversine(a_lat, a_lon, b_lat, b_lon) < 1:
        return 0.0
    if geo.gc_crosses_antimeridian(a_lat, a_lon, b_lat, b_lon):
        la1, lo1 = a_lat + (b_lat - a_lat) * 0.99, a_lon + (b_lon - a_lon) * 0.99
        return geo.bearing(la1, lo1, b_lat, b_lon)
    la1, lo1 = geo.gc_interp(a_lat, a_lon, b_lat, b_lon, 0.99)
    return geo.bearing(la1, lo1, b_lat, b_lon)


def build_leg(kind: str, a: View, b: View, settings: Settings, n=500) -> Piece:
    path, d = _leg_path(a, b, kind, settings)
    us = np.linspace(0, 1, n + 1)
    views = [path(u) for u in us]
    cum = np.zeros(n + 1)
    for k in range(n):
        cum[k + 1] = cum[k] + visual_delta(views[k], views[k + 1])
    total = float(cum[-1])
    E = ease_fn(settings.ease)

    def f(s):
        if total <= 0:
            return path(s)
        u = float(np.interp(E(s) * total, cum, us))
        return path(u)

    return Piece(kind, 0.0, f, km=d / 1000, visual=total)


# ---------------- plan ----------------
@dataclass
class Plan:
    settings: Settings
    stops: List[Stop]
    pieces: List[Piece]
    times: np.ndarray = None
    cam: np.ndarray = None       # (N,3) lat, lon, alt
    target: np.ndarray = None    # (N,3) lat, lon, elev
    rot: np.ndarray = None       # (N,2) heading(unwrapped), tilt
    report: List[dict] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return self.pieces[-1].t1

    @property
    def frames(self) -> int:
        return int(round(self.duration * self.settings.fps))

    def stop_windows(self):
        out = []
        for i, s in enumerate(self.stops):
            ps = [p for p in self.pieces if p.kind == "stop" and p.stop_index == i]
            out.append({"index": i, "name": s.name, "title": s.title, "note": s.note,
                        "lat": s.lat, "lon": s.lon, "elev": s.elev,
                        "t_start": ps[0].t0, "t_end": ps[-1].t1})
        return out

    def view_at(self, t: float) -> View:
        for p in self.pieces:
            if t <= p.t1 + 1e-9:
                return p.eval(_clamp((t - p.t0) / p.duration) if p.duration > 0 else 1.0)
        return self.pieces[-1].eval(1.0)

    def sample(self, ts, ref_heading=None):
        """Camera (lat,lon,alt), target, rotation (pan unwrapped, tilt) at times ts."""
        cam, tgt, rot = [], [], []
        prev_h = ref_heading
        for t in ts:
            v = self.view_at(float(t))
            clat, clon, calt = v.camera()
            h, tl = geo.look_rotation(clat, clon, calt, v.lat, v.lon, v.elev)
            if h is None:                       # nadir view: heading undefined, keep planned one
                h = v.heading
            h = geo.unwrap_to(h, prev_h if prev_h is not None else v.heading)
            prev_h = h
            cam.append((clat, clon, calt))
            tgt.append((v.lat, v.lon, v.elev))
            rot.append((h, tl))
        return np.asarray(ts, float), np.array(cam), np.array(tgt), np.array(rot)

    def boundaries(self):
        return [p.t0 for p in self.pieces] + [self.duration]

    def parts(self):
        """Project windows (t0, t1), split at stop ends, frame-aligned."""
        st = self.settings
        T = self.frames / st.fps
        if not st.max_part_seconds or T <= st.max_part_seconds:
            return [(0.0, T)]
        ends = [round(w["t_end"] * st.fps) / st.fps for w in self.stop_windows()[:-1]]
        out, t0 = [], 0.0
        for k, e in enumerate(ends):
            nxt = ends[k + 1] if k + 1 < len(ends) else T
            if e - t0 >= 1.0 and nxt - t0 > st.max_part_seconds:
                out.append((t0, e))
                t0 = e
        out.append((t0, T))
        return out

    def keyframes(self, t0=0.0, t1=None):
        """Reduced keyframes for window [t0, t1]; times returned relative to t0."""
        from .keyframes import reduce_keyframes
        st = self.settings
        t1 = self.frames / st.fps if t1 is None else t1
        m = (self.times > t0 + 1e-6) & (self.times < t1 - 1e-6)
        ts = np.r_[t0, self.times[m], t1]
        i0 = int(np.argmin(np.abs(self.times - t0)))
        t, cam, tgt, rot = self.sample(ts, ref_heading=self.rot[i0, 0])
        shift = 360.0 * round(0.5 * (rot[:, 0].min() + rot[:, 0].max()) / 360.0)
        rot = rot.copy()
        rot[:, 0] -= shift                      # keep pan near 0 (same view, smaller range)
        if st.keyframe_every_frame:
            return t - t0, cam, rot, tgt
        keep = [b for b in self.boundaries() if t0 < b < t1]
        # strict at stops (city locked to centre, annotations), relaxed in transit
        at_stop = np.zeros(len(t), bool)
        for w in self.stop_windows():
            at_stop |= (t >= w["t_start"] - 1e-6) & (t <= w["t_end"] + 1e-6)
        px = np.where(at_stop, st.keyframe_tol_px, 60.0)
        pos = np.where(at_stop, 0.004, 0.06)
        ang = np.where(at_stop, 0.75, 4.0)
        idx = reduce_keyframes(t, cam, rot, tgt, keep=keep, tol_px=px, pos_tol=pos, ang_tol=ang,
                               max_gap=st.max_key_gap, height=st.height)
        return t[idx] - t0, cam[idx], rot[idx], tgt[idx]

    def summary(self) -> str:
        lines = [f"{'leg':40s} {'km':>8s} {'type':>6s} {'sec':>6s} {'peak v':>7s}"]
        for r in self.report:
            lines.append(f"{r['leg']:40s} {r['km']:8.0f} {r['type']:>6s} {r['sec']:6.1f} {r['peak_v']:7.3f}")
        st = sum(p.duration for p in self.pieces if p.kind == "stop")
        nk = sum(len(self.keyframes(a, b)[0]) for a, b in self.parts())
        lines.append(f"total {self.duration:.1f}s ({self.frames} frames @ {self.settings.fps} fps) | "
                     f"stops {st:.1f}s | transits {self.duration - st:.1f}s | "
                     f"{nk} .esp keyframes in {len(self.parts())} project(s)")
        lines += [f"WARNING: {w}" for w in self.warnings]
        return "\n".join(lines)

    def to_json(self) -> dict:
        return {
            "settings": self.settings.to_dict(),
            "duration": self.duration, "frames": self.frames,
            "stops": self.stop_windows(),
            "cuts": [p.t0 for p in self.pieces if p.kind == "cut"],
            "parts": [{"t_start": a, "t_end": b, "frames": int(round((b - a) * self.settings.fps))}
                      for a, b in self.parts()],
            "report": self.report,
            "samples": {"t": self.times.tolist(), "cam": self.cam.tolist(),
                        "target": self.target.tolist(), "rot": self.rot.tolist()},
        }

    def save_json(self, path):
        with open(path, "w") as f:
            json.dump(self.to_json(), f)


def plan_flyover(stops: Sequence[Stop], settings: Optional[Settings] = None) -> Plan:
    settings = settings or Settings()
    stops = list(stops)
    if not stops:
        raise ValueError("no stops")
    for s in stops:
        if s.lat is None or s.lon is None:
            raise ValueError(f"stop {s.name!r} has no coordinates (use geocode=True or add lat/lon)")
        s.elev = float(s.elev or 0.0)

    n = len(stops)
    # start heading at each stop = arrival direction
    heads = []
    for i, s in enumerate(stops):
        if s.heading is not None:
            heads.append(float(s.heading))
        elif i > 0:
            heads.append(arrival_heading(stops[i - 1].lat, stops[i - 1].lon, s.lat, s.lon))
        elif n > 1:
            heads.append(geo.bearing(s.lat, s.lon, stops[1].lat, stops[1].lon))
        else:
            heads.append(0.0)

    pieces: List[Piece] = []
    stop_pieces = []
    for i, s in enumerate(stops):
        script = parse_moves(s.moves, settings, i)
        r0, t0 = _start_values(script.segments, settings)
        start = View(s.lat, s.lon, s.elev, r0, t0, heads[i])
        stop_pieces.append(build_stop_pieces(i, s, start, settings))

    if settings.intro:
        first = stop_pieces[0][0].eval(0.0)
        sky = View(first.lat, first.lon, first.elev, settings.space_range, 0.0, first.heading)
        pieces.append(build_leg("intro", sky, first, settings))
    for i in range(n):
        if i > 0:
            a = pieces[-1].eval(1.0)
            b = stop_pieces[i][0].eval(0.0)
            b.heading = geo.unwrap_to(b.heading, a.heading)
            kind = (stops[i].transit or "auto").lower()
            d = geo.haversine(a.lat, a.lon, b.lat, b.lon)
            if kind == "auto":
                if settings.cut_km is not None and d / 1000 > settings.cut_km:
                    kind = "cut"
                else:
                    kind = "glide" if d / 1000 < settings.glide_km else "hop"
            if kind == "cut":
                pc = Piece("cut", 1.0 / settings.fps, lambda s, a=a, b=b: a if s < 1 else b, km=d / 1000)
                pc.leg_to = i
                pieces.append(pc)
            else:
                leg = build_leg(kind, a, b, settings)
                leg.leg_to = i
                pieces.append(leg)
            # shift stop headings so the whole track stays continuous
            off = b.heading - stop_pieces[i][0].eval(0.0).heading
            if abs(off) > 1e-9:
                s = stops[i]
                script = parse_moves(s.moves, settings, i)
                r0, t0 = _start_values(script.segments, settings)
                stop_pieces[i] = build_stop_pieces(i, s, View(s.lat, s.lon, s.elev, r0, t0, b.heading), settings)
        pieces.extend(stop_pieces[i])
    if settings.outro:
        last = pieces[-1].eval(1.0)
        sky = View(last.lat, last.lon, last.elev, settings.space_range, 0.0, last.heading + 20)
        pieces.append(build_leg("outro", last, sky, settings))

    plan = Plan(settings, stops, pieces)
    _fit_durations(plan)
    _sample(plan)
    _report(plan)
    return plan


def _fit_durations(plan: Plan):
    st = plan.settings
    peak = PEAK.get(st.ease, 1.875)
    legs = [p for p in plan.pieces if p.kind in ("glide", "hop", "intro", "outro")]
    stops_total = sum(p.duration for p in plan.pieces if p.kind == "stop")
    cuts_total = sum(p.duration for p in plan.pieces if p.kind == "cut")
    vmax = st.vmax()

    def assign(k):          # k = seconds per unit visual distance
        for p in legs:
            floor = st.min_leg * (1.8 if p.kind in ("intro", "outro") else 1.0)
            p.duration = max(floor, k * p.visual)

    if st.duration is None:
        assign(peak / vmax)
    else:
        avail = st.duration - stops_total - cuts_total
        floor = sum(st.min_leg * (1.8 if p.kind in ("intro", "outro") else 1.0) for p in legs)
        if avail < floor:
            need = st.duration - cuts_total - floor
            if need <= 0:
                raise ValueError(f"duration {st.duration}s is too short for {len(plan.stops)} stops")
            f = need / stops_total
            for p in plan.pieces:
                if p.kind == "stop":
                    p.duration *= f
            plan.warnings.append(f"duration {st.duration:.0f}s too short: stop time scaled x{f:.2f}; "
                                 "transits at minimum length (will look fast)")
            assign(0.0)
        else:
            lo, hi = 0.0, 1e4
            for _ in range(80):
                mid = 0.5 * (lo + hi)
                assign(mid)
                if sum(p.duration for p in legs) > avail:
                    hi = mid
                else:
                    lo = mid
            assign(lo)
            eff = peak / lo if lo > 0 else float("inf")
            if eff > vmax * 1.05:
                plan.warnings.append(
                    f"duration {st.duration:.0f}s forces transit speed {eff:.2f} > '{st.speed}' ({vmax:.2f}); "
                    f"auto duration for this preset would be longer. Raise duration or reduce stops/stop time.")
    # snap total to whole frames
    t = 0.0
    for p in plan.pieces:
        p.t0 = t
        t += p.duration
    frames = max(1, round(t * st.fps))
    scale = frames / st.fps / t
    t = 0.0
    for p in plan.pieces:
        p.duration *= scale
        p.t0 = t
        t += p.duration


def _sample(plan: Plan):
    st = plan.settings
    rate = st.fps if st.keyframe_every_frame else st.sample_rate
    ts = []
    for p in plan.pieces:
        if p.kind == "cut":
            f0 = round(p.t0 * st.fps)
            ts += [f0 / st.fps, (f0 + 1) / st.fps]
            continue
        k = max(2, int(math.ceil(p.duration * rate)) + 1)
        ts += list(np.linspace(p.t0, p.t1, k))
    ts = np.unique(np.round(np.array(ts), 6))
    plan.times, plan.cam, plan.target, plan.rot = plan.sample(ts)
    clearance = plan.cam[:, 2] - plan.target[:, 2]
    if clearance.min() < 150:
        plan.warnings.append(f"camera gets within {clearance.min():.0f} m of target ground level")


def _report(plan: Plan):
    names = [s.name for s in plan.stops]
    for p in plan.pieces:
        if p.kind == "stop":
            continue
        if p.kind == "intro":
            leg = f"(space) -> {names[0]}"
        elif p.kind == "outro":
            leg = f"{names[-1]} -> (space)"
        else:
            leg = f"{names[p.leg_to - 1]} -> {names[p.leg_to]}"
        peak = 0.0
        if p.duration > 0 and p.kind != "cut":
            ss = np.linspace(0, 1, 121)
            vs = [p.eval(s) for s in ss]
            dt = p.duration / 120
            peak = max(visual_delta(vs[k], vs[k + 1]) / dt for k in range(120))
        plan.report.append({"leg": leg[:40], "km": p.km, "type": p.kind, "sec": p.duration, "peak_v": peak})
