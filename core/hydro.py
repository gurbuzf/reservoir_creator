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

The flood stops at the requested water level (``max_level``), or earlier
when the water finds another way out:

* ``bypass``  - water reaches the other side of the line (through a saddle),
* ``edge``    - the reservoir reaches the edge of the analysed DEM window,
* ``nodata``  - the reservoir reaches a DEM void.
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
