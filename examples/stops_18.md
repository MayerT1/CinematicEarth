---
title: 18-stop flyover
speed: slow          # glacial | slow | medium | fast  (peak on-screen speed for transits)
stop_duration: 8     # seconds circling each city
orbit: 45            # slow 45-degree orbit around each city
tilt: 60             # oblique 3D view (0 = straight down, 90 = horizon)
range_start: 7000    # m from the city when the orbit starts...
range_end: 3500      # ...pulling in to this by the end of the orbit
glide_km: 150        # shorter hops stay low and fly forward; longer hops arc up
fps: 30
max_part_seconds: 90 # split into ~90 s Earth Studio projects (light enough for the browser)
# duration: 240      # uncomment to force a total length; transits are re-paced to fit
---

# Stops
Format: `name | lat, lon, ground elevation (m) | camera moves (optional) | key=value (optional)`

Leave the moves blank to get the default: `orbit 45 + zoom 7km>3.5km` over `stop_duration`.

- Coeur d'Alene, ID       | 47.6777, -116.7805, 670
- Deer Park, WA           | 47.9543, -117.4769, 645
- Winlock, WA             | 46.4910, -122.9379, 100
- Ellensburg, WA          | 46.9965, -120.5478, 470
- Portland, OR            | 45.5152, -122.6784, 50   | orbit 60 + zoom 8km>3km + tilt 58>66
- Cathlamet, WA           | 46.2032, -123.3832, 20
- McKenzie Bridge, OR     | 44.1754, -122.1606, 420
- Lyle, WA                | 45.6962, -121.2862, 60   | truck 3km + zoom 6km>4km @5s; orbit 30
- Springfield, IL         | 39.7817, -89.6501, 180
- Santa Fe, NM            | 35.6870, -105.9378, 2130
- Fort Collins, CO        | 40.5853, -105.0844, 1525
- Huntsville, AL          | 34.7304, -86.5861, 190   | orbit 60 + zoom 8km>3km; hold 1s | note=NASA EarthRISE / UAH
- Bangkok, Thailand       | 13.7563, 100.5018, 5
- Naypyidaw, Myanmar      | 19.7633, 96.0785, 115
- Kathmandu, Nepal        | 27.7172, 85.3240, 1400   | orbit 45 + tilt 55>68 + zoom 9km>4km
- Dhaka, Bangladesh       | 23.8103, 90.4125, 10
- Thimphu, Bhutan         | 27.4728, 89.6390, 2330   | orbit 45 + zoom 8km>4.5km
- Enschede, Netherlands   | 52.2215, 6.8937, 40      | orbit 60 + zoom 7km>3km; hold 1.5s
