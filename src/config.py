"""
config.py — every setting for the project lives here.

WHY A CONFIG FILE?
Beginners often bury numbers deep inside their code ("magic numbers").
Then when you want to change the study area you have to hunt through five files.
Keeping every tunable value in one place is a habit that real engineering teams use,
and it is the first thing a reviewer looks for when judging whether code is well organised.
"""

# ----------------------------------------------------------------------------
# 1. STUDY AREA
# ----------------------------------------------------------------------------
# A bounding box is just four numbers describing a rectangle on the Earth's surface.
# These coordinates cover the built-up area of Jaipur, from Sanganer / Pratap Nagar
# in the south to Vidyadhar Nagar / Jhotwara in the north, and from Ajmer Road in
# the west to Jagatpura / the Agra Road corridor in the east.
#
# Latitude  = how far north (bigger = further north)
# Longitude = how far east  (bigger = further east)
STUDY_AREA = {
    "name": "Jaipur",
    "min_lat": 26.78,   # southern edge  (roughly Sanganer)
    "max_lat": 27.02,   # northern edge  (roughly Vidyadhar Nagar)
    "min_lon": 75.66,   # western edge   (roughly Ajmer Road / Heerapura)
    "max_lon": 75.92,   # eastern edge   (roughly Jagatpura / Transport Nagar)
}

# The centre point, used for centring the map and for the rainfall lookup.
JAIPUR_CENTRE = (26.9124, 75.7873)   # (latitude, longitude) — near Hawa Mahal


# ----------------------------------------------------------------------------
# 2. GRID RESOLUTION
# ----------------------------------------------------------------------------
# We chop the city into square cells and score each cell.
# Smaller cells = more detail, but slower and noisier.
# 300 m is a sensible compromise: fine enough to separate one colony from the next,
# coarse enough that the free 30 m elevation data is not just noise.
GRID_CELL_METRES = 300

# Elevation tiles come in "zoom levels" like Google Maps.
# Zoom 12 is roughly 30-40 m per pixel at Jaipur's latitude — matching SRTM's real
# resolution. Going higher just interpolates and invents detail that is not there.
DEM_ZOOM = 12


# ----------------------------------------------------------------------------
# 3. RAINFALL WINDOW
# ----------------------------------------------------------------------------
# We pull real daily rainfall so the project is grounded in actual monsoon events
# rather than an abstract "what if it rains" scenario.
RAINFALL_START = "2015-01-01"
RAINFALL_END = "2025-12-31"

# A "design storm" is the rainfall total the system is being tested against.
# Rather than inventing one, we compute it from the real record (see fetch_rainfall.py):
# the 99th percentile of wet-day rainfall, i.e. a day worse than 99% of rainy days.
DESIGN_STORM_PERCENTILE = 99


# ----------------------------------------------------------------------------
# 4. INDEX WEIGHTS
# ----------------------------------------------------------------------------
# The final risk score is a weighted blend of three components.
# These weights are a JUDGEMENT CALL, not a fact — which is exactly why they live
# here in the open where anyone can see and challenge them.
# sensitivity_analysis() in index.py tests how much the answer changes if you move them.
#
# HAZARD      = how likely water is to collect here (physics / terrain)
# EXPOSURE    = how many people and how much property are here to be affected
# SENSITIVITY = how badly those people cope when it does flood
#
# Risk is conventionally Hazard x Exposure x Vulnerability. We use a weighted sum of
# normalised components because it degrades more gracefully when one layer is missing
# (a zero in a product wipes out the whole score; a zero in a sum does not).
INDEX_WEIGHTS = {
    "hazard": 0.50,
    "exposure": 0.25,
    "sensitivity": 0.25,
}

# Weights *within* the hazard component.
# Topographic Wetness Index gets the largest share because it is the single best
# physical predictor of where surface water accumulates.
HAZARD_WEIGHTS = {
    "twi": 0.35,                 # topographic wetness index — flat + lots of upslope area
    "depression_depth": 0.25,    # how deep a local dip the cell sits in
    "flow_accumulation": 0.20,   # how much upstream land drains through this cell
    "drain_distance": 0.10,      # far from a functioning drain = worse
    "slope": 0.10,               # flat ground sheds water slowly
}

# WEIGHT WHAT YOU CAN ACTUALLY MEASURE.
# The obvious weighting puts buildings first — more buildings, more exposure. Checking
# the real data killed that: OpenStreetMap has 43,870 buildings mapped across the study
# area, while Jaipur's population of roughly 4 million implies something nearer 400,000.
# Coverage is around a tenth, and it is uneven, so building count is close to noise here.
#
# Road length is mapped properly: 10,488 km across the study area is a realistic figure,
# and it discriminates cleanly (median cell 1,240 m, 99th percentile 3,515 m). So road
# density carries the most weight — not because it is the better concept, but because it
# is the better measurement. Say that out loud rather than pretending otherwise.
EXPOSURE_WEIGHTS = {
    "road_density": 0.55,
    "building_density": 0.25,
    "amenity_density": 0.20,     # schools, clinics, markets — critical facilities
}

# Same reasoning as EXPOSURE_WEIGHTS above. Unpaved road share is measured from a layer
# that is well surveyed; settlement density leans on the building data we just showed to
# be roughly a tenth complete, so it gets the smallest share.
SENSITIVITY_WEIGHTS = {
    "unpaved_road_fraction": 0.50,    # proxy for weaker municipal infrastructure
    "drainage_absence": 0.30,         # no mapped stormwater drain nearby
    "small_building_fraction": 0.20,  # proxy for dense informal housing (weak coverage)
}

# ----------------------------------------------------------------------------
# 4b. WHAT COUNTS AS "URBAN"
# ----------------------------------------------------------------------------
# This decides which cells are scored at all, and which cells the percentile ranking is
# measured against. Get it wrong and every score shifts.
#
# THE ORIGINAL VERSION WAS WRONG. It counted a cell as urban if it held ANY building or
# more than 50 m of road. Fifty metres of road inside a 300 m cell is a highway crossing
# a field — so 76% of "urban" cells turned out to contain no buildings at all, and the
# median urban cell had zero. Exposure was being ranked against a population of empty
# countryside, which made the ranking close to meaningless.
#
# 800 m of road inside a 300 m cell (9 hectares) means a street network, not a road
# passing through. The building clause catches dense settlement that OSM has mapped but
# whose streets it has not.
URBAN_MIN_ROAD_M = 800
URBAN_MIN_BUILDINGS = 3

# For the populated-risk list: a cell must sit in the top 40% for exposure to qualify.
# Without a floor like this the list fills with drainage corridors — hydrologically the
# right answer, operationally useless, because nobody needs an empty floodplain drained.
PRIORITY_MIN_EXPOSURE_PERCENTILE = 0.60


# ----------------------------------------------------------------------------
# 5. DATA SOURCES
# ----------------------------------------------------------------------------
# Every one of these is free and needs NO API key or signup. That is deliberate:
# a project nobody else can reproduce is not much of a project.
DATA_SOURCES = {
    # Terrain. AWS hosts a global elevation dataset as map tiles (the "Terrarium"
    # format). Built from NASA SRTM and other public surveys.
    "elevation_tiles": "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png",

    # OpenStreetMap's query API. Gives us drains, rivers, roads and buildings.
    "overpass": "https://overpass-api.de/api/interpreter",

    # Historical weather reanalysis. Real measured daily rainfall for any point.
    "rainfall": "https://archive-api.open-meteo.com/v1/archive",
}

# WHY THIS MATTERS MORE THAN IT LOOKS
# Overpass is a free service run on donated hardware, and its operators throttle or
# outright reject requests that arrive with a library's default User-Agent
# ("python-requests/2.x"). One mirror answers such a request with a plain-text 429
# saying so; the main server returns a bare 406. Neither is obviously a "you forgot a
# header" error, and without this string the whole pipeline silently produced an empty
# map. Identify yourself: it is both required here and basic good manners.
USER_AGENT = (
    "jaipur-flood-index/1.0 "
    "(+https://github.com/samyakshah113/jaipur-flood-index)"
)

HTTP_HEADERS = {"User-Agent": USER_AGENT}

# Overpass mirrors, ordered by MEASURED capability rather than by which one
# answers fastest. Counts are road ways returned for the Jaipur bounding box:
#
#     overpass-api.de           65,205
#     overpass.private.coffee   63,656
#     overpass.kumi.systems     (timed out under load, but serves global data)
#     overpass.osm.ch                0   <- REMOVED, see below
#
# overpass.osm.ch is a REGIONAL instance. Queried for Jaipur it returns HTTP 200,
# valid JSON, no remark, and zero elements. Every automated check passes and the
# answer is empty. It is deliberately not in this list: a mirror that confidently
# reports "nothing here" for a city of four million is worse than one that fails.
OVERPASS_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]


# ----------------------------------------------------------------------------
# 6. FILE PATHS
# ----------------------------------------------------------------------------
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DATA_DIR = PROJECT_ROOT / "data" / "raw"
OUTPUT_DIR = PROJECT_ROOT / "outputs"

# Make sure these folders exist so nothing crashes on a fresh clone.
RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Where your own ground-truth observations live. This file is the heart of the
# project's credibility — see docs/HOW_TO_COLLECT_GROUND_TRUTH.md.
GROUND_TRUTH_CSV = PROJECT_ROOT / "data" / "waterlogging_observations.csv"
