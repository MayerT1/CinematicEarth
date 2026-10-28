---
title: Flyover with GeoTIFF products
speed: slow
stop_duration: 8
orbit: 45
tilt: 60
max_part_seconds: 90
layers_dir: cinematicearth_layers   # converted .kmz files go here
# drive_dir: /content/drive/MyDrive/CinematicEarth   # Colab: save .kmz to Drive and link them into the .esp
---

# Stops (the flight path)
- Huntsville, AL | 34.7304, -86.5861, 190 | orbit 60 + zoom 8km>3km | note=NASA EarthRISE / UAH

# Products (GeoTIFFs -> KML overlays)
Format: `layer: <tif path | Drive link | drive:<id>> | 2d / 3d / both | fly | key=value ...`

`fly` adds a stop that frames and orbits the product, at this position in the flight.

- layer: Stage3_transformer_rh.tif | 3d fly | name=Canopy height (rh) | units=m | cmap=viridis | min_value=2
- layer: Stage3_transformer_rh.tif | 2d | name=Canopy height 2D | units=m | cmap=viridis | min_value=2 | opacity=0.8

- Santa Fe, NM | 35.6870, -105.9378, 2130
