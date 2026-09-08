"""
run_pipeline.py — the whole project, start to finish, in one command.

    python run_pipeline.py --demo     run on synthetic data (offline, ~1 minute)
    python run_pipeline.py            run on real downloaded data (~10-20 minutes)
    python run_pipeline.py --fast     real data, coarser grid, quicker

WHY A SINGLE ENTRY POINT MATTERS
"Reproducibility" sounds like an academic buzzword until someone else tries to run your
project, hits four undocumented manual steps, and gives up. One command that goes from
nothing to a finished map is the difference between a project people can check and a
project people take your word for.
"""

import argparse
import sys
import time

import numpy as np
import pandas as pd

from src import config, features, index, mapping, terrain, validate


def main():
    parser = argparse.ArgumentParser(description="Jaipur Flood Vulnerability Index")
    parser.add_argument("--demo", action="store_true",
                        help="use synthetic data instead of downloading (works offline)")
    parser.add_argument("--fast", action="store_true",
                        help="coarser grid and lower-resolution terrain, for a quick run")
    parser.add_argument("--cell-size", type=int, default=None,
                        help="grid cell size in metres (default 300)")
    parser.add_argument("--skip-maps", action="store_true",
                        help="compute everything but do not render the HTML maps")
    args = parser.parse_args()

    started = time.time()
    cell_size = args.cell_size or (500 if args.fast else config.GRID_CELL_METRES)

    print("=" * 70)
    print("  JAIPUR FLOOD VULNERABILITY INDEX")
    print("=" * 70)
    print(f"  Mode        {'SYNTHETIC DEMO DATA' if args.demo else 'live open data'}")
    print(f"  Study area  {config.STUDY_AREA['name']}")
    print(f"  Grid cell   {cell_size} m")
    print("=" * 70)

    # ------------------------------------------------------------------
    # STEP 1 — terrain
    # ------------------------------------------------------------------
    print("\n[1/6] ELEVATION")
    if args.demo:
        from src import demo
        dem = demo.synthetic_dem()
        print(f"  synthetic terrain, {dem.shape[0]} x {dem.shape[1]} cells")
        print(f"  elevation range {dem.min():.0f}-{dem.max():.0f} m")
    else:
        from src import fetch_elevation
        raw_dem, bounds = fetch_elevation.fetch_dem(zoom=11 if args.fast else config.DEM_ZOOM)
        dem, _ = fetch_elevation.crop_to_study_area(raw_dem, bounds)
        dem = fetch_elevation.fill_missing_elevations(dem)
        print(f"  cropped to {dem.shape[0]} x {dem.shape[1]} cells")

    # The real ground distance one elevation pixel covers. Needed for the slope and
    # TWI maths to come out in real units rather than arbitrary ones.
    lat_span_m = ((config.STUDY_AREA["max_lat"] - config.STUDY_AREA["min_lat"])
                  * features.METRES_PER_DEGREE_LAT)
    dem_pixel_m = lat_span_m / dem.shape[0]
    print(f"  each elevation pixel covers about {dem_pixel_m:.0f} m on the ground")

    # ------------------------------------------------------------------
    # STEP 2 — hydrology
    # ------------------------------------------------------------------
    print("\n[2/6] TERRAIN ANALYSIS (filling sinks, routing flow, computing wetness)")
    terrain_result = terrain.analyse_terrain(dem, dem_pixel_m)
    print(f"  deepest depression found: {terrain_result['depression_depth'].max():.2f} m")
    print(f"  peak flow accumulation:   {terrain_result['flow_accumulation'].max():.0f} cells")
    print(f"  TWI range: {terrain_result['twi'].min():.1f} to {terrain_result['twi'].max():.1f}")

    # ------------------------------------------------------------------
    # STEP 3 — infrastructure
    # ------------------------------------------------------------------
    print("\n[3/6] INFRASTRUCTURE AND RAINFALL")
    if args.demo:
        from src import demo
        osm_layers = demo.synthetic_osm()
        rainfall_summary = demo.synthetic_rainfall_summary()
        print(f"  synthetic: {len(osm_layers['buildings'])} buildings, "
              f"{len(osm_layers['roads'])} roads, {len(osm_layers['drains'])} drains")
    else:
        from src import fetch_osm, fetch_rainfall
        osm_layers = fetch_osm.fetch_all_osm()
        rainfall = fetch_rainfall.fetch_daily_rainfall()
        rainfall_summary = fetch_rainfall.summarise_rainfall(rainfall)

    runoff = None
    if rainfall_summary.get("design_storm_mm"):
        from src.fetch_rainfall import runoff_volume_per_cell
        runoff = runoff_volume_per_cell(rainfall_summary["design_storm_mm"], cell_size)
        print(f"  design storm {rainfall_summary['design_storm_mm']:.0f} mm/day "
              f"-> about {runoff:.0f} m3 of runoff per {cell_size} m cell")

    # ------------------------------------------------------------------
    # STEP 4 — feature table
    # ------------------------------------------------------------------
    print("\n[4/6] BUILDING THE FEATURE TABLE")
    grid = features.build_grid(cell_size_m=cell_size)
    table = features.build_feature_table(terrain_result, osm_layers, grid)

    # ------------------------------------------------------------------
    # STEP 5 — scoring
    # ------------------------------------------------------------------
    print("\n[5/6] SCORING")
    table = index.compute_component_scores(table)
    table = index.compute_risk_index(table)
    table = index.sensitivity_analysis(table)

    top_areas = index.top_risk_areas(table, n=20)

    print("\n  Ten highest-priority cells (robust across weightings):")
    print("  " + "-" * 62)
    for rank, (_, site) in enumerate(top_areas.head(10).iterrows(), start=1):
        print(f"   {rank:2d}. {site['lat']:.4f}, {site['lon']:.4f}   "
              f"risk {site['risk_index']:5.1f}   "
              f"robust in {site['rank_stability'] * 100:3.0f}% of weightings   "
              f"{site['building_count']:.0f} buildings")

    # ------------------------------------------------------------------
    # STEP 6 — validation and output
    # ------------------------------------------------------------------
    print("\n[6/6] VALIDATION AND OUTPUT")

    validation_points = None
    if args.demo:
        from src import demo
        observations = demo.synthetic_observations(table, grid)
        validation_points = validate.attach_scores(observations, table, grid)
        auc = validate.roc_auc(validation_points, verbose=False)
        print(f"  synthetic-data AUC {auc:.3f} — MEANINGLESS, the fake observations")
        print(f"  were generated from the model's own scores. This only proves the")
        print(f"  validation code runs. Real numbers need real observations.")
    elif config.GROUND_TRUTH_CSV.exists():
        report = validate.full_validation_report(config.GROUND_TRUTH_CSV, table, grid)
        if report:
            validation_points = report["scored_observations"]
    else:
        print(f"  No observations file at {config.GROUND_TRUTH_CSV}")
        print(f"  The index is UNVALIDATED until you create one.")
        print(f"  See docs/HOW_TO_COLLECT_GROUND_TRUTH.md — this is the step that")
        print(f"  turns a nice-looking map into a defensible result.")

    # Save the tables.
    table_path = config.OUTPUT_DIR / "jaipur_flood_risk_cells.csv"
    table.to_csv(table_path, index=False)
    print(f"\n  Full cell table -> {table_path}")

    top_path = config.OUTPUT_DIR / "top_priority_sites.csv"
    top_areas.to_csv(top_path, index=False)
    print(f"  Priority sites  -> {top_path}")

    if not args.skip_maps:
        print("\n  Rendering maps...")
        mapping.build_risk_map(
            table, grid,
            drains=osm_layers["drains"],
            top_areas=top_areas,
            synthetic=args.demo,
            validation=validation_points,
        )
        mapping.build_diagnostic_maps(table, grid)

    elapsed = time.time() - started
    print("\n" + "=" * 70)
    print(f"  Finished in {elapsed:.0f} seconds")
    if args.demo:
        print("  REMINDER: this run used synthetic data. Nothing here describes Jaipur.")
    print("=" * 70)

    return table, grid


if __name__ == "__main__":
    main()
