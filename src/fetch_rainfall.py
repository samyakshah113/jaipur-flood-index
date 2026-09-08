"""
fetch_rainfall.py — real measured rainfall for Jaipur.

WHY BOTHER WITH RAINFALL AT ALL?
Terrain tells you WHERE water collects. Rainfall tells you HOW MUCH and HOW OFTEN.
Without it, your risk map is answering "where would water pool if it rained" in the
abstract. With it, you can say something concrete: "on a day like 1 August 2024, when
Jaipur recorded around 180 mm, these are the cells that receive runoff from more than
X hectares of upstream land."

It also anchors the project in something real and checkable. Anyone can look up whether
Jaipur actually got that much rain.

THE SOURCE
Open-Meteo's historical archive, built on ERA5 reanalysis — the European Centre for
Medium-Range Weather Forecasts' reconstruction of past weather, which blends station
observations, satellite data and a physical atmosphere model. Free, no API key.

CAVEAT WORTH KNOWING: reanalysis is modelled, on a roughly 25 km grid. It captures
regional monsoon behaviour well but smooths out very local cloudbursts, which is
precisely what causes flash urban flooding. Say this in your write-up.
"""

import numpy as np
import pandas as pd
import requests

from . import config


def fetch_daily_rainfall(lat=None, lon=None, start=None, end=None, verbose=True):
    """
    Download the daily rainfall record for a point.

    Returns a pandas DataFrame with a date column and a rainfall_mm column.
    """
    lat = lat if lat is not None else config.JAIPUR_CENTRE[0]
    lon = lon if lon is not None else config.JAIPUR_CENTRE[1]
    start = start or config.RAINFALL_START
    end = end or config.RAINFALL_END

    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start,
        "end_date": end,
        "daily": "precipitation_sum",
        "timezone": "Asia/Kolkata",   # so a "day" means an Indian calendar day
    }

    if verbose:
        print(f"Fetching rainfall for ({lat:.4f}, {lon:.4f}) from {start} to {end}")

    response = requests.get(
        config.DATA_SOURCES["rainfall"], params=params,
        headers=config.HTTP_HEADERS, timeout=60,
    )
    response.raise_for_status()   # turns an HTTP error into a clear Python exception

    data = response.json()["daily"]

    rainfall = pd.DataFrame({
        "date": pd.to_datetime(data["time"]),
        "rainfall_mm": data["precipitation_sum"],
    })

    # Days with no reading come back as None. Treat them as zero rather than dropping
    # them, so the calendar stays continuous.
    rainfall["rainfall_mm"] = rainfall["rainfall_mm"].fillna(0.0)

    if verbose:
        print(f"  got {len(rainfall)} days of rainfall")

    return rainfall


def summarise_rainfall(rainfall, verbose=True):
    """
    Turn the daily record into the handful of numbers the project actually uses.

    THE STATISTICS AND WHY EACH ONE
      - annual mean: the baseline everyone quotes for a city
      - monsoon share: how concentrated the rain is. In Jaipur the overwhelming majority
        falls in a few weeks, which is precisely why drainage designed for the annual
        average fails.
      - design storm: the 99th percentile of WET-DAY rainfall. Note "wet-day": including
        the ~300 dry days a year would drag the percentile down to nearly nothing and
        give you a meaningless design figure. This is a real and easy mistake to make.
      - biggest days: the specific events you can go and read news reports about, which
        is how you connect the statistics to what actually happened on the ground.
    """
    rainfall = rainfall.copy()
    rainfall["year"] = rainfall["date"].dt.year
    rainfall["month"] = rainfall["date"].dt.month

    # Only days with meaningful rain. 1 mm is the conventional threshold for a "rain day".
    wet_days = rainfall[rainfall["rainfall_mm"] >= 1.0]

    total_by_year = rainfall.groupby("year")["rainfall_mm"].sum()

    # In north-west India the south-west monsoon runs roughly June to September.
    monsoon = rainfall[rainfall["month"].isin([6, 7, 8, 9])]
    monsoon_share = monsoon["rainfall_mm"].sum() / max(rainfall["rainfall_mm"].sum(), 1e-9)

    design_storm = np.percentile(wet_days["rainfall_mm"], config.DESIGN_STORM_PERCENTILE)

    biggest = rainfall.nlargest(10, "rainfall_mm")[["date", "rainfall_mm"]]

    summary = {
        "mean_annual_mm": float(total_by_year.mean()),
        "wettest_year": int(total_by_year.idxmax()),
        "wettest_year_mm": float(total_by_year.max()),
        "driest_year": int(total_by_year.idxmin()),
        "driest_year_mm": float(total_by_year.min()),
        "monsoon_share": float(monsoon_share),
        "rain_days_per_year": float(len(wet_days) / max(len(total_by_year), 1)),
        "design_storm_mm": float(design_storm),
        "max_daily_mm": float(rainfall["rainfall_mm"].max()),
        "biggest_days": biggest,
    }

    if verbose:
        print(f"\n  Mean annual rainfall     {summary['mean_annual_mm']:.0f} mm")
        print(f"  Falls in Jun-Sep         {summary['monsoon_share'] * 100:.0f}%")
        print(f"  Rain days per year       {summary['rain_days_per_year']:.0f}")
        print(f"  Design storm (99th pct)  {summary['design_storm_mm']:.0f} mm/day")
        print(f"  Wettest day on record    {summary['max_daily_mm']:.0f} mm")
        print(f"\n  Ten wettest days — go and look these up in the local news:")
        for _, row in biggest.iterrows():
            print(f"    {row['date'].date()}   {row['rainfall_mm']:.0f} mm")

    return summary


def runoff_volume_per_cell(design_storm_mm, cell_size_m, runoff_coefficient=0.75):
    """
    How much water lands on one grid cell during the design storm, in cubic metres.

    THE RATIONAL METHOD
        runoff volume = coefficient x rainfall depth x area

    The runoff coefficient is the fraction of rain that becomes surface flow rather than
    soaking in or evaporating. Typical published values:

        0.05 - 0.20   woodland, open sandy ground
        0.20 - 0.40   parks, low-density housing with gardens
        0.40 - 0.65   suburban, mixed surfaces
        0.70 - 0.85   dense urban with widespread paving
        0.85 - 0.95   fully paved commercial centre

    We default to 0.75 for built-up Jaipur. This is a coarse assumption and you should
    label it as one — the whole point of putting it in the function signature is that a
    reader can change it and see what happens.
    """
    cell_area_m2 = cell_size_m * cell_size_m
    rainfall_metres = design_storm_mm / 1000.0

    return runoff_coefficient * rainfall_metres * cell_area_m2
