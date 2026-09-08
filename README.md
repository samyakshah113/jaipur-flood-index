# Jaipur Flood Vulnerability Index

An open-data model that identifies which parts of Jaipur are most likely to waterlog
during monsoon rainfall, and which of those areas have the least capacity to cope.

Built entirely from free, keyless public data — NASA-derived elevation, OpenStreetMap
infrastructure, and ERA5 rainfall reanalysis — so that anyone can reproduce it.

---

## What this is, in plain terms

Jaipur floods in the same places most years. Municipal drainage capacity is finite and
has to be allocated somewhere. This project produces a ranked, evidence-based answer to
"where first?", grounded in the physics of where water actually goes.

The model divides the city into 300-metre cells and scores each on three things:

| Component | Question it answers | Where the data comes from |
|---|---|---|
| **Hazard** | Does water physically collect here? | Terrain: wetness index, depression depth, flow accumulation, slope, distance to drainage |
| **Exposure** | How much is here to be damaged? | Building density, road density, schools and clinics |
| **Sensitivity** | How badly do people here cope? | Unpaved road share, settlement density, absence of mapped drainage |

These combine into a 0–100 relative risk index.

## What this is not

Being clear about this is the point, not a disclaimer bolted on the end:

- **It is relative, not absolute.** It ranks Jaipur against itself. A score of 95 means
  "worse than 95% of Jaipur", never "will flood to a depth of X metres".
- **300 m cells cannot see a blocked drain.** Street-level waterlogging often comes down
  to one clogged inlet. This model finds the areas where the terrain is against you; it
  cannot find the specific culvert.
- **The sensitivity component uses proxies, not income data.** Ward-level income data is
  not publicly available at this resolution. Unpaved road share and settlement density
  are published proxies for infrastructure disadvantage, but they are proxies, and they
  can be wrong about real neighbourhoods.
- **OpenStreetMap drainage coverage is uneven.** A cell with no mapped drain nearby may
  simply be one nobody has surveyed yet.
- **It is only as good as its validation.** See below.

## Validation

The index is unvalidated until it is tested against places that actually flooded.
`src/validate.py` does this properly:

- **AUC** rather than accuracy, because accuracy is meaningless on unbalanced data
- **Bootstrap confidence intervals**, because a small sample deserves error bars
- **Baseline comparison** against single variables, to check the composite index is
  earning its complexity rather than just being more elaborate

See `docs/HOW_TO_COLLECT_GROUND_TRUTH.md` for how to build the observation set. This is
the most important part of the project and the part that cannot be automated.

## Running it

```bash
git clone https://github.com/YOUR-USERNAME/jaipur-flood-index.git
cd jaipur-flood-index
pip install -r requirements.txt

python run_pipeline.py --demo    # synthetic data, offline, ~10 seconds
python run_pipeline.py           # real data, ~10-20 minutes
```

Or open `notebooks/JFVI_walkthrough.ipynb` in Google Colab — nothing to install.

Outputs land in `outputs/`: an interactive HTML map, diagnostic maps for each
component, and CSVs of every cell and the ranked priority sites.

## Tests

```bash
python -m pytest tests/ -v
```

The hydrology tests verify the algorithms on landscapes with known answers — that
filling a pit raises it to the surrounding level, that water in a V-shaped valley
collects on the valley floor, that flow accumulation never invents water. If these
fail, every map the project produces is wrong.

## Method notes

- **Depression filling** uses Priority-Flood (Barnes, Lehman & Mulla, 2014)
- **Flow routing** uses D8 steepest-descent, with diagonal distance correction
- **Topographic Wetness Index** follows Beven & Kirkby (1979): `TWI = ln(a / tan β)`
- **Normalisation** is percentile rank rather than min-max, because flow accumulation
  is heavily skewed and min-max would compress the entire city into the bottom of the scale
- **Sensitivity analysis** re-runs the index 200 times with randomised weights, so the
  reported priority sites are the ones that stay high risk regardless of the assumptions

Full reasoning in `docs/METHODOLOGY.md`.

## Data sources

| Layer | Source | Licence |
|---|---|---|
| Elevation | AWS Terrain Tiles (NASA SRTM et al.) | Public domain |
| Drainage, roads, buildings | OpenStreetMap via Overpass API | ODbL |
| Rainfall | Open-Meteo historical archive (ERA5) | CC BY 4.0 |

No API keys. No signups. No paywalls.

## Repository layout

```
src/
  config.py            every tunable setting, in one place
  terrain.py           the hydrology — sink filling, flow routing, TWI
  fetch_elevation.py   downloads and decodes elevation tiles
  fetch_osm.py         downloads drainage, roads, buildings
  fetch_rainfall.py    downloads and summarises rainfall
  features.py          rasterises everything onto a common grid
  index.py             scoring, weighting, sensitivity analysis
  validate.py          AUC, bootstrap CIs, baseline comparison
  mapping.py           interactive Folium maps
  demo.py              synthetic data for offline testing
tests/                 correctness tests for the hydrology
docs/                  methodology and ground-truth collection guide
run_pipeline.py        one command, start to finish
```

## How this was built

The pipeline in `src/` was written with AI assistance (Claude); the commit history
records this. The reasoning behind every modelling decision is set out in
`docs/METHODOLOGY.md`, and I can explain each component of it —
`docs/Jaipur_Flood_Index_Study_Guide.pdf` is the walkthrough I worked through myself.

Field data collection and validation (`data/waterlogging_observations.csv`) is my own
work and is in progress. Until it is done, the index is unvalidated and no accuracy
figure is claimed here.

## Licence

MIT.
