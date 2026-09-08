"""
terrain.py — the hydrology. This is the scientific core of the project.

THE IDEA IN ONE PARAGRAPH
Water does not flood randomly. It runs downhill, collects in dips, and pools where
the ground is flat and a lot of upstream land drains through. Those three things —
"is this a dip?", "how much land drains through here?", "how flat is it?" — can all
be computed from an elevation map using algorithms that hydrologists have used since
the 1980s. That is what this file does. None of it is guesswork; it is the same
maths that sits inside professional GIS software like QGIS and ArcGIS.

If you can explain the four functions below in an interview, you understand more
about flood modelling than most people who put "GIS" on a CV.
"""

import heapq
import numpy as np


# ============================================================================
# STEP 1: FILL THE SINKS
# ============================================================================
def fill_depressions(dem, epsilon=1e-3):
    """
    Remove artificial pits from the elevation map, leaving a faint slope behind.

    WHY THE EPSILON MATTERS ENORMOUSLY (this was a real bug, found by checking output)
    A plain fill makes every filled depression perfectly, exactly flat. That seems
    harmless until the next step: D8 routing sends water to the steepest DOWNHILL
    neighbour, and on perfectly flat ground no neighbour is downhill at all. So flow
    stops dead at the edge of every filled pit.

    Measured on a test basin with a flat floor and one outlet: water from 3,600 cells
    should reach that outlet. Without an epsilon, the busiest cell saw 6. On real
    Jaipur data, flow accumulation peaked at 478 across a 590,000-pixel map, when a
    main drainage channel should carry tens of thousands.

    The fix is to raise each filled cell a hair ABOVE the water level it was reached
    at, rather than exactly to it. Because Priority-Flood processes cells outward from
    the outlet, this leaves filled areas sloping gently back towards where the water
    would actually leave. 1 mm per cell is far below the accuracy of the elevation
    data, so it changes no real terrain — it just gives the router a direction to
    follow.

    THE ALGORITHM: Priority-Flood (Barnes, Lehman & Mulla, 2014)
    Think of the map as a landscape and imagine flooding it from the edges inward.
    You always process the LOWEST unvisited cell on the current shoreline. When you
    step to a neighbour, its filled elevation is whichever is higher: its own real
    elevation, or the water level you arrived at. That single rule fills every pit
    correctly in one pass.

    WHY THIS IS NEEDED
    Elevation data has errors. A single pixel that is wrongly 2 m too low becomes a
    "sink" — a cell with no downhill neighbour. Water flowing into it disappears, and
    the whole flow-accumulation calculation downstream of it is wrong. So before doing
    anything else, hydrologists "fill" these pits, like pouring water into every hollow
    until it can spill out over the lowest rim.

    THE ALGORITHM: Priority-Flood (Barnes, Lehman & Mulla, 2014)
    Think of the map as a landscape and imagine flooding it from the edges inward.
    You always process the LOWEST unvisited cell on the current shoreline. When you
    step to a neighbour, its filled elevation is whichever is higher: its own real
    elevation, or the water level you arrived at. That single rule fills every pit
    correctly in one pass.

    A "priority queue" (heapq) is what lets us always grab the lowest cell cheaply.

    Parameters
    ----------
    dem : 2-D numpy array of elevations in metres
    epsilon : the gradient added per cell across filled areas, in metres.
              1e-3 (1 mm) is far below the ~5 m vertical accuracy of SRTM, so it
              cannot invent terrain. Set it to 0 to reproduce the flat-fill bug.

    Returns
    -------
    2-D numpy array, same shape, with all pits filled and drainable
    """
    rows, cols = dem.shape
    filled = np.full(dem.shape, np.inf)      # start with "unknown = infinitely high"
    visited = np.zeros(dem.shape, dtype=bool)

    heap = []  # our priority queue of (elevation, row, col)

    # Seed the queue with every cell on the outer edge of the map.
    # Water can always escape off the edge, so these keep their real elevation.
    for r in range(rows):
        for c in range(cols):
            on_edge = (r == 0 or r == rows - 1 or c == 0 or c == cols - 1)
            if on_edge:
                heapq.heappush(heap, (dem[r, c], r, c))
                filled[r, c] = dem[r, c]
                visited[r, c] = True

    # The 8 directions you can step from a cell (like a chess king).
    neighbours = [(-1, -1), (-1, 0), (-1, 1),
                  (0, -1),           (0, 1),
                  (1, -1),  (1, 0),  (1, 1)]

    while heap:
        elevation, r, c = heapq.heappop(heap)   # always the lowest cell available

        for dr, dc in neighbours:
            nr, nc = r + dr, c + dc

            # Skip anything off the edge of the array or already done.
            if not (0 <= nr < rows and 0 <= nc < cols) or visited[nr, nc]:
                continue

            # THE KEY LINES. The neighbour's filled height is the higher of:
            #   - its own true elevation, or
            #   - the water level we arrived carrying, plus epsilon.
            #
            # That "plus epsilon" is the whole fix. If the neighbour sits below the
            # water we arrived with, it was inside a pit: rather than levelling it to
            # exactly our height (which produces flat ground water cannot cross), we
            # set it a hair higher than us. Since we are working outward from the
            # outlet, "a hair higher than the cell before" means the filled surface
            # slopes back down towards the outlet, and D8 can follow it out.
            if dem[nr, nc] <= elevation:
                filled[nr, nc] = elevation + epsilon
            else:
                filled[nr, nc] = dem[nr, nc]

            visited[nr, nc] = True
            heapq.heappush(heap, (filled[nr, nc], nr, nc))

    return filled


def depression_depth(dem, filled_dem):
    """
    How deep a hollow is each cell sitting in?

    This is simply (filled elevation - original elevation). A cell in the middle of a
    natural bowl might come out at 3 m; a cell on a ridge comes out at 0 m.

    This turns out to be one of the most intuitive flood indicators there is, and it is
    worth showing on your map: these are literally the places water has nowhere to go.
    """
    return filled_dem - dem


# ============================================================================
# STEP 2: WHICH WAY DOES WATER FLOW?
# ============================================================================
def flow_direction_d8(filled_dem, cell_size_m):
    """
    For every cell, decide which of its 8 neighbours water flows into.

    THE D8 METHOD
    "D8" = eight directions. It is the simplest flow-routing model: all the water in a
    cell goes to whichever single neighbour is steepest downhill. Real water spreads
    across multiple directions, and there are fancier models (D-infinity, MFD) that
    handle that. D8 is the standard teaching model, it is fast, and its weaknesses are
    well documented — which makes it an honest choice as long as you SAY it is D8.

    IMPORTANT DETAIL
    Diagonal neighbours are further away (by a factor of sqrt(2) = 1.414), so we compare
    SLOPE (drop / distance), not raw drop. Forgetting this is the classic beginner bug
    and it biases all your flow paths diagonally.

    Returns
    -------
    A 2-D array where each cell holds the index (0-7) of the direction it drains to,
    or -1 if it has no downhill neighbour at all.
    """
    rows, cols = filled_dem.shape
    directions = np.full(filled_dem.shape, -1, dtype=np.int8)

    neighbours = [(-1, -1), (-1, 0), (-1, 1),
                  (0, -1),           (0, 1),
                  (1, -1),  (1, 0),  (1, 1)]

    # Straight steps cover one cell width; diagonal steps cover sqrt(2) cell widths.
    distances = [cell_size_m * np.sqrt(2), cell_size_m, cell_size_m * np.sqrt(2),
                 cell_size_m,                            cell_size_m,
                 cell_size_m * np.sqrt(2), cell_size_m, cell_size_m * np.sqrt(2)]

    for r in range(rows):
        for c in range(cols):
            steepest_slope = 0.0
            best_direction = -1

            for i, (dr, dc) in enumerate(neighbours):
                nr, nc = r + dr, c + dc
                if not (0 <= nr < rows and 0 <= nc < cols):
                    continue

                drop = filled_dem[r, c] - filled_dem[nr, nc]
                if drop <= 0:
                    continue          # neighbour is higher or level — water won't go there

                slope = drop / distances[i]
                if slope > steepest_slope:
                    steepest_slope = slope
                    best_direction = i

            directions[r, c] = best_direction

    return directions


# ============================================================================
# STEP 3: HOW MUCH LAND DRAINS THROUGH EACH CELL?
# ============================================================================
def flow_accumulation(filled_dem, flow_dir):
    """
    Count how many upstream cells ultimately drain through each cell.

    WHY THIS MATTERS
    A cell with a flow accumulation of 5 gets rain from a patch the size of a cricket
    pitch. A cell with an accumulation of 5,000 is sitting in a natural drainage channel
    collecting runoff from half a square kilometre. When a storm hits, those are two
    completely different situations even if the two cells look identical from the street.

    THE TRICK THAT MAKES THIS FAST
    Process cells from HIGHEST to LOWEST. By the time you reach any cell, every cell
    that drains into it has already been counted, so you can just pass your running
    total downstream. One pass, no recursion, no risk of infinite loops.

    Returns
    -------
    2-D array; each value is the number of cells draining through that cell (including
    itself, so the minimum is 1).
    """
    rows, cols = filled_dem.shape

    # Every cell starts by contributing its own single cell of rainfall.
    accumulation = np.ones(filled_dem.shape, dtype=np.float64)

    neighbours = [(-1, -1), (-1, 0), (-1, 1),
                  (0, -1),           (0, 1),
                  (1, -1),  (1, 0),  (1, 1)]

    # Get the (row, col) of every cell, sorted from highest elevation to lowest.
    flat_order = np.argsort(filled_dem.ravel())[::-1]   # [::-1] reverses = descending

    for flat_index in flat_order:
        r, c = divmod(flat_index, cols)
        d = flow_dir[r, c]

        if d == -1:
            continue            # nowhere to send the water (edge or flat sink)

        dr, dc = neighbours[d]
        nr, nc = r + dr, c + dc

        if 0 <= nr < rows and 0 <= nc < cols:
            accumulation[nr, nc] += accumulation[r, c]   # hand the water downstream

    return accumulation


# ============================================================================
# STEP 4: SLOPE AND WETNESS
# ============================================================================
def compute_slope(dem, cell_size_m):
    """
    Steepness of the ground at every cell, in degrees.

    Uses numpy's gradient function, which estimates the rate of change in the x and y
    directions by comparing each cell to its neighbours. Combining the two with
    Pythagoras gives the steepest slope in any direction.

    Flat ground (low slope) drains slowly, so water sits on it. That is why slope is a
    flood variable and not just scenery.
    """
    # np.gradient returns change-per-cell; dividing by cell size gives change-per-metre.
    dy, dx = np.gradient(dem, cell_size_m)

    # Total steepness = sqrt(rise_x^2 + rise_y^2). arctan turns that ratio into an angle.
    slope_radians = np.arctan(np.sqrt(dx ** 2 + dy ** 2))
    return np.degrees(slope_radians)


def topographic_wetness_index(flow_acc, slope_degrees, cell_size_m):
    """
    The Topographic Wetness Index (TWI) — the single most useful number in this project.

    THE FORMULA
        TWI = ln( a / tan(beta) )

    where 'a' is the upslope area draining through a unit width of contour, and 'beta'
    is the local slope. Introduced by Beven & Kirkby in 1979 for a rainfall-runoff model
    and now used everywhere from soil-moisture mapping to flood-risk screening.

    WHAT IT MEANS INTUITIVELY
    The fraction gets big in two situations:
      - the top gets big  -> lots of water arrives from upstream
      - the bottom gets small -> the ground is flat, so water leaves slowly
    Somewhere that is BOTH low-lying and flat scores very high. That describes almost
    every chronic waterlogging spot in a city. The natural logarithm just squashes a
    very wide range of values into something you can put on a colour scale.

    THE TWO NUMERICAL TRAPS (both handled below)
      1. tan(0) = 0, and dividing by zero gives infinity. Perfectly flat cells would
         blow up. We impose a small minimum slope.
      2. Slope must be in RADIANS before you call tan(). Passing degrees is a silent,
         very common bug — the code runs fine and every number is wrong.
    """
    slope_radians = np.radians(slope_degrees)

    # Trap 1: never let the slope be exactly zero. 0.001 rad is about 0.06 degrees —
    # far flatter than any real terrain, so this changes nothing except the divide-by-zero.
    slope_radians = np.maximum(slope_radians, 0.001)

    # 'a' = upslope contributing AREA per unit contour WIDTH.
    # area  = number of cells x area of one cell
    # width = one cell width
    upslope_area_per_width = (flow_acc * cell_size_m * cell_size_m) / cell_size_m

    return np.log(upslope_area_per_width / np.tan(slope_radians))


# ============================================================================
# CONVENIENCE WRAPPER
# ============================================================================
def analyse_terrain(dem, cell_size_m):
    """
    Run the whole terrain analysis in the correct order and return everything.

    Order matters and is not arbitrary:
      fill sinks -> flow directions -> flow accumulation -> TWI
    You cannot compute flow directions on an unfilled DEM (pits break it), and you
    cannot compute TWI without flow accumulation. Getting this order wrong is the most
    common way people produce a map that looks plausible but is meaningless.
    """
    filled = fill_depressions(dem)
    depth = depression_depth(dem, filled)
    slope = compute_slope(filled, cell_size_m)
    flow_dir = flow_direction_d8(filled, cell_size_m)
    flow_acc = flow_accumulation(filled, flow_dir)
    twi = topographic_wetness_index(flow_acc, slope, cell_size_m)

    return {
        "elevation": dem,
        "filled_elevation": filled,
        "depression_depth": depth,
        "slope": slope,
        "flow_direction": flow_dir,
        "flow_accumulation": flow_acc,
        "twi": twi,
    }
