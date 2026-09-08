"""
validate.py — test the index against places that really flooded.

THIS FILE IS WHAT SEPARATES A PROJECT FROM A POSTER.

Anyone can produce a colourful map. The question a reviewer, an admissions reader, or
a municipal engineer will ask is: "how do you know it is right?" Without an answer,
your map is a well-decorated opinion.

The answer is ground truth. You collect a list of places in Jaipur that genuinely
waterlogged, and a list that genuinely did not, and you check whether your index scored
the first group higher than the second. If it did not, you say so and investigate why.
A validated model with an honest AUC of 0.71 is worth vastly more than an unvalidated
one that claims 95% accuracy.

See docs/HOW_TO_COLLECT_GROUND_TRUTH.md for how to build the observation list.
"""

import numpy as np
import pandas as pd

from . import config
from .features import latlon_to_cell


def load_observations(path=None):
    """
    Load your field observations.

    Expected CSV columns:
        name       — what to call the place, e.g. "Sindhi Camp underpass"
        lat, lon   — coordinates (get them by right-clicking in Google Maps)
        flooded    — 1 if it waterlogs, 0 if it reliably does not
        source     — where you learned this: a news URL, "personal observation",
                     a photo, a neighbour. Recording this is what makes it evidence
                     rather than assertion.
        date       — optional, when it was observed
    """
    path = path or config.GROUND_TRUTH_CSV

    observations = pd.read_csv(path)

    required = {"name", "lat", "lon", "flooded"}
    missing = required - set(observations.columns)
    if missing:
        raise ValueError(f"Your observations CSV is missing these columns: {missing}")

    # A file with only flooded points cannot validate anything — see check_balance().
    return observations


def check_balance(observations, verbose=True):
    """
    Warn about the mistake that quietly ruins most student validation attempts.

    If you only record places that DID flood, your model can score 100% by declaring
    the entire city high risk. You need negative examples: places that stayed dry
    during the same storm. They are less memorable, harder to find, and absolutely
    essential.

    A useful trick for negatives: photos and news reports from a big storm often show
    a flooded road AND, in the background, a dry one. Nearby streets that nobody
    complained about are also legitimate negatives.
    """
    n_flooded = int((observations["flooded"] == 1).sum())
    n_dry = int((observations["flooded"] == 0).sum())

    if verbose:
        print(f"Ground truth: {n_flooded} flooded, {n_dry} dry")

    problems = []
    if n_dry == 0:
        problems.append(
            "You have no dry observations. Validation is impossible without them — "
            "a model that calls everywhere high risk would score perfectly."
        )
    if n_flooded < 10 or n_dry < 10:
        problems.append(
            "Fewer than 10 in one class. Any accuracy figure will be dominated by "
            "noise. Aim for at least 20 of each before quoting a number."
        )
    if n_dry > 0 and (n_flooded / n_dry > 4 or n_dry / n_flooded > 4):
        problems.append(
            "The classes are very unbalanced. Prefer AUC over accuracy, and say so."
        )

    if verbose:
        for problem in problems:
            print(f"  WARNING: {problem}")

    return {"n_flooded": n_flooded, "n_dry": n_dry, "problems": problems}


def attach_scores(observations, table, grid):
    """
    Look up the model's risk score at each observed location.

    Points that fall outside the study area, or in a cell classified as non-urban,
    are dropped with a note. Silently keeping them would corrupt the evaluation.
    """
    lookup = table.set_index(["row", "col"])

    scores, bands, found = [], [], []

    for _, observation in observations.iterrows():
        row, col = latlon_to_cell(observation["lat"], observation["lon"], grid)

        if row is None or (row, col) not in lookup.index:
            scores.append(np.nan)
            bands.append(None)
            found.append(False)
            continue

        cell = lookup.loc[(row, col)]
        scores.append(cell["risk_index"])
        bands.append(cell["risk_band"])
        found.append(True)

    result = observations.copy()
    result["risk_index"] = scores
    result["risk_band"] = bands
    result["found_in_grid"] = found

    n_lost = (~np.array(found)).sum()
    if n_lost:
        print(f"  note: {n_lost} observations fell outside the study grid and were dropped")

    return result.dropna(subset=["risk_index"])


def roc_auc(observations, verbose=True):
    """
    The headline validation number: Area Under the ROC Curve.

    WHAT AUC ACTUALLY MEANS — the intuitive definition, which is the one to quote:
    Pick one flooded location and one dry location at random. AUC is the probability
    that your index gave the flooded one a higher score.

        0.50  no better than a coin flip — your index has no signal
        0.65  weak but real
        0.75  respectable for a screening tool built from open data
        0.85  strong
        1.00  perfect (and if you get this, suspect a bug or data leakage first)

    WHY AUC RATHER THAN ACCURACY
    Accuracy depends on where you set the cut-off, and it can be gamed by an unbalanced
    dataset — if 90% of your points flooded, saying "everything floods" scores 90%. AUC
    is threshold-free and unaffected by class balance. For a ranking tool like this one,
    it is simply the right metric.
    """
    flooded = observations[observations["flooded"] == 1]["risk_index"].values
    dry = observations[observations["flooded"] == 0]["risk_index"].values

    if len(flooded) == 0 or len(dry) == 0:
        raise ValueError("Need at least one flooded and one dry observation to compute AUC")

    # Compute it directly from the definition: count every flooded/dry pair and check
    # how often the flooded one scored higher. Ties count as half a win, which is the
    # standard convention. Doing it this way instead of calling a library function is
    # slower, but it means you can explain exactly what the number is.
    wins = 0.0
    for f in flooded:
        wins += np.sum(f > dry) + 0.5 * np.sum(f == dry)

    auc = wins / (len(flooded) * len(dry))

    if verbose:
        print(f"\n  AUC = {auc:.3f}")
        print(f"  Interpretation: given one flooded and one dry location at random,")
        print(f"  the index ranks the flooded one higher {auc * 100:.0f}% of the time.")

        if auc < 0.6:
            print("  -> Weak. Do not present this as a working model. Investigate:")
            print("     is your ground truth accurate? are the weights wrong?")
            print("     is 300 m too coarse to capture street-level drainage?")
        elif auc < 0.75:
            print("  -> Moderate signal. Honest and reportable, with caveats.")
        else:
            print("  -> Strong for a screening index built entirely from open data.")

    return float(auc)


def bootstrap_confidence_interval(observations, n_bootstrap=2000, seed=42, verbose=True):
    """
    How much would the AUC change if you had collected a slightly different sample?

    WHY THIS MATTERS ENORMOUSLY WITH SMALL DATA
    If you validated on 25 points, your AUC is measured with big error bars. Quoting
    "AUC 0.78" as though it were exact is overclaiming. Quoting "AUC 0.78, 95% CI
    0.61-0.91" is honest, and it immediately tells a reader the sample is small.

    BOOTSTRAPPING, in one sentence: resample your observations WITH REPLACEMENT a few
    thousand times, recompute the statistic each time, and look at the spread. It is a
    remarkably general technique for putting error bars on almost anything.
    """
    rng = np.random.default_rng(seed)
    n = len(observations)
    aucs = []

    for _ in range(n_bootstrap):
        sample = observations.iloc[rng.integers(0, n, size=n)]

        # A resample can by chance contain only one class; skip those draws.
        if sample["flooded"].nunique() < 2:
            continue

        aucs.append(roc_auc(sample, verbose=False))

    aucs = np.array(aucs)
    lower, upper = np.percentile(aucs, [2.5, 97.5])

    if verbose:
        print(f"  95% confidence interval: {lower:.3f} to {upper:.3f}")
        if lower < 0.5:
            print("  -> The interval includes 0.50, which means you cannot rule out")
            print("     that the index is no better than chance. Collect more points.")

    return {"auc_mean": float(aucs.mean()), "ci_lower": float(lower), "ci_upper": float(upper)}


def compare_against_baselines(observations, table, grid, verbose=True):
    """
    Is the whole composite index actually better than one obvious variable?

    THE QUESTION EVERY GOOD REVIEWER ASKS
    You built a five-variable weighted hazard score blended with exposure and
    sensitivity. Does it beat simply "how low is this spot relative to its surroundings"?
    If it does not, all the extra machinery is decoration, and the honest thing is to
    report the simple version.

    This is called baseline comparison and skipping it is how people fool themselves
    into thinking a complicated model is doing something.
    """
    lookup = table.set_index(["row", "col"])
    baselines = {}

    candidates = {
        "elevation only (lower = riskier)": ("elevation_m", True),
        "relative elevation only": ("relative_elevation_m", True),
        "TWI only": ("twi", False),
        "building density only": ("building_density_per_ha", False),
    }

    for label, (column, invert) in candidates.items():
        values = []
        for _, observation in observations.iterrows():
            row, col = latlon_to_cell(observation["lat"], observation["lon"], grid)
            if row is None or (row, col) not in lookup.index:
                values.append(np.nan)
            else:
                value = lookup.loc[(row, col)][column]
                values.append(-value if invert else value)

        subset = observations.copy()
        subset["risk_index"] = values
        subset = subset.dropna(subset=["risk_index"])

        if subset["flooded"].nunique() < 2:
            continue

        baselines[label] = roc_auc(subset, verbose=False)

    full_auc = roc_auc(observations, verbose=False)
    baselines["FULL COMPOSITE INDEX"] = full_auc

    if verbose:
        print("\n  Baseline comparison (AUC — higher is better):")
        for label, auc in sorted(baselines.items(), key=lambda item: -item[1]):
            marker = "  <-- our model" if "COMPOSITE" in label else ""
            print(f"    {auc:.3f}   {label}{marker}")

        best_simple = max(v for k, v in baselines.items() if "COMPOSITE" not in k)
        if full_auc <= best_simple:
            print("\n  IMPORTANT: a single variable does as well as the full index.")
            print("  Report this honestly. It is a real and interesting finding, not a")
            print("  failure — it says the composite structure is not earning its keep.")
        else:
            gain = full_auc - best_simple
            print(f"\n  The composite index beats the best single variable by {gain:.3f} AUC.")

    return baselines


def full_validation_report(observations_path, table, grid):
    """Run every check in this file and return the results together."""
    print("=" * 70)
    print("VALIDATION AGAINST OBSERVED WATERLOGGING")
    print("=" * 70)

    observations = load_observations(observations_path)
    balance = check_balance(observations)

    scored = attach_scores(observations, table, grid)
    if scored["flooded"].nunique() < 2:
        print("\nCannot validate: after matching to the grid, only one class remains.")
        return None

    auc = roc_auc(scored)
    confidence = bootstrap_confidence_interval(scored)
    baselines = compare_against_baselines(scored, table, grid)

    return {
        "balance": balance,
        "auc": auc,
        "confidence_interval": confidence,
        "baselines": baselines,
        "scored_observations": scored,
    }
