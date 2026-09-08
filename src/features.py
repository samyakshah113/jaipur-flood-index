"""
features.py — turn scattered geographic data into a tidy table of numbers.

THE PROBLEM THIS SOLVES
After the fetch steps you have four incompatible things: an elevation array on a fine
pixel grid, a list of drain lines, a list of road lines, and a scatter of building
points. You cannot compare them. Machine learning needs a rectangular table where every
row is one place and every column is one measurement.

So we lay a regular grid of squares over Jaipur and, for each square, ask the same set
of questions: how high is it, how flat, how many buildings, how much road, how far to
the nearest drain. That grid becomes the table.

This is called RASTERISATION, and it is most of what applied GIS work actually consists
of. It is also where the majority of real bugs live, because coordinate conversions are
fiddly and mistakes produce maps that look fine and are wrong.
"""

import numpy as np
import pandas as pd
from scipy import ndimage

from . import config


# ----------------------------------------------------------------------------
# CONVERTING BETWEEN DEGREES AND METRES
# ----------------------------------------------------------------------------
# One degree of latitude is about 110.6 km anywhere on Earth.
# One degree of longitude shrinks as you move away from the equator, because the
# lines of longitude converge at the poles. At Jaipur's latitude (~26.9 deg N) a degree
# of longitude is only about 99 km.
#
# Ignoring this is the single most common beginner GIS error. It stretches your map
# east-west by roughly 11%, which quietly distorts every distance and density you compute.
METRES_PER_DEGREE_LAT = 110_574.0


def metres_per_degree_lon(latitude):
    """Length of one degree of longitude, in metres, at a given latitude."""
    return 111_320.0 * np.cos(np.radians(latitude))


# ----------------------------------------------------------------------------
# BUILDING THE GRID
# ----------------------------------------------------------------------------
def build_grid(study_area=None, cell_size_m=None):
    """
    Lay a regular grid of square cells over the study area.

    Returns a dictionary describing the grid: how many rows and columns, and the
    lat/lon of the centre of every cell.
    """
    study_area = study_area or config.STUDY_AREA
    cell_size_m = cell_size_m or config.GRID_CELL_METRES

    centre_lat = (study_area["min_lat"] + study_area["max_lat"]) / 2
    lon_scale = metres_per_degree_lon(centre_lat)

    # How many degrees is one cell, in each direction?
    cell_lat_degrees = cell_size_m / METRES_PER_DEGREE_LAT
    cell_lon_degrees = cell_size_m / lon_scale

    n_rows = int(np.ceil((study_area["max_lat"] - study_area["min_lat"]) / cell_lat_degrees))
    n_cols = int(np.ceil((study_area["max_lon"] - study_area["min_lon"]) / cell_lon_degrees))

    # Cell centres. Row 0 is the NORTH edge, matching how image arrays are stored.
    lat_centres = study_area["max_lat"] - (np.arange(n_rows) + 0.5) * cell_lat_degrees
    lon_centres = study_area["min_lon"] + (np.arange(n_cols) + 0.5) * cell_lon_degrees

    return {
        "n_rows": n_rows,
        "n_cols": n_cols,
        "cell_size_m": cell_size_m,
        "cell_lat_degrees": cell_lat_degrees,
        "cell_lon_degrees": cell_lon_degrees,
        "lat_centres": lat_centres,
        "lon_centres": lon_centres,
        "bounds": dict(study_area),
    }


def latlon_to_cell(lat, lon, grid):
    """
    Which grid cell does a given latitude/longitude fall in?

    Returns (row, col), or (None, None) if the point is outside the study area.
    """
    bounds = grid["bounds"]

    if not (bounds["min_lat"] <= lat <= bounds["max_lat"]):
        return None, None
    if not (bounds["min_lon"] <= lon <= bounds["max_lon"]):
        return None, None

    row = int((bounds["max_lat"] - lat) / grid["cell_lat_degrees"])
    col = int((lon - bounds["min_lon"]) / grid["cell_lon_degrees"])

    # A point exactly on the northern or eastern edge would index one past the end.
    row = min(row, grid["n_rows"] - 1)
    col = min(col, grid["n_cols"] - 1)

    return row, col


# ----------------------------------------------------------------------------
# RASTERISING POINTS (buildings, facilities)
# ----------------------------------------------------------------------------
def rasterise_points(points, grid, weight_key=None):
    """
    Count how many points fall into each grid cell.

    Parameters
    ----------
    points : list of dicts, each needing 'lat' and 'lon'
    weight_key : optionally, a key whose value is added instead of 1 — useful if you
                 later want to weight by building floor area rather than count.
    """
    raster = np.zeros((grid["n_rows"], grid["n_cols"]))

    for point in points:
        row, col = latlon_to_cell(point["lat"], point["lon"], grid)
        if row is None:
            continue
        raster[row, col] += float(point.get(weight_key, 1)) if weight_key else 1.0

    return raster


# ----------------------------------------------------------------------------
# RASTERISING LINES (roads, drains)
# ----------------------------------------------------------------------------
def rasterise_lines(lines, grid, filter_function=None):
    """
    Measure how many metres of line fall inside each grid cell.

    HOW IT WORKS
    Each line is a chain of points. For every segment between consecutive points we
    work out its real length in metres, then walk along it in small steps, adding a
    share of the length to whichever cell each step lands in.

    Stepping along rather than just marking the endpoints matters: a 2 km stretch of
    highway crossing seven cells should register in all seven, not just the two at
    its ends.

    Parameters
    ----------
    filter_function : optional test applied to each line. Lets you rasterise, say, only
                      unpaved roads without writing a second near-identical function.
    """
    raster = np.zeros((grid["n_rows"], grid["n_cols"]))
    centre_lat = (grid["bounds"]["min_lat"] + grid["bounds"]["max_lat"]) / 2
    lon_scale = metres_per_degree_lon(centre_lat)

    # Step size: a third of a cell, so we cannot skip over a cell entirely.
    step_metres = grid["cell_size_m"] / 3.0

    for line in lines:
        if filter_function and not filter_function(line):
            continue

        points = line["points"]

        for i in range(len(points) - 1):
            lat1, lon1 = points[i]
            lat2, lon2 = points[i + 1]

            # Convert the segment's extent into metres so the length is real.
            dy = (lat2 - lat1) * METRES_PER_DEGREE_LAT
            dx = (lon2 - lon1) * lon_scale
            segment_length = np.sqrt(dx * dx + dy * dy)

            if segment_length == 0:
                continue

            n_steps = max(int(segment_length / step_metres), 1)
            length_per_step = segment_length / n_steps

            for step in range(n_steps):
                fraction = (step + 0.5) / n_steps         # midpoint of this little step
                lat = lat1 + (lat2 - lat1) * fraction
                lon = lon1 + (lon2 - lon1) * fraction

                row, col = latlon_to_cell(lat, lon, grid)
                if row is not None:
                    raster[row, col] += length_per_step

    return raster


# ----------------------------------------------------------------------------
# DISTANCE TO THE NEAREST DRAIN
# ----------------------------------------------------------------------------
def distance_to_nearest(raster, grid):
    """
    For every cell, how far is it to the nearest cell that contains a feature?

    Uses a Euclidean distance transform — an efficient algorithm that computes the
    distance from every empty pixel to the nearest non-empty one in a single pass.
    Writing this yourself with nested loops would be O(n^2) and unbearably slow;
    scipy's version is O(n).

    Returns distances in METRES.
    """
    has_feature = raster > 0

    # Edge case: if nothing was mapped at all, every distance is "very far" rather
    # than zero. Returning zeros would tell the model every cell is beside a drain,
    # which is the opposite of the truth.
    if not np.any(has_feature):
        return np.full(raster.shape, grid["cell_size_m"] * max(raster.shape))

    # distance_transform_edt measures distance to the nearest ZERO, so we invert.
    distance_in_cells = ndimage.distance_transform_edt(~has_feature)

    return distance_in_cells * grid["cell_size_m"]


# ----------------------------------------------------------------------------
# RESAMPLING THE TERRAIN ARRAYS ONTO THE GRID
# ----------------------------------------------------------------------------
def resample_to_grid(array, grid, method="mean"):
    """
    Shrink a fine elevation-resolution array down to the coarser analysis grid.

    The elevation data is roughly 30 m per pixel; our grid is 300 m. So roughly 100
    elevation pixels sit inside each grid cell and we must combine them into one number.

    WHICH STATISTIC TO USE MATTERS A LOT:
      'mean' — for slope and TWI, where you want the typical condition
      'min'  — for elevation, because a flood finds the LOWEST point in a cell, and
               averaging would hide exactly the dip you are looking for
      'max'  — for flow accumulation, since the drainage line through a cell is the
               feature of interest and averaging would dilute it away

    Choosing the wrong one here is a subtle, plausible-looking way to get the wrong answer.
    """
    source_rows, source_cols = array.shape
    target_rows, target_cols = grid["n_rows"], grid["n_cols"]

    result = np.zeros((target_rows, target_cols))

    # Which source pixels belong to each target cell.
    row_edges = np.linspace(0, source_rows, target_rows + 1).astype(int)
    col_edges = np.linspace(0, source_cols, target_cols + 1).astype(int)

    for r in range(target_rows):
        for c in range(target_cols):
            block = array[row_edges[r]:row_edges[r + 1], col_edges[c]:col_edges[c + 1]]

            if block.size == 0:
                result[r, c] = np.nan
                continue

            if method == "mean":
                result[r, c] = np.nanmean(block)
            elif method == "min":
                result[r, c] = np.nanmin(block)
            elif method == "max":
                result[r, c] = np.nanmax(block)
            else:
                raise ValueError(f"Unknown method '{method}' — use mean, min or max")

    return result


# ----------------------------------------------------------------------------
# PUTTING IT ALL TOGETHER
# ----------------------------------------------------------------------------
def build_feature_table(terrain, osm_layers, grid, verbose=True):
    """
    Produce the final table: one row per grid cell, one column per measurement.

    This is the handover point between "geography" and "data science". Everything after
    this is ordinary table manipulation of the kind you would do on any dataset.
    """
    if verbose:
        print(f"Building feature table for {grid['n_rows']} x {grid['n_cols']} cells")

    # --- Terrain features, resampled from the fine elevation grid -------------
    elevation = resample_to_grid(terrain["elevation"], grid, "min")     # lowest point wins
    slope = resample_to_grid(terrain["slope"], grid, "mean")
    twi = resample_to_grid(terrain["twi"], grid, "mean")
    flow_acc = resample_to_grid(terrain["flow_accumulation"], grid, "max")
    depression = resample_to_grid(terrain["depression_depth"], grid, "max")

    # --- Relative elevation --------------------------------------------------
    # Absolute height above sea level is nearly useless in a city: 400 m tells you
    # nothing. What floods a street is being lower than the ground AROUND it.
    # A uniform filter computes the local neighbourhood average; subtracting gives
    # height relative to surroundings. Negative = sitting in a dip.
    neighbourhood_mean = ndimage.uniform_filter(elevation, size=5, mode="nearest")
    relative_elevation = elevation - neighbourhood_mean

    # --- OSM features --------------------------------------------------------
    building_count = rasterise_points(osm_layers["buildings"], grid)
    amenity_count = rasterise_points(osm_layers["amenities"], grid)

    road_length = rasterise_lines(osm_layers["roads"], grid)
    drain_length = rasterise_lines(osm_layers["drains"], grid)

    # Unpaved / track-grade roads, as an infrastructure-quality proxy.
    def is_unpaved(road):
        unpaved_surfaces = {"unpaved", "dirt", "ground", "earth", "gravel", "sand", "mud"}
        return (road.get("surface", "") in unpaved_surfaces
                or road.get("highway", "") in {"track", "path"})

    unpaved_length = rasterise_lines(osm_layers["roads"], grid, filter_function=is_unpaved)

    drain_distance = distance_to_nearest(drain_length, grid)

    # --- Small-building fraction --------------------------------------------
    # Many buildings packed into one cell means small buildings packed tightly.
    # We express it as buildings per hectare, which is a standard planning unit
    # and lets you compare against published density figures.
    cell_area_hectares = (grid["cell_size_m"] ** 2) / 10_000
    building_density = building_count / cell_area_hectares

    # --- Assemble the table --------------------------------------------------
    rows = []
    for r in range(grid["n_rows"]):
        for c in range(grid["n_cols"]):
            road_m = road_length[r, c]

            rows.append({
                "row": r,
                "col": c,
                "lat": grid["lat_centres"][r],
                "lon": grid["lon_centres"][c],

                # terrain
                "elevation_m": elevation[r, c],
                "relative_elevation_m": relative_elevation[r, c],
                "slope_deg": slope[r, c],
                "twi": twi[r, c],
                "flow_accumulation": flow_acc[r, c],
                "depression_depth_m": depression[r, c],

                # exposure
                "building_count": building_count[r, c],
                "building_density_per_ha": building_density[r, c],
                "amenity_count": amenity_count[r, c],
                "road_length_m": road_m,

                # infrastructure quality / sensitivity
                "unpaved_road_m": unpaved_length[r, c],
                # Guard the division: a cell with no roads at all would be 0/0.
                "unpaved_fraction": unpaved_length[r, c] / road_m if road_m > 0 else 0.0,
                "drain_length_m": drain_length[r, c],
                "drain_distance_m": drain_distance[r, c],
            })

    table = pd.DataFrame(rows)

    # Cells with essentially nothing in them are countryside inside our rectangle, not
    # city. Keeping them would drag every percentile calculation towards zero and make
    # the urban areas all look uniformly high risk by comparison.
    table["is_urban"] = (table["building_count"] > 0) | (table["road_length_m"] > 50)

    if verbose:
        urban = table["is_urban"].sum()
        print(f"  {len(table)} cells total, {urban} classified as urban "
              f"({urban / len(table) * 100:.0f}%)")

    return table
