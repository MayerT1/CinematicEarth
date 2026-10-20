import json
import math
import os
import xml.dom.minidom

import numpy as np
import pytest

import cinematicearth as ce
from cinematicearth.model import parse_moves, Settings
from cinematicearth.simulate import centering_error

HERE = os.path.dirname(__file__)
EX = os.path.join(HERE, "..", "examples", "stops_18.md")


@pytest.fixture(scope="module")
def plan18():
    s, st = ce.load(EX)
    return ce.plan_flyover(st, s)


def test_parse_moves():
    ms = parse_moves("orbit 30 + zoom 9km>5km @5s; orbit -30 + tilt 60>72 + zoom 2.5km; hold 1s; slow 2", Settings())
    assert ms.stretch == 2
    assert len(ms.segments) == 3
    assert ms.segments[0].duration == 5
    k = [m.kind for m in ms.segments[1].moves]
    assert k == ["orbit", "tilt", "zoom"]
    assert ms.segments[0].moves[1].a == 9000 and ms.segments[0].moves[1].b == 5000
    assert ms.segments[1].moves[0].b == -30


def test_default_moves():
    ms = parse_moves(None, Settings(orbit=45))
    assert ms.segments[0].moves[0].kind == "orbit" and ms.segments[0].moves[0].b == 45


def test_load_markdown():
    s, st = ce.load(EX)
    assert len(st) == 18
    assert st[0].name == "Coeur d'Alene, ID" and st[0].elev == 670
    hv = [x for x in st if x.name.startswith("Huntsville")][0]
    assert hv.note == "NASA EarthRISE / UAH" and "orbit 60" in hv.moves
    assert s.speed == "slow" and s.orbit == 45 and s.glide_km == 150


def test_load_inline_and_lists(tmp_path):
    s, st = ce.load("- A | 10, 20 | orbit 90\n- B (11.5, 21.5) | duration=4")
    assert st[0].lat == 10 and st[0].moves == "orbit 90" and st[1].lon == 21.5 and st[1].duration == 4
    _, st = ce.load([("X", 1, 2), {"name": "Y", "lat": 3, "lon": 4, "moves": ["orbit 20", "hold 1s"]}])
    assert st[1].moves == "orbit 20; hold 1s"
    p = tmp_path / "s.csv"
    p.write_text("name,lat,lon,moves\nA,1,2,orbit 30\nB,3,4,\n")
    _, st = ce.load(str(p))
    assert st[0].moves == "orbit 30" and st[1].moves is None
    j = tmp_path / "s.json"
    j.write_text(json.dumps({"settings": {"speed": "fast"}, "stops": [{"name": "A", "lat": 1, "lon": 2}]}))
    s, st = ce.load(str(j))
    assert s.speed == "fast" and st[0].lat == 1


def test_esp_roundtrip(plan18):
    esp = ce.build_esp(plan18)
    t, cam, rot = ce.decode_tracks(esp)
    kt, kcam, krot, _ = plan18.keyframes()
    assert np.allclose(cam, kcam, atol=1e-6)
    assert np.allclose(rot, krot, atol=1e-6)
    assert esp["settings"]["duration"] == plan18.frames


def test_light_projects(plan18):
    """Earth Studio chokes on thousands of keyframes: keep projects light."""
    kt, _, krot, _ = plan18.keyframes()
    assert len(kt) < 900
    parts = plan18.parts()
    assert len(parts) > 1
    for k in range(len(parts)):
        esp = ce.build_esp(plan18, part=k)
        t, cam, rot = ce.decode_tracks(esp)
        assert len(t) < 250
        assert np.abs(rot[:, 0]).max() < 400
        assert esp["settings"]["duration"] <= 90 * 30 + 1


def test_parts_join_seamlessly(plan18):
    parts = plan18.parts()
    for (a0, a1), (b0, b1) in zip(parts[:-1], parts[1:]):
        assert abs(a1 - b0) < 1e-9
        assert abs(round(a1 * 30) - a1 * 30) < 1e-6        # frame aligned
        _, ca, _, _ = plan18.keyframes(a0, a1)
        _, cb, _, _ = plan18.keyframes(b0, b1)
        assert np.allclose(ca[-1], cb[0], atol=1e-6)


def test_esp_time_range(plan18):
    esp = ce.build_esp(plan18, part=0)
    kf = esp["scenes"][0]["attributes"][0]["attributes"][0]["attributes"][0]["keyframes"]
    assert kf[0]["time"] == 0 and abs(kf[-1]["time"] - 1) < 1e-9


def test_city_locked_center(plan18):
    """Using Earth Studio-style linear interpolation of the written tracks,
    each city stays at screen centre for its entire stop."""
    esp = ce.build_esp(plan18)
    for name, mx, mean in centering_error(esp, plan18, step=0.1):
        assert mx < 3.0, (name, mx)


def test_pacing_limit(plan18):
    vmax = plan18.settings.vmax()
    for r in plan18.report:
        assert r["peak_v"] <= vmax * 1.08, r


def test_no_wild_jumps(plan18):
    lon = plan18.cam[:, 1]
    assert np.abs(np.diff(lon)).max() < 25        # no antimeridian smear
    pan = plan18.rot[:, 0]
    assert np.abs(np.diff(pan)).max() < 30


def test_orbit_sweep(plan18):
    """Default stop = 45 deg orbit, pulling in from range_start to range_end."""
    w = plan18.stop_windows()[1]
    v0, v1 = plan18.view_at(w["t_start"] + 1e-6), plan18.view_at(w["t_end"] - 1e-6)
    assert abs(abs(v1.heading - v0.heading) - 45) < 0.5   # alternating direction
    assert abs(v0.rng - 7000) < 50 and abs(v1.rng - 3500) < 50
    assert abs(v0.tilt - 60) < 0.5


def test_duration_fit():
    s, st = ce.load(EX, duration=420)
    p = ce.plan_flyover(st, s)
    assert abs(p.duration - 420) < 0.5


def test_cut_and_truck():
    s, st = ce.load("- A | 40, -100 | truck 2km + zoom 6km>4km\n- B | 41, 10 | transit=cut")
    p = ce.plan_flyover(st, s)
    assert any(pc.kind == "cut" for pc in p.pieces)
    assert p.to_json()["cuts"]


def test_kml(plan18, tmp_path):
    out = ce.write_kml(plan18, str(tmp_path / "t.kml"))
    xml.dom.minidom.parse(out)


def test_overlay_preview(plan18):
    pytest.importorskip("cv2")
    pytest.importorskip("PIL")
    from cinematicearth.overlay import preview_frame
    w = plan18.stop_windows()[0]
    fr = preview_frame(plan18, w["t_start"] + 3, 960, 540)
    assert fr.shape == (540, 960, 3) and fr.std() > 1
