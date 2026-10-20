"""KML tour (Google Earth Pro / Web) from the same camera plan."""
from __future__ import annotations

from xml.sax.saxutils import escape


def build_kml(plan) -> str:
    steps, prev = [], 0.0
    for t, (lat, lon, alt), (h, tl) in zip(plan.times, plan.cam, plan.rot):
        dur = max(float(t) - prev, 1e-3)
        prev = float(t)
        steps.append(
            f"<gx:FlyTo><gx:duration>{dur:.3f}</gx:duration><gx:flyToMode>smooth</gx:flyToMode>"
            f"<Camera><longitude>{lon:.7f}</longitude><latitude>{lat:.7f}</latitude>"
            f"<altitude>{alt:.1f}</altitude><heading>{((h + 180) % 360) - 180:.3f}</heading>"
            f"<tilt>{tl:.3f}</tilt><roll>0</roll><altitudeMode>absolute</altitudeMode></Camera></gx:FlyTo>")
    pins = "".join(
        f"<Placemark><name>{escape(s.title)}</name>"
        f"<Point><coordinates>{s.lon},{s.lat},0</coordinates></Point></Placemark>"
        for s in plan.stops)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<kml xmlns="http://www.opengis.net/kml/2.2" xmlns:gx="http://www.google.com/kml/ext/2.2">\n'
            f"<Document><name>{escape(plan.settings.title)}</name>{pins}\n"
            f"<gx:Tour><name>{escape(plan.settings.title)} tour</name><gx:Playlist>"
            f"{''.join(steps)}</gx:Playlist></gx:Tour>\n</Document></kml>\n")


def write_kml(plan, path) -> str:
    with open(path, "w", encoding="utf-8") as f:
        f.write(build_kml(plan))
    return path
