import json
import sys
import types
import zipfile
import xml.dom.minidom

import numpy as np
import pytest

pd = pytest.importorskip("pandas")
pytest.importorskip("rasterio")
pytest.importorskip("matplotlib")

import cinematicearth as ce
from cinematicearth import gedi as G

BBOX = (-85.99, 35.127, -85.857, 35.236)   # Sewanee Domain extent


def test_aoi_bbox_and_contains():
    a = G.load_aoi(BBOX)
    assert a.bbox == BBOX
    inside = a.contains(np.array([-85.92, -86.5]), np.array([35.18, 35.18]))
    assert inside.tolist() == [True, False]
    assert G.load_aoi("-85.99,35.127,-85.857,35.236").bbox == BBOX


def test_l2b_h5_reader(tmp_path):
    h5py = pytest.importorskip("h5py")
    p = tmp_path / "GEDI02_B_test_subsetted.h5"
    n = 50
    with h5py.File(p, "w") as f:
        for b in ("BEAM0000", "BEAM0101"):
            g = f.create_group(b)
            g["geolocation/lat_lowestmode"] = np.linspace(35.13, 35.23, n)
            g["geolocation/lon_lowestmode"] = np.linspace(-85.98, -85.86, n)
            g["geolocation/delta_time"] = np.full(n, 1.5e8)        # 2022-10-03
            g["geolocation/degrade_flag"] = np.zeros(n, "uint8")
            g["geolocation/elev_lowestmode"] = np.full(n, 580.0)
            fhd = np.linspace(1.5, 3.5, n)
            fhd[0] = -9999
            g["fhd_normal"] = fhd
            g["cover"] = np.full(n, 0.8)
            g["pai"] = np.full(n, 3.0)
            g["rh100"] = np.full(n, 2500, "int16")                 # cm
            g["l2b_quality_flag"] = np.ones(n, "uint8")
            g["sensitivity"] = np.full(n, 0.97)
            g["shot_number"] = np.arange(n, dtype="uint64")
    df = G.read_l2b_h5(str(p), aoi=BBOX)
    assert len(df) > 0 and {"fhd_normal", "rh100", "canopy_height", "year"} <= set(df.columns)
    assert abs(df["rh100"].median() - 25.0) < 1e-6 and int(df["year"].iloc[0]) == 2022
    q = G.filter_l2b(df)
    assert np.isfinite(q["fhd_normal"]).all() and len(q) < len(df)


def test_sliderule_normalisation(monkeypatch):
    gpd = pytest.importorskip("geopandas")
    times = pd.to_datetime(["2021-06-01", "2021-06-01", "2022-07-01"])
    gdf = gpd.GeoDataFrame({"elevation_lm": [570.0, 575.0, 580.0], "elevation_hr": [600.0, 598.0, 581.0],
                            "sensitivity": [0.95, 0.96, 0.97], "beam": [0, 0, 5], "flags": [2, 2, 2]},
                           geometry=gpd.points_from_xy([-85.92, -85.91, -85.90], [35.18, 35.181, 35.182]),
                           index=pd.Index(times, name="time"), crs="EPSG:7912")
    fake_sr = types.SimpleNamespace(init=lambda **k: True)
    fake_gedi = types.SimpleNamespace(gedi02ap=lambda parms: gdf, gedi04ap=lambda parms: gdf)
    pkg = types.ModuleType("sliderule")
    pkg.sliderule, pkg.gedi = fake_sr, fake_gedi
    monkeypatch.setitem(sys.modules, "sliderule", pkg)
    monkeypatch.setattr(G, "_SR_READY", False)
    df = G.sliderule_gedi(BBOX, "l2a", t0="2019-01-01")
    assert list(df["canopy_height"].round(1)) == [30.0, 23.0, 1.0]
    assert {"elev_ground", "elev_top", "lat", "lon", "year"} <= set(df.columns)
    with pytest.raises(ValueError):
        G.sliderule_gedi(BBOX, "l2b")


def test_kmz_outputs(tmp_path):
    df = G.synthetic_shots(BBOX)
    gl = G.GediLayer(aoi=",".join(map(str, BBOX)), source="synthetic", product="l2b",
                     viz="columns,curtains,grid2d,grid3d", height="rh100", by="year")
    files, info = G.gedi_kmz(df, gl, str(tmp_path))
    assert len(files) == 4 * len(info["years"]) and info["exaggeration"] > 1
    for f in files:
        k = zipfile.ZipFile(f).read("doc.kml").decode()
        xml.dom.minidom.parseString(k)
    col = [f for f in files if f.endswith("_columns.kmz")][0]
    k = zipfile.ZipFile(col).read("doc.kml").decode()
    assert "<extrude>1</extrude>" in k and "relativeToGround" in k


def test_gedi_line_and_build(tmp_path):
    md = f"""---
title: t
layers_dir: {tmp_path}/lay
---
- Huntsville, AL | 34.7304, -86.5861, 190
- gedi: {",".join(map(str, BBOX))} | source=synthetic | l2b | columns curtains | height=rh100 | fly | name=Sewanee GEDI
- Santa Fe, NM | 35.687, -105.94, 2130
"""
    s, st = ce.load(md)
    gl = s.layers[0]
    assert isinstance(gl, G.GediLayer) and gl.viz == "columns,curtains" and gl.fly and gl.product == "l2b"
    plan = ce.build(md, out=str(tmp_path / "f.esp"), verbose=False)
    w = [x for x in plan.stop_windows() if x["name"] == "Sewanee GEDI"][0]
    assert 35.12 < w["lat"] < 35.24 and w["elev"] > 400        # framed on the AOI, at ground elevation
    pj = json.load(open(str(tmp_path / "f.plan.json")))
    assert pj["layers"][0]["mode"] == "gedi:columns,curtains"
