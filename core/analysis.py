# -*- coding: utf-8 -*-
"""
Reservoir behind a line drawn across a valley - DEM only.

The logic is deliberately simple:

1. The **water level** is the ground elevation at the *lower of the two ends*
   of the line (above that, water would flow around the line's end).
2. The line is a wall. The **reservoir** is every DEM cell behind the line that
   is connected to it and lies below the water level (priority flood).
3. Area and volume are also reported for every level from the river bed up to
   the water level (elevation-area-volume curve).

If the water finds a lower way out before reaching that level (a saddle
elsewhere in the rim), the level is lowered to that point and the user is
told.  The analysis window grows automatically until the reservoir fits.
"""

import math

import numpy as np

from . import hydro, terrain
from .terrain import TerrainError

MAX_RADIUS_M = 100_000.0


class Feedback:
    """Minimal progress/cancel interface (overridden by the QGIS task)."""

    def set_progress(self, percent):
        pass

    def set_status(self, text):
        pass

    def is_cancelled(self):
        return False


class Note:
    INFO, WARNING = 'info', 'warning'

    def __init__(self, level, text):
        self.level = level
        self.text = text

    def __repr__(self):
        return '[{}] {}'.format(self.level, self.text)


class Params:
    """Inputs: a DEM, the line's vertices and the line's CRS.

    ``side`` ('auto' | 'left' | 'right' of the drawing direction) only
    matters when the automatic choice of the reservoir side is wrong.
    """

    def __init__(self, dem_path, line_coords, line_crs, side='auto', radius_m=None,
                 dem_scale=None, dem_offset=None, max_cells=6_000_000):
        self.dem_path = dem_path
        self.line_coords = [(float(x), float(y)) for x, y in line_coords]
        self.line_crs = line_crs
        self.side = side
        self.radius_m = radius_m
        self.dem_scale = dem_scale
        self.dem_offset = dem_offset
        self.max_cells = max_cells


class Result:
    """Outcome.  Lengths in m, areas in m2, volumes in m3, levels in m."""

    def __init__(self):
        self.notes = []
        self.grid = None
        self.spill = None
        self.blocked = None
        self.line_coords = []       # in the working CRS
        self.stations = None        # ground profile along the line
        self.ground = None
        self.end_levels = None      # (start, end) ground elevation
        self.water_level = None
        self.limited_by = None      # None | 'saddle' | 'edge' | 'nodata'
        self.pour_point = None
        self.side = None
        self.bed_level = None
        self.area_m2 = 0.0
        self.volume_m3 = 0.0
        self.polygon_wkt = None
        self.table = None
        self.radius_m = None
        self.window_can_grow = False   # reservoir hit the window edge, not the DEM's

    @property
    def srs_wkt(self):
        return self.grid.srs_wkt

    @property
    def max_depth(self):
        return self.water_level - self.bed_level

    def curve(self):
        """(levels, area_m2, volume_m3) from the river bed to the water level."""
        step = hydro.nice_step(self.water_level - self.bed_level)
        lv = hydro.level_series(self.bed_level, self.water_level, step)
        return lv, self.table.area(lv), self.table.volume(lv)

    def depth_array(self):
        wet = self.spill <= self.water_level
        return np.where(wet, self.water_level - self.grid.z, np.nan)


# ---------------------------------------------------------------------------

def plan_frame(line_coords, line_crs, radius_m, dem_srs=None):
    """Working CRS (DEM CRS if metric, else local UTM), line coordinates in
    it, and the analysis bounds.  Returns (work_srs, coords, bounds, lat)."""
    src = terrain.make_srs(line_crs)
    ll = terrain.transform_points(line_coords, src, terrain.geographic_srs())
    lon = float(np.mean([p[0] for p in ll]))
    lat = float(np.mean([p[1] for p in ll]))
    work = (terrain.choose_working_srs(dem_srs, lon, lat) if dem_srs is not None
            else terrain.utm_srs_for(lon, lat))
    coords = terrain.transform_points(line_coords, src, work)
    xs = [p[0] for p in coords]
    ys = [p[1] for p in coords]
    r = float(radius_m)
    return work, coords, (min(xs) - r, min(ys) - r, max(xs) + r, max(ys) + r), lat


def line_length(line_coords, line_crs):
    work, coords, _b, _lat = plan_frame(line_coords, line_crs, 0.0)
    pts = np.asarray(coords)
    return float(np.hypot(*np.diff(pts, axis=0).T).sum())


def initial_radius(line_coords, line_crs):
    """Start with a window ~20x the line length (at least 5 km)."""
    return max(5000.0, 20.0 * line_length(line_coords, line_crs))


def run(params, feedback=None, get_dem=None):
    """Compute the reservoir, enlarging the window until it fits.

    ``get_dem(bounds, work_srs, radius)`` may return a DEM path for the
    window (used for downloads); by default ``params.dem_path`` is used.
    """
    fb = feedback or Feedback()
    radius = params.radius_m or initial_radius(params.line_coords, params.line_crs)
    while True:
        if get_dem is not None:
            work, _c, bounds, _lat = plan_frame(params.line_coords, params.line_crs, radius)
            params.dem_path = get_dem(bounds, work, radius)
        res = _run_once(params, radius, fb)
        if not res.window_can_grow or radius >= MAX_RADIUS_M or params.radius_m:
            break
        radius = min(radius * 2.0, MAX_RADIUS_M)
        fb.set_status('Reservoir reaches the edge of the window - enlarging to {:.0f} km…'
                      .format(radius / 1000.0))
    _add_notes(res)
    fb.set_progress(100)
    return res


def _run_once(params, radius, fb):
    res = Result()
    res.radius_m = radius
    if len(params.line_coords) < 2:
        raise TerrainError('The line needs at least two points.')

    fb.set_status('Reading elevation data…')
    fb.set_progress(5)
    info = terrain.dem_info(params.dem_path)
    work, coords, bounds, lat = plan_frame(params.line_coords, params.line_crs, radius,
                                           terrain.make_srs(info['srs_wkt']))
    grid, grid_notes = terrain.read_dem_window(
        params.dem_path, work, bounds, max_cells=params.max_cells, lat=lat,
        scale=params.dem_scale, offset=params.dem_offset)
    res.notes = [Note(Note.INFO, t) for t in grid_notes]
    res.grid, res.line_coords = grid, coords
    if fb.is_cancelled():
        raise hydro.Cancelled()

    # the line as a wall, and its ground profile
    fb.set_progress(15)
    blocked = terrain.rasterize_polyline(grid, coords)
    res.blocked = blocked
    st, pxs, pys, ground, seg_idx = _profile(grid, coords, grid.cell_size / 2.0)
    res.stations, res.ground = st, ground
    if not (np.isfinite(ground[0]) and np.isfinite(ground[-1])):
        raise TerrainError('An end of the line is outside the DEM (no elevation there).')
    res.end_levels = (float(ground[0]), float(ground[-1]))
    level = min(res.end_levels)

    k = int(np.nanargmin(ground))
    if ground[k] >= level - 1e-6:
        raise TerrainError('The line does not cross a valley: no point along it is lower '
                           'than its ends.')
    thalweg = (float(pxs[k]), float(pys[k]))
    si = int(seg_idx[k])
    d = np.subtract(coords[si + 1], coords[si])
    d = d / (np.hypot(*d) or 1.0)
    open_mask = hydro.open_boundary_mask(grid.z)
    left, right = _side_cells(grid, blocked, open_mask, thalweg, d)
    if not left or not right:
        raise TerrainError('The line is too close to the DEM edge or a no-data area.')
    seed = {'left': _lowest(grid, left), 'right': _lowest(grid, right)}
    stop = {'left': _mask(grid.shape, right), 'right': _mask(grid.shape, left)}

    # which side is the reservoir?
    fb.set_status('Finding the upstream side…')
    fb.set_progress(25)
    floods = {}
    if params.side in ('left', 'right'):
        side = params.side
    else:
        for s in ('left', 'right'):
            floods[s] = hydro.priority_flood(grid.z, seed[s], blocked, stop_cells=stop[s],
                                             max_level=level, max_cells=250_000,
                                             is_cancelled=fb.is_cancelled)
        fl, fr = floods['left'], floods['right']
        # the downstream side drains away along the river almost at once
        if abs(fl.rise - fr.rise) > 0.5:
            side = 'left' if fl.rise > fr.rise else 'right'
        else:
            side = 'left' if fl.seed_level >= fr.seed_level else 'right'
    res.side = side

    fb.set_status('Filling the reservoir…')
    fb.set_progress(40)
    flood = floods.get(side)
    if flood is None or flood.reason == hydro.STOP_CELL_LIMIT:
        flood = hydro.priority_flood(grid.z, seed[side], blocked, stop_cells=stop[side],
                                     max_level=level, is_cancelled=fb.is_cancelled)
    if flood.reason == hydro.STOP_MAX_LEVEL:
        water = level
    else:
        water = flood.limit_level
        res.limited_by = {hydro.STOP_BYPASS: 'saddle', hydro.STOP_EDGE: 'edge',
                          hydro.STOP_NODATA: 'nodata'}.get(flood.reason)
        if flood.pour_cell is not None:
            res.pour_point = tuple(float(v) for v in grid.cell_center(*flood.pour_cell))
        if flood.reason == hydro.STOP_EDGE and flood.stop_cell is not None:
            res.window_can_grow = _edge_is_window(grid, bounds, flood.stop_cell)
    res.spill = flood.spill
    wet = np.isfinite(flood.spill) & (flood.spill <= water)
    if wet.sum() < 1:
        raise TerrainError('No reservoir forms behind this line. Try the other side '
                           '(Flip side) or check the DEM.')
    res.water_level = float(water)
    res.table = hydro.CapacityTable(flood.spill[wet], grid.z[wet], grid.cell_area)
    res.bed_level = float(np.min(flood.spill[wet]))
    res.area_m2 = float(res.table.area(water))
    res.volume_m3 = float(res.table.volume(water))

    fb.set_status('Tracing the shoreline…')
    fb.set_progress(85)
    res.polygon_wkt, _a, _p = terrain.water_surface_polygon(grid, flood.spill, water, blocked)
    return res


def _add_notes(res):
    lo = min(res.end_levels)
    if res.limited_by == 'saddle':
        res.notes.append(Note(Note.WARNING,
                              'Water escapes through a low point in the rim at {:.1f} m, below '
                              'the line ends ({:.1f} m). The reservoir is shown at {:.1f} m; '
                              'the escape point is marked on the map.'
                              .format(res.water_level, lo, res.water_level)))
    elif res.limited_by == 'edge':
        res.notes.append(Note(Note.WARNING,
                              'The reservoir reaches the edge of the DEM at {:.1f} m, so it is '
                              'cut there. Use a DEM covering the whole valley.'
                              .format(res.water_level)))
    elif res.limited_by == 'nodata':
        res.notes.append(Note(Note.WARNING,
                              'The reservoir reaches missing DEM data (no-data) at {:.1f} m, '
                              'so it is cut there.'.format(res.water_level)))


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _profile(grid, coords, step):
    pts = np.asarray(coords, dtype=np.float64)
    seg = np.hypot(np.diff(pts[:, 0]), np.diff(pts[:, 1]))
    cum = np.concatenate(([0.0], np.cumsum(seg)))
    n = max(2, int(math.ceil(cum[-1] / step)) + 1)
    st = np.unique(np.concatenate((np.linspace(0.0, cum[-1], n), cum)))
    xs = np.interp(st, cum, pts[:, 0])
    ys = np.interp(st, cum, pts[:, 1])
    seg_idx = np.clip(np.searchsorted(cum, st, side='right') - 1, 0, len(seg) - 1)
    return st, xs, ys, grid.sample(xs, ys), seg_idx


def _side_cells(grid, blocked, open_mask, centre, direction, radius_cells=3):
    """Cells next to the line's lowest point, split into left / right."""
    r, c = grid.to_cell(*centre)
    r, c = int(round(float(r))), int(round(float(c)))
    rows, cols = grid.shape
    dx, dy = direction
    left, right = [], []
    for rr in range(max(1, r - radius_cells), min(rows - 1, r + radius_cells + 1)):
        for cc in range(max(1, c - radius_cells), min(cols - 1, c + radius_cells + 1)):
            if blocked[rr, cc] or open_mask[rr, cc] or np.isnan(grid.z[rr, cc]):
                continue
            x, y = grid.cell_center(rr, cc)
            cross = dx * (y - centre[1]) - dy * (x - centre[0])
            if cross > 0:
                left.append((rr, cc))
            elif cross < 0:
                right.append((rr, cc))
    return left, right


def _edge_is_window(grid, bounds, cell):
    """True if ``cell`` lies on a grid side that was cut by the analysis window
    (a bigger window would show more), False if that side is the DEM's own edge."""
    rows, cols = grid.shape
    gx0, gy0, gx1, gy1 = grid.bounds
    bx0, by0, bx1, by1 = bounds
    tol = 1.5 * grid.cell_size
    r, c = cell
    sides = []
    if c == 0:
        sides.append(gx0 - bx0)
    if c == cols - 1:
        sides.append(bx1 - gx1)
    if r == 0:
        sides.append(by1 - gy1)
    if r == rows - 1:
        sides.append(gy0 - by0)
    return any(gap <= tol for gap in sides)


def _lowest(grid, cells):
    return min(cells, key=lambda rc: grid.z[rc[0], rc[1]])


def _mask(shape, cells):
    m = np.zeros(shape, dtype=bool)
    for rr, cc in cells:
        m[rr, cc] = True
    return m
