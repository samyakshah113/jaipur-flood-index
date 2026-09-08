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


def _validate_overpass_response(response):
    """
    Decide whether an Overpass reply is actually usable.

    A 200 status is NOT sufficient, and assuming it was is what broke this pipeline.
    Three separate ways a request can fail while looking fine:

      1. The body is an HTML error page, not JSON. Calling .json() on it raises a
         confusing JSONDecodeError about "line 1 column 1".
      2. The body is valid JSON but carries a "remark" field saying the query timed
         out server-side. Elements come back as an empty list. Everything downstream
         then works perfectly on no data.
      3. The status is 429 (rate limited) or 406, which older versions of this code
         quietly skipped past.

    Returns the parsed JSON, or raises ValueError describing what went wrong.
    """
    if response.status_code != 200:
        raise ValueError(
            f"HTTP {response.status_code}: {response.text[:200].strip()}"
        )

    content_type = response.headers.get("content-type", "")
    if "json" not in content_type.lower():
        raise ValueError(
            f"expected JSON but got {content_type!r}: {response.text[:200].strip()}"
        )

    try:
        data = response.json()
    except ValueError as error:
        raise ValueError(f"body was not valid JSON: {error}")

    # Overpass reports server-side timeouts here, with HTTP 200 and no elements.
    if "remark" in data:
        raise ValueError(f"Overpass remark: {data['remark']}")

    return data


def _run_overpass_query(query, verbose=True, expect_results=True):
    """
    Send a query to Overpass, trying each mirror until one gives a valid answer.

    Every request identifies itself via config.HTTP_HEADERS. Without that, mirrors
    return 406 or 429 and the pipeline ends up with no data at all.

    expect_results=True treats an EMPTY answer as a failure worth retrying elsewhere.
    That is not paranoia: a regional Overpass instance queried outside its region
    returns 200, valid JSON, no remark, and zero elements. Accepting that silently is
    exactly how this project first produced a blank map of Jaipur and called it a
    success. If a mirror has no data for the study area, move on to one that does.
    """
    problems = []

    for mirror in config.OVERPASS_MIRRORS:
        host = mirror.split("/")[2]
        try:
            if verbose:
                print(f"  querying {host} ...", end=" ", flush=True)

            response = requests.post(
                mirror,
                data={"data": query},
                headers=config.HTTP_HEADERS,
                timeout=300,
            )

            data = _validate_overpass_response(response)
            n_elements = len(data.get("elements", []))

            if expect_results and n_elements == 0:
                raise ValueError(
                    "returned 0 elements - this mirror probably does not hold data "
                    "for the study area"
                )

            if verbose:
                print(f"ok ({n_elements} elements)")
            return data

        except (requests.RequestException, ValueError) as error:
            problems.append(f"{host}: {error}")
            if verbose:
                print(f"failed - {str(error)[:90]}")

            # Rate limiting eases if you actually wait, so give it a moment before
            # hammering the next mirror.
            if "429" in str(error) or "rate" in str(error).lower():
                time.sleep(5)
            continue

    raise RuntimeError(
        "Every Overpass mirror refused this query.\n  "
        + "\n  ".join(problems)
        + "\n\nIf these are timeouts, the study area may be too large for one "
        "request. If they mention User-Agent, check config.USER_AGENT is being sent."
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

    # FAIL LOUDLY ON AN EMPTY RESULT.
    # The first version of this pipeline returned empty layers without complaint and
    # went on to render a blank map, reporting success the whole way. Silence is the
    # worst possible response to having no data: every later stage "worked", and the
    # only symptom was an unusually small output file.
    if len(layers["roads"]) == 0 and len(layers["buildings"]) == 0:
        raise RuntimeError(
            "OpenStreetMap returned no roads and no buildings for the study area.\n"
            "Jaipur has tens of thousands of both, so this is a fetch failure, not a\n"
            "real result. Continuing would produce an empty map that looks fine.\n"
            "Check the study area coordinates in config.py and the messages above."
        )

    if verbose:
        print("\n  sanity check passed: OSM returned real data")

    return layers
