import json
import os
import re
import xml.dom.minidom
import zipfile

import numpy as np
import pytest

rasterio = pytest.importorskip("rasterio")
pytest.importorskip("matplotlib")
pytest.importorskip("PIL")

import cinematicearth as ce
from cinematicearth.layers import Layer, convert_layer


@pytest.fixture(scope="module")
def chm(tmp_path_factory):
    """Synthetic canopy-height GeoTIFF in UTM 16N (near Huntsville), with nodata."""
    from rasterio.transform import from_origin
    H, W = 200, 250
    y, x = np.mgrid[0:H, 0:W]
    a = (25 + 12 * np.sin(x / 19) * np.cos(y / 15)).astype("float32")
    a[(x - 125) ** 2 / 60 ** 2 + (y - 100) ** 2 / 20 ** 2 < 1] = 0.5
    a[:10, :30] = -9999
    p = tmp_path_factory.mktemp("tif") / "chm.tif"
    with rasterio.open(p, "w", driver="GTiff", height=H, width=W, count=1, dtype="float32",
                       crs="EPSG:32616", transform=from_origin(530000, 3850000, 30, 30), nodata=-9999) as ds:
        ds.write(a, 1)
    return str(p)


def _kml(kmz):
    z = zipfile.ZipFile(kmz)
    k = z.read("doc.kml").decode()
    xml.dom.minidom.parseString(k)
    return k, z.namelist()


def test_2d_ground_overlay(chm, tmp_path):
    r = convert_layer(Layer(chm, name="CHM", mode="2d", units="m", min_value=2), str(tmp_path), verbose=False)
    k, names = _kml(r.files[0])
    assert "<GroundOverlay>" in k and "overlay.png" in names and "legend.png" in names
    w, s, e, n = r.bounds
    assert -86.75 < w < e < -86.4 and 34.7 < s < n < 34.85     # reprojected from UTM to lon/lat
    assert 10 < r.vmax < 40


def test_3d_extruded(chm, tmp_path):
    r = convert_layer(Layer(chm, name="CHM", mode="3d", units="m", min_value=2, exaggeration=10),
                      str(tmp_path), verbose=False)
    k, names = _kml(r.files[0])
    assert "<extrude>1</extrude>" in k and "relativeToGround" in k
    hs = [float(c.split(",")[2]) for c in re.findall(r"-?\d+\.\d+,-?\d+\.\d+,\d+\.\d", k)]
    assert max(hs) <= r.vmax * 10 + 1 and min(hs) > 0
    assert r.n_polygons > 0 and r.exaggeration == 10


def test_3d_prisms_and_auto(chm, tmp_path):
    r = convert_layer(Layer(chm, mode="3d", style="prisms", max_cells=2000), str(tmp_path), verbose=False)
    assert r.exaggeration >= 1 and r.n_polygons <= 2000


def test_markdown_layers_and_fly_stop(chm, tmp_path):
    md = f"""---
title: t
layers_dir: {tmp_path}/layers
---
- Huntsville, AL | 34.7304, -86.5861, 190
- layer: {chm} | 3d fly | name=Canopy | units=m | min_value=2 | drive_id=1AbCdEfGhIjKlMnOpQrStUvWxYz0123
- {chm} | 2d | name=Canopy 2D
- Santa Fe, NM | 35.687, -105.94, 2130
"""
    s, st = ce.load(md)
    assert [l.mode for l in s.layers] == ["3d", "2d"]
    assert [x.name for x in st] == ["Huntsville, AL", "Canopy", "Santa Fe, NM"]
    out = str(tmp_path / "f.esp")
    plan = ce.build(md, out=out, verbose=False)
    w = [x for x in plan.stop_windows() if x["name"] == "Canopy"][0]
    assert abs(w["lat"] - plan.layers[0].center[0]) < 1e-9
    esp = json.load(open(plan.esp_files[0]))
    kmls = esp["scenes"][0]["world"]["kmls"]
    assert kmls[0]["url"] == "/studio/api/files/1AbCdEfGhIjKlMnOpQrStUvWxYz0123"
    pj = json.load(open(str(tmp_path / "f.plan.json")))
    assert len(pj["layers"]) == 2 and "layers" not in pj["settings"]


def test_layer_line_parsing():
    from cinematicearth.io import layer_from_any
    l = layer_from_any("- https://drive.google.com/file/d/13rZJHR4rkurJYNOFUc1cGhcOTl2ycXrV/view?usp=drive_link"
                       " | both prisms | name=Stage 3 rh | exaggeration=8x | levels=20 | nolegend")
    assert l.mode == "both" and l.style == "prisms" and l.name == "Stage 3 rh"
    assert l.exaggeration == 8.0 and l.levels == 20 and l.legend is False
