# -*- coding: utf-8 -*-
"""
Pure-numpy hydrology routines for reservoir analysis.

Nothing in this module depends on QGIS or GDAL, so it can be unit tested
in isolation.

Method
------
A reservoir created by a dam is the set of DEM cells that are hydraulically
connected to the upstream face of the dam and lie below the water level.
We compute, with a *priority flood* started from the lowest cell just
upstream of the dam, the **spill level** of every cell: the lowest water
level at which that cell becomes connected to the dam.  The dam axis is burnt
into the grid as an impassable barrier.

Once the spill level ``s`` of every cell is known, the whole
elevation-area-capacity (EAC) relation follows from a single sort::

    A(h) = a * #{cells : s <= h}
    V(h) = a * sum_{s <= h} (h - z) = a * (h * n(h) - sum_{s <= h} z)

where ``a`` is the cell area.  Isolated depressions that are not connected
to the reservoir are therefore never counted (unlike simple
"all pixels below h" approaches).

The flood stops when the water finds another way out, which defines the
**maximum impoundable level** of the dam axis:

* ``bypass``  - water flows around the dam (dam ends too low or a saddle),
* ``edge``    - the reservoir reaches the edge of the analysed DEM window,
* ``nodata``  - the reservoir reaches a DEM void,
* ``max_level`` - a user-defined ceiling was reached first.
"""

import heapq
import math
from array import array

import numpy as np

# Flood stop reasons
STOP_BYPASS = 'bypass'
STOP_EDGE = 'edge'
STOP_NODATA = 'nodata'
STOP_MAX_LEVEL = 'max_level'
STOP_CELL_LIMIT = 'cell_limit'
STOP_EXHAUSTED = 'exhausted'

_OPEN_EDGE = 1
_OPEN_NODATA = 2


class Cancelled(Exception):
    """Raised when the caller requested cancellation."""


class FloodResult:
    """Outcome of a priority flood.

    Attributes
    ----------
    spill : np.ndarray (float64, grid shape)
        Spill level of every finalised cell, ``inf`` elsewhere.
    limit_level : float
        Level at which the flood stopped (see ``reason``).
    reason : str
        One of the ``STOP_*`` constants.
    stop_cell : tuple or None
        (row, col) of the cell that triggered the stop, if any.
    pour_cell : tuple or None
        (row, col) of the cell that last raised the water level - at the
        stop this is the saddle / spill point controlling ``limit_level``.
    n_cells : int
        Number of finalised cells.
    """

    def __init__(self, spill, limit_level, reason, stop_cell, n_cells, seed_level,
                 pour_cell=None):
        self.spill = spill
        self.pour_cell = pour_cell
        self.limit_level = limit_level
        self.reason = reason
        self.stop_cell = stop_cell
        self.n_cells = n_cells
        self.seed_level = seed_level

    @property
    def rise(self):
        return self.limit_level - self.seed_level


def open_boundary_mask(z):
    """Return a uint8 mask: 1 on the grid edge, 2 next to no-data (NaN)."""
    nan = np.isnan(z)
    out = np.zeros(z.shape, dtype=np.uint8)
    near = np.zeros(z.shape, dtype=bool)
    near[1:, :] |= nan[:-1, :]
    near[:-1, :] |= nan[1:, :]
    near[:, 1:] |= nan[:, :-1]
    near[:, :-1] |= nan[:, 1:]
    out[near & ~nan] = _OPEN_NODATA
    out[0, :] = _OPEN_EDGE
    out[-1, :] = _OPEN_EDGE
    out[:, 0] = _OPEN_EDGE
    out[:, -1] = _OPEN_EDGE
    return out


def priority_flood(z, seed, blocked, stop_cells=None, max_level=math.inf,
                   max_cells=None, progress=None, is_cancelled=None):
    """Priority flood (4-connected) from ``seed`` over elevation grid ``z``.

    Parameters
    ----------
    z : 2-D float array, NaN = no data.
    seed : (row, col) start cell.
    blocked : 2-D bool array of impassable cells (the dam axis).
    stop_cells : optional 2-D bool array; reaching one of these stops the
        flood with reason ``bypass`` (used for the downstream side of the dam).
    max_level : stop once the water level would exceed this value.
    max_cells : stop after this many cells were finalised.
    progress : callable(level, n_cells) called periodically.
    is_cancelled : callable() -> bool, checked periodically.

    Returns
    -------
    FloodResult
    """
    rows, cols = z.shape
    n = rows * cols
    zf = np.where(np.isnan(z), np.inf, z).astype(np.float64).ravel()
    zarr = array('d', zf.tobytes())
    open_ = bytearray(open_boundary_mask(z).ravel().tobytes())
    closed = bytearray((blocked | np.isnan(z)).ravel().astype(np.uint8).tobytes())
    stop = (bytearray(stop_cells.ravel().astype(np.uint8).tobytes())
            if stop_cells is not None else bytearray(n))
    spill = array('d', [math.inf]) * n

    r0, c0 = seed
    i0 = int(r0) * cols + int(c0)
    seed_level = zarr[i0]
    heap = [(seed_level, i0)]
    closed[i0] = 1
    heappop, heappush = heapq.heappop, heapq.heappush
    count = 0
    reason = STOP_EXHAUSTED
    limit = seed_level
    stop_idx = None
    rise_idx = i0
    offsets = (-1, 1, -cols, cols)
    check_every = 20000

    while heap:
        level, i = heappop(heap)
        if level > max_level:
            reason, limit = STOP_MAX_LEVEL, max_level
            break
        if level > limit:
            rise_idx = i          # this cell controls the current water level
        if stop[i]:
            reason, limit, stop_idx = STOP_BYPASS, level, i
            break
        o = open_[i]
        if o:
            reason = STOP_EDGE if o == _OPEN_EDGE else STOP_NODATA
            limit, stop_idx = level, i
            break
        spill[i] = level
        count += 1
        limit = level
        # Neighbours of a non-open cell are always inside the grid.
        for d in offsets:
            j = i + d
            if not closed[j]:
                closed[j] = 1
                zj = zarr[j]
                heappush(heap, (zj if zj > level else level, j))
        if count % check_every == 0:
            if is_cancelled is not None and is_cancelled():
                raise Cancelled()
            if progress is not None:
                progress(level, count)
            if max_cells is not None and count >= max_cells:
                reason = STOP_CELL_LIMIT
                break

    spill_np = np.frombuffer(spill, dtype=np.float64).reshape(rows, cols).copy()
    stop_cell = divmod(stop_idx, cols) if stop_idx is not None else None
    return FloodResult(spill_np, float(limit), reason, stop_cell, count, float(seed_level),
                       pour_cell=divmod(rise_idx, cols))


def geodesic_distance(domain, sources, cell_size, is_cancelled=None):
    """Distance (map units) from ``sources`` travelling only inside ``domain``.

    8-connected Dijkstra with chamfer weights (1, sqrt 2).  Used to measure the
    reservoir length along the (possibly winding) valley.
    """
    rows, cols = domain.shape
    n = rows * cols
    dom = bytearray(domain.ravel().astype(np.uint8).tobytes())
    dist = array('d', [math.inf]) * n
    heap = []
    for i in np.flatnonzero((sources & domain).ravel()):
        dist[int(i)] = 0.0
        heap.append((0.0, int(i)))
    heapq.heapify(heap)
    d1, d2 = float(cell_size), float(cell_size) * math.sqrt(2.0)
    nbrs = ((-1, 0, d1), (1, 0, d1), (0, -1, d1), (0, 1, d1),
            (-1, -1, d2), (-1, 1, d2), (1, -1, d2), (1, 1, d2))
    heappop, heappush = heapq.heappop, heapq.heappush
    count = 0
    while heap:
        d, i = heappop(heap)
        if d > dist[i]:
            continue
        r, c = divmod(i, cols)
        for dr, dc, w in nbrs:
            rr, cc = r + dr, c + dc
            if 0 <= rr < rows and 0 <= cc < cols:
                j = rr * cols + cc
                if dom[j]:
                    nd = d + w
                    if nd < dist[j]:
                        dist[j] = nd
                        heappush(heap, (nd, j))
        count += 1
        if is_cancelled is not None and count % 50000 == 0 and is_cancelled():
            raise Cancelled()
    return np.frombuffer(dist, dtype=np.float64).reshape(rows, cols).copy()


# ---------------------------------------------------------------------------
# Elevation - area - capacity
# ---------------------------------------------------------------------------

class CapacityTable:
    """Fast elevation-area-capacity lookup built from spill levels."""

    def __init__(self, spill_values, z_values, cell_area):
        order = np.argsort(spill_values, kind='stable')
        self.spill = np.asarray(spill_values, dtype=np.float64)[order]
        z_sorted = np.asarray(z_values, dtype=np.float64)[order]
        self.cum_z = np.concatenate(([0.0], np.cumsum(z_sorted)))
        self.cell_area = float(cell_area)

    def counts(self, levels):
        return np.searchsorted(self.spill, np.asarray(levels, dtype=np.float64), side='right')

    def area(self, levels):
        """Water surface area [m2] at the given level(s)."""
        return self.counts(levels) * self.cell_area

    def volume(self, levels):
        """Stored volume [m3] at the given level(s)."""
        lv = np.asarray(levels, dtype=np.float64)
        n = self.counts(lv)
        return np.maximum(lv * n - self.cum_z[n], 0.0) * self.cell_area


def nice_step(span, target_rows=120):
    """A round level increment giving roughly ``target_rows`` rows."""
    if not np.isfinite(span) or span <= 0:
        return 1.0
    raw = span / float(target_rows)
    for s in (0.1, 0.2, 0.25, 0.5, 1.0, 2.0, 2.5, 5.0, 10.0, 20.0, 25.0, 50.0, 100.0):
        if s >= raw:
            return s
    return 100.0


def level_series(bottom, top, step):
    """Round levels from ``bottom`` to ``top`` (both included) every ``step``."""
    if top <= bottom:
        return np.array([bottom, top], dtype=np.float64)
    start = math.floor(bottom / step) * step
    levels = np.arange(start, top, step, dtype=np.float64)
    levels = levels[levels >= bottom - 1e-9]
    levels = np.concatenate(([bottom], levels, [top]))
    return np.unique(np.round(levels, 6))


# ---------------------------------------------------------------------------
# Dam axis
# ---------------------------------------------------------------------------

def crest_length(stations, ground, crest):
    """Length of the dam axis whose ground lies below ``crest`` (linear interp)."""
    s = np.asarray(stations, dtype=np.float64)
    g = np.asarray(ground, dtype=np.float64)
    total = 0.0
    for k in range(len(s) - 1):
        g0, g1 = g[k], g[k + 1]
        ds = s[k + 1] - s[k]
        if not (np.isfinite(g0) and np.isfinite(g1)):
            continue
        b0, b1 = g0 < crest, g1 < crest
        if b0 and b1:
            total += ds
        elif b0 != b1:
            total += ds * abs(crest - (g0 if b0 else g1)) / abs(g1 - g0)
    return total


def embankment(stations, ground, crest, crest_width, slope_us, slope_ds):
    """Indicative embankment geometry for a trapezoidal dam section.

    The cross-section at each station is a trapezoid of height
    ``H = crest - ground`` with top width ``crest_width`` and side slopes
    ``slope_us`` / ``slope_ds`` (horizontal : 1 vertical)::

        A(H) = b H + (m_us + m_ds) H^2 / 2

    Returns dict(height, crest_length, fill_volume, max_section_area).
    Foundation excavation and cut-off works are ignored.
    """
    s = np.asarray(stations, dtype=np.float64)
    g = np.asarray(ground, dtype=np.float64)
    valid = np.isfinite(g)
    h = np.where(valid, np.clip(crest - g, 0.0, None), 0.0)
    area = np.where(h > 0, crest_width * h + 0.5 * (slope_us + slope_ds) * h * h, 0.0)
    # trapezoidal rule (np.trapz is deprecated in numpy 2)
    fill = float(0.5 * np.sum((area[1:] + area[:-1]) * np.diff(s))) if len(s) > 1 else 0.0
    return {
        'height': float(crest - np.nanmin(g)) if valid.any() else float('nan'),
        'crest_length': crest_length(s, g, crest),
        'fill_volume': fill,
        'max_section_area': float(area.max()) if len(area) else 0.0,
    }


# ---------------------------------------------------------------------------
# Sediment / hydrology indicators
# ---------------------------------------------------------------------------

SECONDS_PER_YEAR = 365.25 * 86400.0


def brune_trap_efficiency(capacity_m3, annual_inflow_m3):
    """Sediment trap efficiency [%] from Brune's median curve (Dendy, 1974).

    ``TE = 100 * 0.97 ** (0.19 ** log10(C/I))``
    """
    if not annual_inflow_m3 or annual_inflow_m3 <= 0 or capacity_m3 <= 0:
        return float('nan')
    ci = capacity_m3 / annual_inflow_m3
    return 100.0 * 0.97 ** (0.19 ** math.log10(ci))


def residence_time_days(volume_m3, mean_flow_m3s):
    if not mean_flow_m3s or mean_flow_m3s <= 0:
        return float('nan')
    return volume_m3 / (mean_flow_m3s * 86400.0)


def shoreline_development(perimeter_m, area_m2):
    """Shoreline development index  D_L = P / (2 sqrt(pi A))  (1 = circle)."""
    if area_m2 <= 0:
        return float('nan')
    return perimeter_m / (2.0 * math.sqrt(math.pi * area_m2))
