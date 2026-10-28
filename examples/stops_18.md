---
title: 36-stop flyover
speed: slow          # glacial | slow | medium | fast (peak on-screen speed for transits)
stop_duration: 8     # seconds circling each city
orbit: 45            # slow 45-degree orbit around each city
tilt: 60             # oblique 3D view (0 = straight down, 90 = horizon)
range_start: 7000    # m from the city when the orbit starts
range_end: 3500      # pull in to this by the end of the orbit
glide_km: 150        # shorter hops stay low and fly forward; longer hops arc up
fps: 30
max_part_seconds: 90 # split into ~90 s Earth Studio projects
# duration: 240      # uncomment to force a total length; transits are re-paced to fit
---

# Stops
Format: `name | lat, lon, ground elevation (m) | camera moves (optional) | key=value (optional)`

- New Orleans, LA           | 29.9511, -90.0715, 2
- Detroit, MI               | 42.3314, -83.0458, 183
- Toronto, Canada           | 43.6532, -79.3832, 76
- Mexico City, Mexico       | 19.4326, -99.1332, 2240
- Guatemala City, Guatemala | 14.6349, -90.5069, 1500
- San José, Costa Rica      | 9.9281, -84.0907, 1172
- Bogotá, Colombia          | 4.7110, -74.0721, 2640
- Lima, Peru                | -12.0464, -77.0428, 154
- La Paz, Bolivia           | -16.4897, -68.1193, 3640
- Santiago, Chile           | -33.4489, -70.6693, 570
- Buenos Aires, Argentina   | -34.6037, -58.3816, 25
- Montevideo, Uruguay       | -34.9011, -56.1645, 43
- São Paulo, Brazil         | -23.5505, -46.6333, 760
- Rio de Janeiro, Brazil    | -22.9068, -43.1729, 11
- Dakar, Senegal            | 14.7167, -17.4677, 22
- Accra, Ghana              | 5.6037, -0.1870, 61
- Addis Ababa, Ethiopia     | 8.9806, 38.7578, 2355
- Seoul, South Korea        | 37.5665, 126.9780, 38
