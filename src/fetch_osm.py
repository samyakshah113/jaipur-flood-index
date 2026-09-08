"""
fetch_osm.py — download Jaipur's drains, roads and buildings from OpenStreetMap.

WHY OPENSTREETMAP
The Jaipur Municipal Corporation does not publish its stormwater drainage network as
open data. OpenStreetMap does have a lot of it, because local volunteers have mapped it.
It is incomplete and unevenly surveyed, and you must say so — but it is the best openly
available picture of the city's drainage, and it is free.

BE HONEST ABOUT THIS LIMITATION. "OSM drainage coverage is uneven, so absence of a
mapped drain does not prove absence of a real drain" is exactly the kind of sentence
that makes a reviewer trust the rest of your work.

HOW OVERPASS WORKS
Overpass is a query language for OpenStreetMap. You describe the features you want and
the box to search in, and it returns them as JSON. Think of it as SQL for the map.
"""

import time

import requests

from . import config


def _run_overpass_query(query, verbose=True):
    """
    Send a query to Overpass, trying each mirror until one answers.

    The main Overpass server is free and heavily used, so it sometimes returns
    "429 Too Many Requests" or simply times out. Falling back to a mirror makes the
    pipeline reliable instead of flaky — the difference between a project that works
    when someone else runs it and one that does not.
    """
    last_error = None

    for mirror in config.OVERPASS_MIRRORS:
        try:
            if verbose:
                print(f"  querying {mirror.split('/')[2]} ...", end=" ", flush=True)

            response = requests.post(mirror, data={"data": query}, timeout=180)

            if response.status_code == 200:
                if verbose:
                    print("ok")
                return response.json()

            if response.status_code == 429:
                if verbose:
                    print("rate limited, waiting")
                time.sleep(10)
                continue

            if verbose:
                print(f"HTTP {response.status_code}")

        except requests.RequestException as error:
            last_error = error
            if verbose:
                print("failed")
            continue

    raise RuntimeError(
        f"Every Overpass mirror failed. Last error: {last_error}. "
        "This is usually temporary — wait a few minutes and run it again."
    )


def _bbox_string(study_area=None):
    """
    Overpass wants bounding boxes as 'south,west,north,east'.

    That ordering is not the one most people expect (it is not 'min_lon, min_lat').
    Getting it wrong silently returns data for the wrong part of the world, so it is
    worth having one function that does it correctly rather than typing it out repeatedly.
    """
    area = study_area or config.STUDY_AREA
    return f"{area['min_lat']},{area['min_lon']},{area['max_lat']},{area['max_lon']}"


# ----------------------------------------------------------------------------
# DRAINAGE NETWORK
# ----------------------------------------------------------------------------
def fetch_drainage(study_area=None, verbose=True):
    """
    Get every mapped drain, canal, stream and river in the study area.

    For Jaipur this should pick up the Dravyavati river corridor (the old Amanishah
    nala, redeveloped as a channel) plus assorted smaller nalas and municipal drains.

    The tags we ask for:
      waterway=drain   — a purpose-built stormwater or wastewater drain
      waterway=ditch   — a smaller unlined channel
      waterway=stream  — a natural watercourse
      waterway=river   — a large natural watercourse
      waterway=canal   — an engineered channel
    """
    query = f"""
    [out:json][timeout:180];
    (
      way["waterway"~"drain|ditch|stream|river|canal"]({_bbox_string(study_area)});
    );
    out geom;
    """

    if verbose:
        print("Fetching drainage network from OpenStreetMap")

    data = _run_overpass_query(query, verbose)

    drains = []
    for element in data.get("elements", []):
        # 'geometry' is the list of points making up the line. Occasionally an element
        # comes back without it; skipping those is safer than crashing.
        if "geometry" not in element:
            continue

        drains.append({
            "type": element.get("tags", {}).get("waterway", "unknown"),
            "name": element.get("tags", {}).get("name", ""),
            "points": [(point["lat"], point["lon"]) for point in element["geometry"]],
        })

    if verbose:
        print(f"  found {len(drains)} drainage features")

    return drains


# ----------------------------------------------------------------------------
# ROAD NETWORK
# ----------------------------------------------------------------------------
def fetch_roads(study_area=None, verbose=True):
    """
    Get the road network, keeping each road's surface tag.

    Roads matter twice over in this project:
      1. Road density is a decent proxy for how built-up and populated an area is.
      2. Surface type is a proxy for municipal investment. Areas with a high share of
         unpaved or track-grade roads tend to be the areas with weaker drainage,
         weaker services, and less political weight when budgets are allocated.

    That second point is the honest, data-grounded way to get at the "low-income
    neighbourhoods" part of the research question without pretending to have census
    income data that is not publicly available at this resolution.
    """
    query = f"""
    [out:json][timeout:180];
    (
      way["highway"]({_bbox_string(study_area)});
    );
    out geom;
    """

    if verbose:
        print("Fetching road network from OpenStreetMap")

    data = _run_overpass_query(query, verbose)

    roads = []
    for element in data.get("elements", []):
        if "geometry" not in element:
            continue

        tags = element.get("tags", {})
        roads.append({
            "highway": tags.get("highway", ""),
            "surface": tags.get("surface", ""),   # empty means simply not surveyed
            "name": tags.get("name", ""),
            "points": [(point["lat"], point["lon"]) for point in element["geometry"]],
        })

    if verbose:
        print(f"  found {len(roads)} road segments")

    return roads


# ----------------------------------------------------------------------------
# BUILDINGS
# ----------------------------------------------------------------------------
def fetch_buildings(study_area=None, verbose=True):
    """
    Get building footprints.

    We use these two ways:
      - Density: more buildings = more people and property exposed to a flood.
      - Footprint SIZE: this is the interesting one. Dense clusters of very small
        footprints are characteristic of informal and low-income settlement, while
        large footprints indicate planned housing, commercial or institutional
        development. It is a proxy, not a measurement of income — but it is a
        published, widely used one in urban remote sensing.

    NOTE ON VOLUME: Jaipur has a lot of mapped buildings and this query can return
    tens of megabytes. `out center;` asks Overpass for just the CENTRE POINT of each
    building rather than its full outline, which cuts the download dramatically. We
    lose exact footprint shape but keep position, which is all we need for density.
    """
    query = f"""
    [out:json][timeout:300];
    (
      way["building"]({_bbox_string(study_area)});
    );
    out center;
    """

    if verbose:
        print("Fetching buildings from OpenStreetMap (this is the slow one)")

    data = _run_overpass_query(query, verbose)

    buildings = []
    for element in data.get("elements", []):
        centre = element.get("center")
        if centre is None:
            continue

        tags = element.get("tags", {})
        buildings.append({
            "lat": centre["lat"],
            "lon": centre["lon"],
            "building_type": tags.get("building", "yes"),
            "levels": tags.get("building:levels", ""),
        })

    if verbose:
        print(f"  found {len(buildings)} buildings")

    return buildings


# ----------------------------------------------------------------------------
# CRITICAL FACILITIES
# ----------------------------------------------------------------------------
def fetch_amenities(study_area=None, verbose=True):
    """
    Get schools, hospitals, clinics and markets.

    These carry weight beyond their footprint. A flooded street is a nuisance; a
    flooded primary school closes for a week and a flooded clinic cuts off care during
    exactly the period when waterborne illness spikes. Emergency planners prioritise
    these, so a risk index that ignores them is not much use to the people it is for.
    """
    query = f"""
    [out:json][timeout:180];
    (
      node["amenity"~"school|hospital|clinic|doctors|marketplace|pharmacy"]({_bbox_string(study_area)});
      way["amenity"~"school|hospital|clinic|doctors|marketplace|pharmacy"]({_bbox_string(study_area)});
    );
    out center;
    """

    if verbose:
        print("Fetching critical facilities from OpenStreetMap")

    data = _run_overpass_query(query, verbose)

    amenities = []
    for element in data.get("elements", []):
        # Nodes carry lat/lon directly; ways carry a 'center' instead.
        if "lat" in element:
            lat, lon = element["lat"], element["lon"]
        elif "center" in element:
            lat, lon = element["center"]["lat"], element["center"]["lon"]
        else:
            continue

        amenities.append({
            "lat": lat,
            "lon": lon,
            "amenity": element.get("tags", {}).get("amenity", ""),
            "name": element.get("tags", {}).get("name", ""),
        })

    if verbose:
        print(f"  found {len(amenities)} critical facilities")

    return amenities


def fetch_all_osm(study_area=None, verbose=True):
    """
    Fetch every OSM layer in one go, pausing between queries.

    The sleep is not laziness — Overpass is a free service run on donated hardware and
    firing four heavy queries back to back is how you get your IP rate-limited.
    """
    layers = {}

    layers["drains"] = fetch_drainage(study_area, verbose)
    time.sleep(3)

    layers["roads"] = fetch_roads(study_area, verbose)
    time.sleep(3)

    layers["buildings"] = fetch_buildings(study_area, verbose)
    time.sleep(3)

    layers["amenities"] = fetch_amenities(study_area, verbose)

    return layers
