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

THREE HARD-WON LESSONS, ALL FOUND BY THINGS GOING WRONG
  1. Send a real User-Agent. Without one, mirrors answer 406 or 429.
  2. Never trust an HTTP 200. It can carry an HTML error page, a server-side timeout
     notice, or a perfectly valid empty result from a mirror that has no data for your
     region.
  3. Ask for less at a time. A regex tag filter cannot use the tag index, so Overpass
     scans instead of looking up; and one request covering a whole city times out at
     the gateway. Exact tag matches, split across sub-areas, is dramatically cheaper.
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
      3. The status is 429 (rate limited), 406 (rejected) or 504 (gateway timeout),
         which older versions of this code quietly skipped past.

    Returns the parsed JSON, or raises ValueError describing what went wrong.
    """
    if response.status_code != 200:
        # Strip HTML tags out of error pages so the message stays readable.
        body = response.text[:150].replace("\n", " ").strip()
        raise ValueError(f"HTTP {response.status_code} ({body[:60]}...)")

    content_type = response.headers.get("content-type", "")
    if "json" not in content_type.lower():
        raise ValueError(f"expected JSON, got {content_type!r}")

    try:
        data = response.json()
    except ValueError as error:
        raise ValueError(f"body was not valid JSON: {error}")

    # Overpass reports server-side timeouts here, with HTTP 200 and no elements.
    if "remark" in data:
        raise ValueError(f"Overpass remark: {data['remark']}")

    return data


def _run_overpass_query(query, verbose=True, rounds=2):
    """
    Send a query to Overpass, trying each mirror until one gives a valid answer.

    Every request identifies itself via config.HTTP_HEADERS. Without that, mirrors
    return 406 or 429 and the pipeline ends up with no data at all.

    'rounds' controls how many times we work through the whole mirror list. A 504
    Gateway Timeout usually means the server is busy right now rather than broken, so
    it is worth waiting and coming back rather than giving up on the first pass.

    Note this does NOT reject an empty result any more. With the study area split into
    sub-areas (see _collect below), a single sub-area legitimately can contain no
    drains. Emptiness is now judged across the whole layer instead, where it actually
    means something.
    """
    problems = []

    for attempt in range(rounds):
        if attempt > 0:
            wait = 20 * attempt
            if verbose:
                print(f"    all mirrors busy, waiting {wait}s before retrying")
            time.sleep(wait)

        for mirror in config.OVERPASS_MIRRORS:
            host = mirror.split("/")[2]
            try:
                response = requests.post(
                    mirror,
                    data={"data": query},
                    headers=config.HTTP_HEADERS,
                    timeout=180,
                )
                return _validate_overpass_response(response)

            except (requests.RequestException, ValueError) as error:
                problems.append(f"{host}: {str(error)[:70]}")
                if "429" in str(error):
                    time.sleep(5)
                continue

    raise RuntimeError(
        "Every Overpass mirror refused this query, twice.\n  "
        + "\n  ".join(problems[-6:])
        + "\n\n504 or timeout means the servers are busy — wait a few minutes and run "
        "this cell again. If they mention User-Agent, check config.USER_AGENT is set."
    )


def _bbox_string(area):
    """
    Overpass wants bounding boxes as 'south,west,north,east'.

    That ordering is not the one most people expect (it is not 'min_lon, min_lat').
    Getting it wrong silently returns data for the wrong part of the world, so it is
    worth having one function that does it correctly rather than typing it out
    repeatedly.
    """
    return f"{area['min_lat']},{area['min_lon']},{area['max_lat']},{area['max_lon']}"


def _split_area(study_area, n):
    """
    Cut the study area into an n x n grid of smaller boxes.

    WHY BOTHER
    A single request covering all 26 x 26 km of Jaipur is enough work that the server
    gives up and returns 504 Gateway Timeout — which is what happens when Overpass is
    under load. Sixteen requests each covering a sixteenth of the area do the same
    total work, but no individual request is big enough to be killed.

    This is the standard way to stay inside a shared free service's limits: ask for
    less, more often, rather than asking for everything and hoping.
    """
    lat_min, lat_max = study_area["min_lat"], study_area["max_lat"]
    lon_min, lon_max = study_area["min_lon"], study_area["max_lon"]

    boxes = []
    for i in range(n):
        for j in range(n):
            boxes.append({
                "min_lat": lat_min + (lat_max - lat_min) * i / n,
                "max_lat": lat_min + (lat_max - lat_min) * (i + 1) / n,
                "min_lon": lon_min + (lon_max - lon_min) * j / n,
                "max_lon": lon_min + (lon_max - lon_min) * (j + 1) / n,
            })
    return boxes


def _collect(build_query, study_area, tiles_per_side, label, verbose=True):
    """
    Run one query per sub-area and merge the results, removing duplicates.

    WHY DEDUPLICATION IS ESSENTIAL
    A road that crosses a sub-area boundary is returned by BOTH queries covering it.
    Without removing duplicates, every boundary-crossing feature is counted twice —
    which would quietly inflate road density along a grid of invisible lines across
    your map, and those lines would look exactly like a real finding.

    OSM gives every element a stable id, so (type, id) identifies a feature uniquely.
    """
    boxes = _split_area(study_area, tiles_per_side)

    seen = set()
    elements = []
    duplicates = 0

    for k, box in enumerate(boxes, 1):
        if verbose:
            print(f"  {label}: area {k}/{len(boxes)} ...", end=" ", flush=True)

        data = _run_overpass_query(build_query(box), verbose)
        got = data.get("elements", [])

        for element in got:
            key = (element.get("type"), element.get("id"))
            if key in seen:
                duplicates += 1
                continue
            seen.add(key)
            elements.append(element)

        if verbose:
            print(f"{len(got)}")

        # Be a good citizen of a free shared service.
        if k < len(boxes):
            time.sleep(1)

    if verbose and duplicates:
        print(f"  {label}: removed {duplicates} duplicates from sub-area overlaps")

    return elements


# ----------------------------------------------------------------------------
# DRAINAGE NETWORK
# ----------------------------------------------------------------------------
def fetch_drainage(study_area=None, verbose=True):
    """
    Get every mapped drain, canal, stream and river in the study area.

    For Jaipur this should pick up the Dravyavati river corridor (the old Amanishah
    nala, redeveloped as a channel) plus assorted smaller nalas and municipal drains.

    NOTE ON THE QUERY SHAPE
    The obvious way to write this is one regex: way["waterway"~"drain|ditch|..."].
    That is much slower on the server, because a regex cannot use the tag index — the
    database has to look at every waterway and test it. Listing exact values instead
    lets Overpass do five fast index lookups. Same result, a fraction of the work, and
    far less likely to be killed by a gateway timeout.
    """
    study_area = study_area or config.STUDY_AREA

    def build(box):
        types = ["drain", "ditch", "stream", "river", "canal"]
        clauses = "\n      ".join(
            f'way["waterway"="{t}"]({_bbox_string(box)});' for t in types
        )
        return f"[out:json][timeout:120];\n    (\n      {clauses}\n    );\n    out geom;"

    if verbose:
        print("Fetching drainage network from OpenStreetMap")

    elements = _collect(build, study_area, 2, "drains", verbose)

    drains = []
    for element in elements:
        # 'geometry' is the list of points making up the line. Occasionally an element
        # comes back without it; skipping those is safer than crashing.
        if "geometry" not in element:
            continue
        drains.append({
            "type": element.get("tags", {}).get("waterway", "unknown"),
            "name": element.get("tags", {}).get("name", ""),
            "points": [(p["lat"], p["lon"]) for p in element["geometry"]],
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
    study_area = study_area or config.STUDY_AREA

    def build(box):
        return (f'[out:json][timeout:120];\n'
                f'way["highway"]({_bbox_string(box)});\n'
                f'out geom;')

    if verbose:
        print("Fetching road network from OpenStreetMap")

    # Jaipur has ~65,000 road ways. Nine sub-areas keeps each response manageable.
    elements = _collect(build, study_area, 3, "roads", verbose)

    roads = []
    for element in elements:
        if "geometry" not in element:
            continue
        tags = element.get("tags", {})
        roads.append({
            "highway": tags.get("highway", ""),
            "surface": tags.get("surface", ""),   # empty means simply not surveyed
            "name": tags.get("name", ""),
            "points": [(p["lat"], p["lon"]) for p in element["geometry"]],
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
      - Footprint SIZE: dense clusters of very small footprints are characteristic of
        informal and low-income settlement, while large footprints indicate planned
        housing, commercial or institutional development. It is a proxy, not a
        measurement of income — but a published, widely used one.

    NOTE ON VOLUME: this is by far the heaviest query in the project. `out center;`
    asks Overpass for just the CENTRE POINT of each building rather than its full
    outline, which cuts the download enormously. We lose exact footprint shape but keep
    position, which is all we need for density.
    """
    study_area = study_area or config.STUDY_AREA

    def build(box):
        return (f'[out:json][timeout:120];\n'
                f'way["building"]({_bbox_string(box)});\n'
                f'out center;')

    if verbose:
        print("Fetching buildings from OpenStreetMap (the slow one — be patient)")

    # Sixteen sub-areas. This is the query that gets killed by gateway timeouts, so it
    # gets cut the finest.
    elements = _collect(build, study_area, 4, "buildings", verbose)

    buildings = []
    for element in elements:
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
    study_area = study_area or config.STUDY_AREA
    kinds = ["school", "hospital", "clinic", "doctors", "marketplace", "pharmacy"]

    def build(box):
        bbox = _bbox_string(box)
        clauses = "\n      ".join(
            f'node["amenity"="{k}"]({bbox});\n      way["amenity"="{k}"]({bbox});'
            for k in kinds
        )
        return f"[out:json][timeout:120];\n    (\n      {clauses}\n    );\n    out center;"

    if verbose:
        print("Fetching critical facilities from OpenStreetMap")

    elements = _collect(build, study_area, 2, "facilities", verbose)

    amenities = []
    for element in elements:
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
    """Fetch every OSM layer, then check the result is real before returning it."""
    layers = {}

    layers["drains"] = fetch_drainage(study_area, verbose)
    time.sleep(2)

    layers["roads"] = fetch_roads(study_area, verbose)
    time.sleep(2)

    layers["buildings"] = fetch_buildings(study_area, verbose)
    time.sleep(2)

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
