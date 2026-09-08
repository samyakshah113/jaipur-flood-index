"""
fetch_elevation.py — download real terrain data for Jaipur.

WHERE THE DATA COMES FROM
Amazon hosts a free global elevation dataset, assembled from NASA's Shuttle Radar
Topography Mission (SRTM) and other public surveys. It is served as map tiles, exactly
like the image tiles that make up Google Maps — but instead of a picture of the ground,
each pixel's COLOUR encodes the HEIGHT of the ground.

No API key. No signup. No download limits. Which means anyone reading your project can
reproduce it, and that is worth more than a fancier dataset behind a login wall.

THE CLEVER BIT: "TERRARIUM" ENCODING
A PNG pixel has three colour channels — red, green, blue — each 0 to 255. That gives
256 x 256 x 256 = about 16.7 million possible values, plenty to store an elevation in
centimetres. The agreed formula is:

    elevation_in_metres = (red * 256 + green + blue / 256) - 32768

The 32768 offset lets the format store negative elevations (below sea level, like the
Dead Sea) without needing negative numbers.
"""

import io
import math
import time

import numpy as np
import requests

from . import config


# ----------------------------------------------------------------------------
# CONVERTING BETWEEN LATITUDE/LONGITUDE AND TILE NUMBERS
# ----------------------------------------------------------------------------
def deg_to_tile(lat, lon, zoom):
    """
    Convert a latitude/longitude into the (x, y) number of the map tile containing it.

    This is the standard "slippy map" scheme used by OpenStreetMap, Google Maps and
    essentially every web map. At zoom level z the world is cut into a 2^z by 2^z grid.

    Longitude is easy: it maps linearly across the world.
    Latitude is not, because web maps use the Web Mercator projection, which stretches
    the poles. Hence the logarithm and tangent below — that is the Mercator formula.
    """
    lat_rad = math.radians(lat)
    n = 2.0 ** zoom

    x = int((lon + 180.0) / 360.0 * n)
    y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)

    return x, y


def tile_to_deg(x, y, zoom):
    """
    The reverse: given a tile's (x, y), find the lat/lon of its top-left corner.
    We need this to know exactly where on Earth each pixel of our elevation array sits.
    """
    n = 2.0 ** zoom
    lon = x / n * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    return lat, lon


# ----------------------------------------------------------------------------
# DECODING A SINGLE TILE
# ----------------------------------------------------------------------------
def decode_terrarium(png_bytes):
    """
    Turn a Terrarium PNG's pixels into an array of elevations in metres.

    Applies the formula from the file header. Note the .astype(np.float64) — without it,
    `red * 256` would overflow the 8-bit integer type and wrap around to nonsense.
    That is a genuinely nasty bug because it produces plausible-looking wrong numbers
    rather than an error.
    """
    from PIL import Image

    image = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    pixels = np.array(image).astype(np.float64)

    red = pixels[:, :, 0]
    green = pixels[:, :, 1]
    blue = pixels[:, :, 2]

    return (red * 256.0 + green + blue / 256.0) - 32768.0


def _download_tile(x, y, zoom, retries=3):
    """
    Fetch one tile, retrying politely if the server is briefly busy.

    "Exponential backoff" means waiting longer after each failure (1s, then 2s, then 4s)
    rather than hammering the server. It is basic good manners when using a free public
    service, and it is what production code does.
    """
    url = config.DATA_SOURCES["elevation_tiles"].format(z=zoom, x=x, y=y)

    for attempt in range(retries):
        try:
            response = requests.get(url, timeout=30)
            if response.status_code == 200:
                return response.content
            # 404 means there is genuinely no tile there (e.g. open ocean) — no point retrying.
            if response.status_code == 404:
                return None
        except requests.RequestException as error:
            if attempt == retries - 1:
                raise RuntimeError(f"Could not download tile {zoom}/{x}/{y}: {error}")

        time.sleep(2 ** attempt)

    return None


# ----------------------------------------------------------------------------
# STITCHING TILES INTO ONE ELEVATION MAP
# ----------------------------------------------------------------------------
def fetch_dem(study_area=None, zoom=None, verbose=True):
    """
    Download every tile covering the study area and stitch them into one array.

    Returns
    -------
    dem : 2-D numpy array of elevations in metres
    bounds : dict giving the exact lat/lon edges of that array, so we can place it on a map
    """
    study_area = study_area or config.STUDY_AREA
    zoom = zoom or config.DEM_ZOOM

    # Work out the range of tiles we need.
    # Careful: tile Y numbers INCREASE going south, while latitude increases going north.
    # So max_lat gives the minimum y. Getting this backwards produces a vertically
    # flipped map, which is subtle enough to slip through unnoticed.
    x_min, y_min = deg_to_tile(study_area["max_lat"], study_area["min_lon"], zoom)
    x_max, y_max = deg_to_tile(study_area["min_lat"], study_area["max_lon"], zoom)

    tile_count = (x_max - x_min + 1) * (y_max - y_min + 1)
    if verbose:
        print(f"Downloading {tile_count} elevation tiles at zoom {zoom}...")

    rows = []
    for y in range(y_min, y_max + 1):
        row_tiles = []
        for x in range(x_min, x_max + 1):
            data = _download_tile(x, y, zoom)

            if data is None:
                # No tile available: fill with NaN ("not a number") rather than 0.
                # Zero would be read as "sea level" and would carve a fake canyon
                # through the map. NaN correctly means "unknown".
                row_tiles.append(np.full((256, 256), np.nan))
            else:
                row_tiles.append(decode_terrarium(data))

            if verbose:
                print(".", end="", flush=True)

        rows.append(np.hstack(row_tiles))   # join this row of tiles side by side

    dem = np.vstack(rows)                   # stack the rows on top of each other

    if verbose:
        print(f"\nGot a {dem.shape[0]} x {dem.shape[1]} elevation grid.")
        print(f"Elevation range: {np.nanmin(dem):.0f} m to {np.nanmax(dem):.0f} m")

    # The exact geographic bounds of the stitched image.
    top_lat, left_lon = tile_to_deg(x_min, y_min, zoom)
    bottom_lat, right_lon = tile_to_deg(x_max + 1, y_max + 1, zoom)

    bounds = {
        "min_lat": bottom_lat, "max_lat": top_lat,
        "min_lon": left_lon,  "max_lon": right_lon,
    }

    return dem, bounds


def crop_to_study_area(dem, bounds, study_area=None):
    """
    Trim the stitched tiles down to exactly the study area.

    Tiles never line up neatly with the rectangle you asked for, so we always download
    slightly too much and then cut. Doing the analysis on the untrimmed array would
    include a strip of countryside outside the city and skew every statistic.
    """
    study_area = study_area or config.STUDY_AREA
    rows, cols = dem.shape

    lat_span = bounds["max_lat"] - bounds["min_lat"]
    lon_span = bounds["max_lon"] - bounds["min_lon"]

    # Convert the target lat/lon into row/column positions in the array.
    # Row 0 is the NORTH edge, so latitude runs "backwards" relative to row number.
    row_top = int((bounds["max_lat"] - study_area["max_lat"]) / lat_span * rows)
    row_bottom = int((bounds["max_lat"] - study_area["min_lat"]) / lat_span * rows)
    col_left = int((study_area["min_lon"] - bounds["min_lon"]) / lon_span * cols)
    col_right = int((study_area["max_lon"] - bounds["min_lon"]) / lon_span * cols)

    # Clamp to the array's real size so a rounding error cannot cause a crash.
    row_top = max(0, row_top)
    row_bottom = min(rows, row_bottom)
    col_left = max(0, col_left)
    col_right = min(cols, col_right)

    cropped = dem[row_top:row_bottom, col_left:col_right]

    return cropped, dict(study_area)


def fill_missing_elevations(dem):
    """
    Replace any NaN gaps with the average of the surrounding data.

    Small holes are common in radar-derived elevation data (steep slopes and water
    surfaces can scatter the signal away). Leaving NaNs in place would poison every
    downstream calculation, because almost any arithmetic involving NaN gives NaN.
    """
    if not np.any(np.isnan(dem)):
        return dem

    filled = dem.copy()
    mean_elevation = np.nanmean(dem)

    # A simple, robust approach: fill holes with the overall mean.
    # For the small gaps typical in this data that is entirely adequate, and it cannot
    # fail the way a fancier interpolation can.
    filled[np.isnan(filled)] = mean_elevation

    return filled
