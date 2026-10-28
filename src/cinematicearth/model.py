"""Data model: stops, global settings, and the camera-move language."""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Union

SPEED_PRESETS = {          # peak "visual speed" for transits (screen units / s)
    "glacial": 0.55,
    "slow": 0.80,
    "medium": 1.20,
    "fast": 1.80,
}


@dataclass
class Settings:
    title: str = "CinematicEarth flyover"
    fps: int = 30
    width: int = 1920
    height: int = 1080
    duration: Optional[float] = None      # total seconds; None = auto from pacing
    speed: Union[str, float] = "slow"     # transit pacing preset or number
    stop_duration: float = 8.0            # seconds spent at each stop
    orbit: float = 45.0                   # default orbit sweep (deg) at each stop
    tilt: float = 60.0                    # default camera tilt at stops (0 down, 90 horizon)
    range_start: float = 7_000.0          # m, LookAt range when arriving at a stop
    range_end: float = 3_500.0            # m, range at end of default pull-in
    direction: Union[int, str] = "alternate"  # 1 clockwise, -1 counter-clockwise, alternate (keeps pan range small)
    ease: str = "smooth"                  # smooth | sine | linear
    intro: bool = True                    # descend from space into first stop
    outro: bool = True                    # pull back to space after last stop
    space_range: float = 12_000_000.0     # m, LookAt range for intro/outro
    glide_km: float = 150.0               # hops shorter than this stay low ("glide")
    glide_tilt: float = 66.0              # tilt mid-glide (forward-looking)
    glide_apex: float = 0.45              # glide cruise range = glide_apex x distance
    cut_km: Optional[float] = None        # hops longer than this become hard cuts (dip to black in annotate)
    hop_tilt: float = 20.0                # tilt at top of high hops
    hop_apex: float = 0.6                 # apex range = hop_apex x distance
    max_apex: float = 9_000_000.0
    min_leg: float = 3.0                  # seconds, floor for any transit
    sample_rate: float = 10.0             # dense camera samples / s (KML, overlay, keyframe source)
    keyframe_tol_px: float = 3.0          # max drift of the city from screen centre between .esp keyframes
    max_key_gap: float = 4.0              # s, longest gap between .esp keyframes
    keyframe_every_frame: bool = False    # write every frame as a keyframe (huge .esp; not recommended)
    max_part_seconds: Optional[float] = None   # split into several .esp projects of at most this length
    layers_dir: str = "cinematicearth_layers"  # where GeoTIFF layers are converted to .kmz
    drive_dir: Optional[str] = None       # Colab: copy .kmz here (under /content/drive) and link it into the .esp
    layers: list = field(default_factory=list)  # GeoTIFF products (cinematicearth.layers.Layer)

    def vmax(self) -> float:
        if isinstance(self.speed, (int, float)):
            return float(self.speed)
        try:
            return SPEED_PRESETS[str(self.speed).lower()]
        except KeyError:
            return float(self.speed)

    def to_dict(self):
        return asdict(self)


@dataclass
class Stop:
    name: str
    lat: Optional[float] = None
    lon: Optional[float] = None
    elev: Optional[float] = None          # ground elevation (m); None = 0 / lookup
    duration: Optional[float] = None      # override Settings.stop_duration
    moves: Optional[str] = None           # move script, see parse_moves
    transit: Optional[str] = None         # how to ARRIVE here: auto | glide | hop | cut
    heading: Optional[float] = None       # start heading at this stop (default: travel direction)
    label: Optional[str] = None           # on-screen title (default: name)
    note: Optional[str] = None            # extra annotation line
    layer: Optional[str] = None           # name of a GeoTIFF layer this stop shows (fly stops)

    @property
    def title(self) -> str:
        return self.label or self.name


# ---------------- move language ----------------
# A move script is a sequence of SEGMENTS separated by ';' (or newlines).
# Each segment holds one or more moves joined with '+' that run TOGETHER,
# plus an optional duration ("6s" / "@6s"). Untimed segments share what is
# left of the stop's duration.
#
#   orbit 45            circle the city 45 deg (negative = other way). alias: pan, circle, spin
#   zoom 8km>3km        LookAt range from>to (m or km). "zoom 3km" = from current.
#   zoom in | zoom out  halve / double the range
#   tilt 50>70          camera tilt from>to (0 = straight down, 90 = horizon)
#   truck 2km           slide the camera sideways (flyby/parallax) keeping the city centred.
#                       alias: flyby, slide. negative = slide left
#   rise 1km            raise/lower the camera while keeping the city centred. alias: crane
#   hold                no motion (use with a duration). alias: pause, wait
#   slow 1.5            stop-level: stretch this stop's duration x1.5. fast 2 = halve
#
# Example:  "orbit 30 + zoom 9km>5km @5s; orbit 30 + tilt 60>72 + zoom 2.5km; hold 1s"

_DUR = re.compile(r"@?\s*(\d+(?:\.\d+)?)\s*(s|sec|secs|seconds)\b", re.I)
_NUM = r"[-+]?\d+(?:\.\d+)?"


def parse_length(tok: str) -> float:
    m = re.fullmatch(rf"\s*({_NUM})\s*(km|m)?\s*", tok, re.I)
    if not m:
        raise ValueError(f"bad length: {tok!r}")
    v = float(m.group(1))
    return v * 1000 if (m.group(2) or "").lower() == "km" else v


def _range_pair(arg: str):
    arg = arg.replace("->", ">").replace("→", ">").replace(" to ", ">")
    if ">" in arg:
        a, b = arg.split(">", 1)
        return parse_length(a), parse_length(b)
    return None, parse_length(arg)


def _num_pair(arg: str):
    arg = arg.replace("->", ">").replace("→", ">").replace(" to ", ">")
    if ">" in arg:
        a, b = arg.split(">", 1)
        return float(a), float(b)
    return None, float(arg)


@dataclass
class Move:
    kind: str                       # orbit | zoom | tilt | truck | rise | hold
    a: Optional[float] = None       # "from" value (zoom/tilt) or None
    b: Optional[float] = None       # "to" value / amount
    rel: Optional[str] = None       # zoom in/out marker


@dataclass
class Segment:
    moves: List[Move] = field(default_factory=list)
    duration: Optional[float] = None


@dataclass
class MoveScript:
    segments: List[Segment]
    stretch: float = 1.0


ALIASES = {
    "orbit": "orbit", "pan": "orbit", "circle": "orbit", "spin": "orbit", "rotate": "orbit",
    "zoom": "zoom", "range": "zoom", "dolly": "zoom", "push": "zoom",
    "tilt": "tilt", "pitch": "tilt",
    "truck": "truck", "flyby": "truck", "slide": "truck", "strafe": "truck",
    "rise": "rise", "crane": "rise", "lift": "rise",
    "hold": "hold", "pause": "hold", "wait": "hold",
    "slow": "slow", "fast": "fast",
}


def orbit_sign(settings: Settings, index: int = 0) -> int:
    d = settings.direction
    if isinstance(d, str):
        if d.lower().startswith("alt"):
            return 1 if index % 2 == 0 else -1
        d = float(d)
    return 1 if float(d) >= 0 else -1


def parse_moves(script: Optional[str], settings: Settings, index: int = 0) -> MoveScript:
    if not script or not str(script).strip():
        script = (f"orbit {settings.orbit * orbit_sign(settings, index)} + "
                  f"zoom {settings.range_start}>{settings.range_end}")
    segs, stretch = [], 1.0
    for raw in re.split(r"[;\n]+", str(script)):
        raw = raw.strip().strip(",")
        if not raw:
            continue
        dur = None
        m = _DUR.search(raw)
        if m:
            dur = float(m.group(1))
            raw = (raw[:m.start()] + raw[m.end():]).strip()
        seg = Segment(duration=dur)
        for part in re.split(r"\s*(?:\+|&|,|\band\b)\s*", raw):
            part = part.strip()
            if not part:
                continue
            word, _, arg = part.partition(" ")
            kind = ALIASES.get(word.lower())
            arg = arg.strip()
            if kind is None:
                raise ValueError(f"unknown camera move {word!r} in {script!r}")
            if kind == "slow":
                stretch *= float(arg) if arg else 1.5
                continue
            if kind == "fast":
                stretch /= float(arg) if arg else 1.5
                continue
            if kind == "orbit":
                seg.moves.append(Move("orbit", b=float(arg) if arg else settings.orbit * orbit_sign(settings, index)))
            elif kind == "zoom":
                if arg.lower() in ("in", ""):
                    seg.moves.append(Move("zoom", rel="in"))
                elif arg.lower() == "out":
                    seg.moves.append(Move("zoom", rel="out"))
                else:
                    a, b = _range_pair(arg)
                    seg.moves.append(Move("zoom", a=a, b=b))
            elif kind == "tilt":
                a, b = _num_pair(arg)
                seg.moves.append(Move("tilt", a=a, b=b))
            elif kind == "truck":
                seg.moves.append(Move("truck", b=parse_length(arg) if arg else 2000.0))
            elif kind == "rise":
                seg.moves.append(Move("rise", b=parse_length(arg) if arg else 1000.0))
            elif kind == "hold":
                seg.moves.append(Move("hold"))
        if seg.moves or seg.duration:
            segs.append(seg)
    if not segs:   # only modifiers were given -> default motion, stretched
        segs = parse_moves(None, settings, index).segments
    return MoveScript(segs, stretch)
