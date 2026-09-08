"""
demo.py — a synthetic stand-in for the real data, so the pipeline can be tested offline.

WHAT THIS IS FOR
The real pipeline downloads elevation tiles and OpenStreetMap data over the internet.
That is slow, and it fails if a server is down or you are on a restricted network. So
this file manufactures a small fake city with the same STRUCTURE as the real data: an
elevation array, some drain lines, some roads, some buildings.

WHAT THIS IS NOT FOR
The output is not Jaipur and must never be presented as a result. Every map produced
from it carries a "SYNTHETIC" watermark for exactly that reason. Its purpose is to
prove the machinery works — that the terrain maths, the rasterising, the scoring and
the map rendering all connect correctly — so that when you plug in real data you know
any problem is in the data, not the code.

Building a fake dataset to test a pipeline is standard professional practice. It is
called a fixture, and it is how you develop without hammering someone else's free API.
"""

import numpy as np

from . import config


def synthetic_dem(shape=(360, 360), seed=7):
    """
    Generate a plausible-looking urban terrain: a broad slope, a river valley cutting
    across it, some rolling variation, and a few enclosed hollows.

    The point is that we KNOW where the low ground is, so we can check that the
    pipeline finds it.
    """
    rng = np.random.default_rng(seed)
    rows, cols = shape

    y, x = np.mgrid[0:rows, 0:cols]

    # A regional slope: high in the north-west, falling towards the south-east.
    # Jaipur really does sit on ground that drains broadly southward, so this is not
    # arbitrary, but the numbers are invented.
    elevation = 460.0 - (y / rows) * 25.0 - (x / cols) * 10.0

    # A river valley running roughly north-south, meandering slightly.
    valley_centre = cols * 0.45 + np.sin(y / rows * 6) * cols * 0.08
    distance_from_valley = np.abs(x - valley_centre)
    # A Gaussian trench: deepest at the centre line, fading out to either side.
    elevation -= 12.0 * np.exp(-(distance_from_valley ** 2) / (2 * (cols * 0.04) ** 2))

    # Rolling variation at a couple of scales, so the terrain is not unnaturally smooth.
    for wavelength, amplitude in [(90, 3.0), (35, 1.2), (15, 0.5)]:
        elevation += amplitude * np.sin(x / wavelength * 2 * np.pi + rng.random() * 6)
        elevation += amplitude * np.cos(y / wavelength * 2 * np.pi + rng.random() * 6)

    # A handful of enclosed hollows — the fake equivalent of a low-lying colony with
    # no outlet. These are what the depression-filling step should light up.
    for _ in range(6):
        cy, cx = rng.integers(40, rows - 40), rng.integers(40, cols - 40)
        radius = rng.integers(12, 28)
        depth = rng.uniform(1.5, 4.0)
        hollow = np.exp(-(((y - cy) ** 2 + (x - cx) ** 2) / (2 * radius ** 2)))
        elevation -= depth * hollow

    # A little measurement noise, as any real elevation dataset would have.
    elevation += rng.normal(0, 0.15, size=shape)

    return elevation


def synthetic_osm(study_area=None, seed=7):
    """
    Manufacture drain, road, building and facility layers with realistic geography:
    denser in the centre, sparser at the edges, with a main drainage channel.
    """
    study_area = study_area or config.STUDY_AREA
    rng = np.random.default_rng(seed)

    lat_min, lat_max = study_area["min_lat"], study_area["max_lat"]
    lon_min, lon_max = study_area["min_lon"], study_area["max_lon"]
    centre_lat = (lat_min + lat_max) / 2
    centre_lon = (lon_min + lon_max) / 2

    # --- drains: one main channel plus tributaries ---------------------------
    drains = []

    main_channel = []
    for i in range(40):
        fraction = i / 39
        lat = lat_max - fraction * (lat_max - lat_min)
        lon = lon_min + (0.45 + 0.06 * np.sin(fraction * 6)) * (lon_max - lon_min)
        main_channel.append((lat, lon))
    drains.append({"type": "river", "name": "Synthetic main channel", "points": main_channel})

    for _ in range(14):
        start_index = rng.integers(3, 36)
        start = main_channel[start_index]
        direction = rng.choice([-1, 1])
        tributary = [start]
        for step in range(1, rng.integers(4, 10)):
            tributary.append((
                start[0] + rng.normal(0, 0.002) * step,
                start[1] + direction * 0.004 * step + rng.normal(0, 0.001),
            ))
        drains.append({"type": "drain", "name": "", "points": tributary})

    # --- roads: a rough grid, denser near the centre --------------------------
    roads = []
    for _ in range(260):
        # Cluster road midpoints towards the city centre.
        lat = np.clip(rng.normal(centre_lat, (lat_max - lat_min) * 0.22), lat_min, lat_max)
        lon = np.clip(rng.normal(centre_lon, (lon_max - lon_min) * 0.22), lon_min, lon_max)

        horizontal = rng.random() < 0.5
        length = rng.uniform(0.004, 0.02)

        if horizontal:
            points = [(lat, lon), (lat + rng.normal(0, 0.0008), lon + length)]
        else:
            points = [(lat, lon), (lat + length, lon + rng.normal(0, 0.0008))]

        # Outer areas are more likely to have unpaved roads, mimicking the real pattern
        # where peripheral and informal settlements have weaker infrastructure.
        distance_from_centre = np.hypot(lat - centre_lat, lon - centre_lon)
        unpaved_chance = min(0.6, distance_from_centre * 22)
        is_unpaved = rng.random() < unpaved_chance

        roads.append({
            "highway": "residential" if not is_unpaved else "track",
            "surface": "unpaved" if is_unpaved else "asphalt",
            "name": "",
            "points": points,
        })

    # --- buildings: heavily clustered -----------------------------------------
    buildings = []
    n_clusters = 40
    for _ in range(n_clusters):
        cluster_lat = np.clip(rng.normal(centre_lat, (lat_max - lat_min) * 0.25), lat_min, lat_max)
        cluster_lon = np.clip(rng.normal(centre_lon, (lon_max - lon_min) * 0.25), lon_min, lon_max)
        spread = rng.uniform(0.002, 0.008)

        for _ in range(rng.integers(40, 200)):
            buildings.append({
                "lat": float(np.clip(rng.normal(cluster_lat, spread), lat_min, lat_max)),
                "lon": float(np.clip(rng.normal(cluster_lon, spread), lon_min, lon_max)),
                "building_type": "yes",
                "levels": "",
            })

    # --- critical facilities ---------------------------------------------------
    amenities = []
    for _ in range(90):
        amenities.append({
            "lat": float(np.clip(rng.normal(centre_lat, (lat_max - lat_min) * 0.25), lat_min, lat_max)),
            "lon": float(np.clip(rng.normal(centre_lon, (lon_max - lon_min) * 0.25), lon_min, lon_max)),
            "amenity": str(rng.choice(["school", "clinic", "marketplace", "pharmacy"])),
            "name": "",
        })

    return {
        "drains": drains,
        "roads": roads,
        "buildings": buildings,
        "amenities": amenities,
    }


def synthetic_rainfall_summary():
    """
    Stand-in rainfall statistics, in the same shape the real fetch returns.

    The numbers are in the right ballpark for a semi-arid north-Indian city, but they
    are invented. The real function pulls measured values.
    """
    return {
        "mean_annual_mm": 560.0,
        "wettest_year": 2024,
        "wettest_year_mm": 980.0,
        "driest_year": 2018,
        "driest_year_mm": 310.0,
        "monsoon_share": 0.86,
        "rain_days_per_year": 34.0,
        "design_storm_mm": 74.0,
        "max_daily_mm": 190.0,
        "biggest_days": None,
        "SYNTHETIC": True,
    }


def synthetic_observations(table, grid, n=44, seed=11):
    """
    Fake ground-truth points, used ONLY to prove the validation code runs.

    IMPORTANT: these are generated by peeking at the model's own hazard score and
    adding noise. That means the AUC computed from them is meaningless — the answer
    was constructed from the question. It tests that the plumbing works, nothing more.
    Real validation requires real observations you collected yourself.
    """
    rng = np.random.default_rng(seed)
    urban = table[table["is_urban"]].copy()

    if len(urban) < n:
        n = len(urban)

    # Sample across the whole range so we get both flooded and dry examples.
    sample = urban.sample(n=n, random_state=seed)

    rows = []
    for i, (_, cell) in enumerate(sample.iterrows()):
        # Deliberately noisy so the fake AUC is not an implausible 1.00.
        probability = cell["hazard_score"] * 0.6 + rng.random() * 0.4
        rows.append({
            "name": f"Synthetic point {i + 1}",
            "lat": cell["lat"] + rng.normal(0, 0.0005),
            "lon": cell["lon"] + rng.normal(0, 0.0005),
            "flooded": int(probability > 0.5),
            "source": "SYNTHETIC — not a real observation",
            "date": "",
        })

    import pandas as pd
    return pd.DataFrame(rows)
