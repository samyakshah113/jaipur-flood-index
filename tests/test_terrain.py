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
    """
    dem = np.full((7, 7), 100.0)
    dem[3, 3] = 90.0                      # dig a 10 m hole in the middle

    filled = fill_depressions(dem)

    assert np.isclose(filled[3, 3], 100.0), (
        f"The pit should have filled to 100 m, but it came out at {filled[3, 3]} m"
    )
    # And nothing else should have changed.
    assert np.isclose(filled[0, 0], 100.0)


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
    """Depression depth of a 10 m pit should be 10 m, and 0 m everywhere flat."""
    dem = np.full((7, 7), 100.0)
    dem[3, 3] = 90.0

    filled = fill_depressions(dem)
    depth = depression_depth(dem, filled)

    assert np.isclose(depth[3, 3], 10.0)
    assert np.isclose(depth[0, 0], 0.0)


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
