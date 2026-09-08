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

EXPOSURE_WEIGHTS = {
    "building_density": 0.50,
    "road_density": 0.30,
    "amenity_density": 0.20,     # schools, clinics, markets — critical facilities
}

SENSITIVITY_WEIGHTS = {
    "small_building_fraction": 0.45,  # proxy for dense informal / low-income housing
    "unpaved_road_fraction": 0.35,    # proxy for weaker municipal infrastructure
    "drainage_absence": 0.20,         # no mapped stormwater drain nearby
}


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

# Overpass mirrors, in case the main one is busy. The pipeline tries them in order.
OVERPASS_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.osm.ch/api/interpreter",
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
