"""
test_terrain.py — proof that the hydrology actually works.

WHY WRITE TESTS AT ALL?
Because a flood map that is silently wrong looks exactly like a flood map that is right.
The only way to know your algorithms are correct is to run them on a landscape whose
answer you already know, and check they give that answer.

Having tests in your repository is also, bluntly, one of the fastest ways to signal to
anyone reading your GitHub that you know what you are doing. Most student projects have
none. Run them with:   python -m pytest tests/ -v
"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.terrain import (
    fill_depressions,
    depression_depth,
    flow_direction_d8,
    flow_accumulation,
    compute_slope,
    topographic_wetness_index,
    analyse_terrain,
)


def test_fill_depressions_fills_a_known_pit():
    """
    Build a flat plain at 100 m with one cell dug down to 90 m.
    After filling, that pit must rise back to the level of the plain around it.

    NOTE ON THE TOLERANCE: filling deliberately adds a 1 mm epsilon per cell so that
    filled areas slope gently towards their outlet instead of being perfectly flat.
    Without it, water cannot cross filled ground at all (see the flat-routing test
    below). So the pit lands a few millimetres above 100 m, not exactly on it, and
    the tolerance here has to allow for that.
    """
    dem = np.full((7, 7), 100.0)
    dem[3, 3] = 90.0                      # dig a 10 m hole in the middle

    filled = fill_depressions(dem)

    assert 100.0 <= filled[3, 3] < 100.05, (
        f"The pit should have filled to just over 100 m, got {filled[3, 3]} m"
    )
    # And nothing else should have moved more than the epsilon.
    assert 100.0 <= filled[0, 0] < 100.05


def test_fill_depressions_does_not_flatten_real_hills():
    """
    A hill is not a pit. Filling must leave high ground exactly as it was, otherwise
    we would be destroying the very terrain we are trying to analyse.
    """
    dem = np.full((7, 7), 100.0)
    dem[3, 3] = 150.0                     # a peak, not a hole

    filled = fill_depressions(dem)

    assert np.isclose(filled[3, 3], 150.0), "Filling must never lower a hilltop"


def test_depression_depth_measures_the_hole():
    """
    Depression depth of a 10 m pit should be 10 m, give or take the fill epsilon.
    """
    dem = np.full((7, 7), 100.0)
    dem[3, 3] = 90.0

    filled = fill_depressions(dem)
    depth = depression_depth(dem, filled)

    assert 10.0 <= depth[3, 3] < 10.05, f"expected about 10 m, got {depth[3, 3]}"
    assert depth[0, 0] < 0.05


def test_water_can_cross_filled_ground():
    """
    THE REGRESSION TEST FOR THE WORST BUG IN THIS PROJECT.

    Build a basin with a wide flat floor and a single outlet on the left edge.
    Physically, rain landing anywhere in that basin has exactly one way out, so a
    large share of the map must drain through cells near the outlet.

    The original implementation filled depressions to a PERFECTLY FLAT surface. D8
    routing needs a strictly downhill neighbour, and flat ground offers none, so every
    flow path stopped at the edge of the filled area. Measured: 6 cells out of 3,600
    reached the busiest point, and 3,479 cells had nowhere to drain at all.

    On real Jaipur data the symptom was subtler and easier to miss - flow accumulation
    peaked at 478 across a 590,000-pixel map, where a main channel should carry tens of
    thousands. Nothing errored. The maps looked perfectly reasonable.

    Filling now adds a 1 mm gradient per cell, so filled ground slopes back towards its
    outlet. This test fails loudly if that is ever removed.
    """
    size = 60
    dem = np.zeros((size, size))
    for r in range(size):
        for c in range(size):
            distance_from_centre = max(abs(r - size // 2), abs(c - size // 2))
            # Flat inside a radius of 15 cells, rising walls outside it.
            dem[r, c] = 100.0 + max(distance_from_centre - 15, 0) * 1.5
    dem[size // 2, 0] = 90.0          # the single outlet

    result = analyse_terrain(dem, cell_size_m=30)
    accumulation = result["flow_accumulation"]
    stranded = (result["flow_direction"] == -1).sum()

    total_cells = size * size

    assert accumulation.max() > total_cells * 0.10, (
        f"Only {accumulation.max():.0f} of {total_cells} cells drain through the "
        f"busiest point. Water is not crossing the filled basin floor - the fill "
        f"epsilon has probably been removed."
    )
    assert stranded < total_cells * 0.10, (
        f"{stranded} of {total_cells} cells have no downhill neighbour. Filled ground "
        f"is flat and water is stuck on it."
    )


def test_fill_epsilon_stays_negligible():
    """
    The epsilon must never grow large enough to invent terrain.

    SRTM elevation is accurate to roughly 5 m vertically. The gradient we add to make
    filled ground drainable has to stay far below that, or we would be fixing one
    problem by manufacturing an invisible one.

    A PERFECTLY FLAT plane is the strict test: every cell qualifies for the epsilon, so
    it accumulates across the entire grid and we see the worst case. Random terrain
    would not work here - it contains genuine pits whose filling is metres deep and
    entirely correct, which would swamp the thing we are trying to measure.
    """
    dem = np.full((50, 50), 400.0)

    filled = fill_depressions(dem)
    added = filled - dem

    assert added.max() < 0.1, (
        f"Epsilon accumulated to {added.max():.4f} m across a flat plane. It should "
        f"stay far below the ~5 m accuracy of the elevation data."
    )


def test_filling_leaves_pit_free_terrain_alone():
    """
    On a slope with no depressions at all, filling should change nothing.

    This checks the epsilon is only applied where it is needed - inside pits - rather
    than being sprinkled over the whole map.
    """
    dem = np.array([[500.0 - r * 2.0 - c * 0.5 for c in range(30)] for r in range(30)])

    filled = fill_depressions(dem)

    assert np.allclose(filled, dem, atol=1e-9), (
        "Terrain that drains perfectly well was modified by the filling step"
    )


def test_flow_runs_downhill_not_uphill():
    """
    On a simple ramp that slopes down towards the south (increasing row index),
    every cell must send its water south. If any cell routes north, the sign
    convention is inverted somewhere — a bug that would flip the entire map.
    """
    # Row 0 is highest at 110 m, each row 2 m lower going down.
    dem = np.array([[110.0 - 2 * r] * 6 for r in range(6)])

    filled = fill_depressions(dem)
    flow_dir = flow_direction_d8(filled, cell_size_m=30)

    # Direction index 6 is (row+1, col+0) — i.e. straight "south" in array terms.
    # Check an interior cell, away from edge effects.
    assert flow_dir[2, 3] == 6, (
        f"Water should flow to direction 6 (downhill), got {flow_dir[2, 3]}"
    )


def test_flow_accumulation_concentrates_in_a_valley():
    """
    THE MOST IMPORTANT TEST IN THE FILE.

    Build a V-shaped valley running north-south. Physically, water from both hillsides
    must collect along the valley floor. So the valley floor cells must have a much
    higher flow accumulation than the hillside cells. If this fails, every flood map the
    project produces is meaningless.
    """
    size = 21
    dem = np.zeros((size, size))
    valley_col = size // 2

    for r in range(size):
        for c in range(size):
            # Distance from the valley centre line drives the height of the walls.
            distance_from_centre = abs(c - valley_col)
            # Plus a gentle slope down the length of the valley so water has somewhere to go.
            dem[r, c] = 100.0 + distance_from_centre * 2.0 - r * 0.5

    result = analyse_terrain(dem, cell_size_m=30)
    acc = result["flow_accumulation"]

    # Compare the valley floor to the hillside, halfway down the valley.
    valley_floor = acc[15, valley_col]
    hillside = acc[15, valley_col + 7]

    assert valley_floor > hillside * 5, (
        f"Valley floor accumulation ({valley_floor:.0f}) should dwarf the hillside "
        f"({hillside:.0f}). Water is not collecting where it physically must."
    )


def test_twi_is_highest_where_it_is_flat_and_wet():
    """
    TWI must rank a flat, low, water-collecting spot above a steep hillside.
    This is the property the entire risk index leans on.
    """
    size = 21
    dem = np.zeros((size, size))
    valley_col = size // 2

    for r in range(size):
        for c in range(size):
            distance_from_centre = abs(c - valley_col)
            dem[r, c] = 100.0 + distance_from_centre * 2.0 - r * 0.5

    result = analyse_terrain(dem, cell_size_m=30)
    twi = result["twi"]

    assert twi[15, valley_col] > twi[15, valley_col + 7], (
        "TWI should be higher on the valley floor than on the hillside"
    )


def test_twi_survives_perfectly_flat_ground():
    """
    A completely flat DEM has zero slope everywhere. Without the minimum-slope guard
    in topographic_wetness_index() this would divide by zero and fill the map with
    infinities. Check that it does not.
    """
    dem = np.full((10, 10), 100.0)
    result = analyse_terrain(dem, cell_size_m=30)

    assert np.all(np.isfinite(result["twi"])), (
        "TWI produced infinite or NaN values on flat ground — the divide-by-zero "
        "guard is not working"
    )


def test_slope_of_a_known_ramp_is_correct():
    """
    A ramp that drops 1 m for every 10 m travelled has a slope of arctan(0.1) = 5.71 deg.
    Checking a known angle catches the classic degrees/radians mix-up.
    """
    # 10 m cells, dropping 1 m per cell = gradient of 0.1
    dem = np.array([[100.0 - 1.0 * c for c in range(10)] for _ in range(10)])

    slope = compute_slope(dem, cell_size_m=10)
    expected = np.degrees(np.arctan(0.1))

    # Check an interior cell (edges use one-sided differences and are less exact).
    assert np.isclose(slope[5, 5], expected, atol=0.01), (
        f"Expected {expected:.2f} degrees, got {slope[5, 5]:.2f}"
    )


def test_flow_accumulation_conserves_water():
    """
    A physical sanity check. Every cell contributes exactly 1 unit of rain, so the
    accumulation at any cell can never exceed the total number of cells on the map.
    A violation would mean water is being created out of nothing.
    """
    rng = np.random.default_rng(42)
    dem = 100 + rng.random((15, 15)) * 20

    result = analyse_terrain(dem, cell_size_m=30)
    acc = result["flow_accumulation"]

    assert acc.max() <= dem.size, (
        f"Maximum accumulation {acc.max()} exceeds the {dem.size} cells on the map — "
        "water is being invented"
    )
    assert acc.min() >= 1.0, "Every cell must contribute at least its own rainfall"


if __name__ == "__main__":
    # Lets you run this file directly with `python tests/test_terrain.py`
    # even if you have not installed pytest yet.
    import traceback

    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = failed = 0

    for test in tests:
        try:
            test()
            print(f"  PASS  {test.__name__}")
            passed += 1
        except Exception:
            print(f"  FAIL  {test.__name__}")
            traceback.print_exc()
            failed += 1

    print(f"\n{passed} passed, {failed} failed")
