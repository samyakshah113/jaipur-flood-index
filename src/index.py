"""
index.py — combine the measurements into a single risk score.

THE CENTRAL HONESTY PROBLEM OF THIS PROJECT
You cannot add a slope in degrees to a building count. They are different units on
different scales, and whichever happens to have bigger numbers would dominate the total
for no good reason. So every variable must first be converted onto a common 0-1 scale.
HOW you do that conversion silently decides the answer, which is why this file spends
as much space explaining the choice as making it.

Read this file properly. If someone interviews you about this project, this is where
the interesting questions are.
"""

import numpy as np
import pandas as pd

from . import config


# ----------------------------------------------------------------------------
# NORMALISATION
# ----------------------------------------------------------------------------
def percentile_normalise(values, invert=False):
    """
    Convert any set of numbers onto a 0-1 scale using their RANK, not their value.

    WHY RANK RATHER THAN MIN-MAX SCALING
    The obvious approach is min-max: (x - min) / (max - min). It has a serious flaw
    with geographic data. Flow accumulation is extremely skewed — one cell sitting on
    the Dravyavati channel might have an accumulation of 400,000 while a typical
    residential cell has 50. Min-max scaling would squash 99% of the city into the
    bottom 1% of the scale, and your map would show one bright line and nothing else.

    Percentile ranking asks "what fraction of cells score lower than this one?" instead.
    A cell in the worst 5% scores 0.95 whether the worst cell is ten times or ten
    thousand times the median. The result is a map that actually discriminates between
    neighbourhoods.

    THE TRADE-OFF, WHICH YOU SHOULD STATE OPENLY
    Ranking throws away magnitude. It can only tell you a cell is worse than 90% of
    other cells — never that it is in genuine absolute danger. This index ranks Jaipur
    against itself. It is a prioritisation tool, not an absolute hazard assessment.

    Parameters
    ----------
    invert : set True when LOW values mean HIGH risk (e.g. flat slope is bad news)
    """
    values = pd.Series(values).astype(float)

    # pct=True returns the percentile rank directly, between 0 and 1.
    # NaNs are left as NaN rather than being ranked, which is what we want.
    ranked = values.rank(pct=True, na_option="keep")

    if invert:
        ranked = 1.0 - ranked

    return ranked.values


def compute_component_scores(table, verbose=True):
    """
    Build the three components — hazard, exposure and sensitivity — from raw features.

    Each component is a weighted average of normalised variables. The weights come from
    config.py so they are visible and arguable rather than buried here.
    """
    table = table.copy()

    # Score only the urban cells. Ranking against empty countryside would compress the
    # whole city into the top of the scale and destroy the contrast we need.
    urban = table["is_urban"]

    def scored(column, invert=False):
        """Percentile-normalise a column using only urban cells as the reference set."""
        result = np.full(len(table), np.nan)
        result[urban.values] = percentile_normalise(
            table.loc[urban, column].values, invert=invert
        )
        return result

    # --- HAZARD: how likely is water to collect here? ------------------------
    hazard_parts = {
        # High TWI = flat and receiving lots of upslope water. Directly a risk.
        "twi": scored("twi"),

        # Deep local depression = nowhere for water to drain. Directly a risk.
        "depression_depth": scored("depression_depth_m"),

        # High flow accumulation = lots of runoff passes through. Directly a risk.
        "flow_accumulation": scored("flow_accumulation"),

        # INVERTED: being FAR from a mapped drain is worse, so higher distance = higher
        # risk. Distance is already "high is bad", so no inversion needed here.
        "drain_distance": scored("drain_distance_m"),

        # INVERTED: FLAT ground (low slope) drains slowly, so low slope = high risk.
        "slope": scored("slope_deg", invert=True),
    }

    hazard = sum(hazard_parts[name] * weight
                 for name, weight in config.HAZARD_WEIGHTS.items())

    # --- EXPOSURE: how much is here to be damaged? ---------------------------
    exposure_parts = {
        "building_density": scored("building_density_per_ha"),
        "road_density": scored("road_length_m"),
        "amenity_density": scored("amenity_count"),
    }

    exposure = sum(exposure_parts[name] * weight
                   for name, weight in config.EXPOSURE_WEIGHTS.items())

    # --- SENSITIVITY: how badly do people here cope? -------------------------
    # Read the caveat in docs/METHODOLOGY.md before quoting this component. These are
    # proxies for disadvantage, not measurements of it, and proxies can be wrong in
    # ways that matter to real people.
    sensitivity_parts = {
        # Very high building density with small footprints is characteristic of dense
        # and informal settlement.
        "small_building_fraction": scored("building_density_per_ha"),

        # A high share of unpaved roads indicates weaker municipal infrastructure.
        "unpaved_road_fraction": scored("unpaved_fraction"),

        # INVERTED: little or no mapped drainage nearby is worse.
        "drainage_absence": scored("drain_length_m", invert=True),
    }

    sensitivity = sum(sensitivity_parts[name] * weight
                      for name, weight in config.SENSITIVITY_WEIGHTS.items())

    table["hazard_score"] = hazard
    table["exposure_score"] = exposure
    table["sensitivity_score"] = sensitivity

    if verbose:
        print("Component scores computed (urban cells only)")
        for name in ["hazard_score", "exposure_score", "sensitivity_score"]:
            values = table.loc[urban, name]
            print(f"  {name:20s} mean {values.mean():.3f}  range {values.min():.3f}-{values.max():.3f}")

    return table


def compute_risk_index(table, weights=None, verbose=True):
    """
    The headline number: blend the three components into one 0-100 risk score.

    WHY A WEIGHTED SUM RATHER THAN A PRODUCT
    Textbook disaster risk is Hazard x Exposure x Vulnerability, and there is a real
    argument for it: somewhere with zero exposure has zero risk no matter how much it
    floods, which a sum would not capture. We use a sum anyway, for one practical reason:
    our data has gaps, and in a product a single missing or zero layer annihilates the
    whole score. A sum degrades gracefully. State this choice; do not hide it.
    """
    weights = weights or config.INDEX_WEIGHTS
    table = table.copy()

    risk = (table["hazard_score"] * weights["hazard"]
            + table["exposure_score"] * weights["exposure"]
            + table["sensitivity_score"] * weights["sensitivity"])

    # Re-rank the final blend so the output uses the full 0-100 range. Without this,
    # averaging three scores pulls everything towards the middle and the map looks flat.
    urban = table["is_urban"]
    final = np.full(len(table), np.nan)
    final[urban.values] = percentile_normalise(risk[urban].values) * 100

    table["risk_index"] = final

    # Human-readable bands. The thresholds are quintiles — deliberately RELATIVE, since
    # as explained above this index ranks Jaipur against itself.
    table["risk_band"] = pd.cut(
        table["risk_index"],
        bins=[0, 20, 40, 60, 80, 100],
        labels=["Very low", "Low", "Moderate", "High", "Very high"],
        include_lowest=True,
    )

    if verbose:
        print("\nRisk index computed.")
        counts = table.loc[urban, "risk_band"].value_counts().sort_index()
        for band, count in counts.items():
            print(f"  {band:12s} {count:5d} cells")

    return table


# ----------------------------------------------------------------------------
# SENSITIVITY ANALYSIS
# ----------------------------------------------------------------------------
def sensitivity_analysis(table, n_trials=200, seed=42, verbose=True):
    """
    Does the answer survive if the weights were different?

    THIS IS THE MOST IMPORTANT FUNCTION IN THE PROJECT AND ALMOST NOBODY DOES IT.

    The weights in config.py are a judgement call. A fair critic will say: "you chose
    hazard = 0.50; if you had chosen 0.30 you would get a different map, so why should
    I believe this one?" That is a completely reasonable objection, and the answer is
    not to argue — it is to test it.

    We re-run the index a few hundred times with randomly jiggled weights and see which
    cells stay near the top regardless. Cells that are high risk under almost every
    plausible weighting are a robust finding. Cells that jump around are an artefact of
    your assumptions, and you should say so rather than reporting them as results.

    Returns the table with two extra columns:
      rank_stability   — fraction of trials where the cell landed in the worst 10%
      rank_volatility  — spread of the cell's rank across trials (high = unreliable)
    """
    rng = np.random.default_rng(seed)
    urban_mask = table["is_urban"].values
    n_urban = urban_mask.sum()

    all_ranks = np.zeros((n_trials, n_urban))

    base = config.INDEX_WEIGHTS

    for trial in range(n_trials):
        # Perturb each weight by up to +/-50% of its value, then renormalise so the
        # three weights still sum to 1.
        perturbed = {
            key: max(value * (1 + rng.uniform(-0.5, 0.5)), 0.01)
            for key, value in base.items()
        }
        total = sum(perturbed.values())
        perturbed = {key: value / total for key, value in perturbed.items()}

        risk = (table.loc[urban_mask, "hazard_score"] * perturbed["hazard"]
                + table.loc[urban_mask, "exposure_score"] * perturbed["exposure"]
                + table.loc[urban_mask, "sensitivity_score"] * perturbed["sensitivity"])

        all_ranks[trial] = pd.Series(risk.values).rank(pct=True).values

    table = table.copy()

    stability = np.full(len(table), np.nan)
    volatility = np.full(len(table), np.nan)

    # How often did this cell land in the worst 10% across all the trials?
    stability[urban_mask] = (all_ranks >= 0.90).mean(axis=0)
    volatility[urban_mask] = all_ranks.std(axis=0)

    table["rank_stability"] = stability
    table["rank_volatility"] = volatility

    if verbose:
        always_high = (stability[urban_mask] >= 0.95).sum()
        never_high = (stability[urban_mask] <= 0.05).sum()
        print(f"\nSensitivity analysis over {n_trials} random weightings:")
        print(f"  {always_high} cells are in the worst 10% under 95%+ of weightings")
        print(f"     -> these are the robust findings you can defend")
        print(f"  {never_high} cells are essentially never high risk")
        print(f"  median rank volatility {np.nanmedian(volatility):.4f} "
              f"(lower means the conclusion depends less on your assumptions)")

    return table


def drainage_corridors(table, n=20):
    """
    Where does water physically collect? Hazard only, exposure ignored.

    WHY THIS LIST EXISTS SEPARATELY, AND WHAT IT COST TO LEARN
    The first version of this project had one list called "top priority sites", built
    from the blended risk index. Checking the results in satellite view showed almost
    every entry sitting on a nala corridor with open ground around it.

    That was not a bug in the hydrology — it is exactly right. Water collects in
    drainage corridors, and in Jaipur those corridors are often undeveloped floodplain.
    The mistake was mine, in labelling: "where water collects" and "where a municipality
    should act" are DIFFERENT QUESTIONS, and I had merged them into one list under a
    name that implied the second.

    So there are now two lists. This one is honest about being hydrology: these are the
    corridors driving flood risk across the city. They are worth knowing precisely
    because everything downstream of them depends on how they behave.
    """
    urban = table[table["is_urban"]].copy()
    urban = urban.sort_values("hazard_score", ascending=False)

    columns = ["lat", "lon", "hazard_score", "twi", "flow_accumulation",
               "depression_depth_m", "elevation_m", "relative_elevation_m",
               "drain_distance_m", "building_count", "road_length_m"]
    return urban[columns].head(n).reset_index(drop=True)


def populated_risk_areas(table, n=20, verbose=True):
    """
    Where is risk high AND people are actually there? The list to act on.

    This applies an exposure floor: a cell must sit in the top 40% of the city for
    exposure to appear here at all. See config.PRIORITY_MIN_EXPOSURE_PERCENTILE.

    NOTE ON WHAT "EXPOSURE" LEANS ON
    Because OpenStreetMap has roughly a tenth of Jaipur's buildings, exposure is driven
    mainly by road density, which is mapped properly. A 300 m cell holding 3 km of road
    is a dense street network whether or not its buildings have been surveyed. That is a
    measurement decision forced by the data, and it is written up in METHODOLOGY.md
    rather than hidden.
    """
    urban = table[table["is_urban"]].copy()

    if "exposure_score" not in urban.columns or urban["exposure_score"].isna().all():
        raise ValueError("Run compute_component_scores() before this")

    floor = urban["exposure_score"].quantile(config.PRIORITY_MIN_EXPOSURE_PERCENTILE)
    populated = urban[urban["exposure_score"] >= floor]

    if verbose:
        print(f"  exposure floor at the {config.PRIORITY_MIN_EXPOSURE_PERCENTILE:.0%} "
              f"percentile keeps {len(populated)} of {len(urban)} urban cells")

    if "rank_stability" in populated.columns:
        populated = populated.sort_values(
            ["rank_stability", "risk_index"], ascending=[False, False]
        )
    else:
        populated = populated.sort_values("risk_index", ascending=False)

    columns = ["lat", "lon", "risk_index", "risk_band",
               "hazard_score", "exposure_score", "sensitivity_score",
               "elevation_m", "relative_elevation_m", "twi",
               "depression_depth_m", "drain_distance_m",
               "building_count", "road_length_m"]
    if "rank_stability" in populated.columns:
        columns.append("rank_stability")

    return populated[columns].head(n).reset_index(drop=True)
