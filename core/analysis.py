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
import time
from contextlib import contextmanager

import numpy as np

from . import hydro, terrain
from .i18n import Msg, tr
from .terrain import TerrainError

MAX_RADIUS_M = 200_000.0          # per side; the cell budget usually stops growth first
INITIAL_RADIUS_MAX_M = 30_000.0


class Feedback:
    """Minimal progress/cancel interface (overridden by the QGIS task)."""

    def set_progress(self, percent):
        pass

    def set_status(self, text):
        pass

    def is_cancelled(self):
        return False

    def log(self, text):
        """Diagnostic line (step timings); the QGIS task sends it to the log panel."""
        pass


class StepTimer:
    """Wall-clock time of every step, logged as it finishes and kept in the result."""

    def __init__(self, fb):
        self.fb = fb
        self.steps = []          # (name, seconds)
        self.start = time.perf_counter()

    @contextmanager
    def step(self, name):
        t = time.perf_counter()
        try:
            yield
        finally:
            dt = time.perf_counter() - t
            self.steps.append((name, dt))
            self.fb.log('{:<44} {:8.2f} s'.format(name, dt))

    @property
    def total(self):
        return time.perf_counter() - self.start


class Note:
    INFO, WARNING = 'info', 'warning'

    def __init__(self, level, text, kind=None):
        self.level = level
        self._text = text       # a Msg / English text, translated when shown
        self.kind = kind        # 'resolution' | 'fast' | 'cap' | None (for the panel)

    @property
    def text(self):
        return str(self._text) if isinstance(self._text, Msg) else tr(self._text)

    def __repr__(self):
        return '[{}] {}'.format(self.level, self.text)


class Params:
    """Inputs: a DEM, the line's vertices and the line's CRS.

    ``side`` ('auto' | 'left' | 'right' of the drawing direction) only
    matters when the automatic choice of the reservoir side is wrong.
    ``fast`` lets large windows be coarsened (the DEM's own resolution is
    kept otherwise).
    """

    def __init__(self, dem_path, line_coords, line_crs, side='auto', radius_m=None,
                 dem_scale=None, dem_offset=None, fast=False, max_level=None,
                 max_depth=None):
        self.dem_path = dem_path
        self.line_coords = [(float(x), float(y)) for x, y in line_coords]
        self.line_crs = line_crs
        self.side = side
        self.radius_m = radius_m
        self.dem_scale = dem_scale
        self.dem_offset = dem_offset
        self.fast = fast
        # design maximum water level (m); the line's lower end still caps it
        self.max_level = None if max_level is None else float(max_level)
        # or a design maximum depth (m) above the riverbed at the line
        self.max_depth = None if max_depth is None else float(max_depth)


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
        self.level_source = 'line'  # 'line' (lower end) | 'max' | 'depth' (user's limit)
        self.line_bed = None        # lowest ground along the line (riverbed at the dam)
        self.cap = None             # user's limit: (level m a.s.l., 'max' | 'depth')
        self.cap_ignored = False    # the limit was above what the line can hold
        self.pour_point = None
        self.side = None
        self.bed_level = None
        self.area_m2 = 0.0
        self.volume_m3 = 0.0
        self.polygon_wkt = None
        self.table = None
        self.radius_m = None
        self.window_can_grow = False   # reservoir hit the window edge, not the DEM's
        self.grow_sides = []           # which window sides it hit ('w', 's', 'e', 'n')
        self.margins = None            # window extent beyond the line, per side (m)
        self.fast = False              # resolution reduced on request (Fast mode)
        self.timings = []              # (step, seconds), see StepTimer

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

SIDES = ('w', 's', 'e', 'n')
SIDE_NAMES = {'w': 'west', 's': 'south', 'e': 'east', 'n': 'north'}


def plan_frame(line_coords, line_crs, margins, dem_srs=None):
    """Working CRS (DEM CRS if metric, else local UTM), line coordinates in
    it, and the analysis bounds.  ``margins`` is one distance for all sides or
    a dict {'w','s','e','n'} (m beyond the line's bounding box).
    Returns (work_srs, coords, bounds, lat)."""
    src = terrain.make_srs(line_crs)
    ll = terrain.transform_points(line_coords, src, terrain.geographic_srs())
    lon = float(np.mean([p[0] for p in ll]))
    lat = float(np.mean([p[1] for p in ll]))
    work = (terrain.choose_working_srs(dem_srs, lon, lat) if dem_srs is not None
            else terrain.utm_srs_for(lon, lat))
    coords = terrain.transform_points(line_coords, src, work)
    xs = [p[0] for p in coords]
    ys = [p[1] for p in coords]
    m = margins if isinstance(margins, dict) else dict.fromkeys(SIDES, float(margins))
    return work, coords, (min(xs) - m['w'], min(ys) - m['s'],
                          max(xs) + m['e'], max(ys) + m['n']), lat


def line_length(line_coords, line_crs):
    work, coords, _b, _lat = plan_frame(line_coords, line_crs, 0.0)
    pts = np.asarray(coords)
    return float(np.hypot(*np.diff(pts, axis=0).T).sum())


def initial_radius(line_coords, line_crs):
    """Start with a window ~20x the line length (5 to 30 km beyond the line)."""
    return min(INITIAL_RADIUS_MAX_M, max(5000.0, 20.0 * line_length(line_coords, line_crs)))


def _window_cells(line_coords, line_crs, margins, cell_size):
    _w, _c, (x0, y0, x1, y1), _lat = plan_frame(line_coords, line_crs, margins)
    return (x1 - x0) * (y1 - y0) / (cell_size * cell_size)


def run(params, feedback=None, get_dem=None):
    """Compute the reservoir, enlarging the window until it fits.

    The window only grows on the side where the water reached its edge, so a
    long, narrow reservoir gets a long, narrow window.  After the first pass
    the reservoir side is known and the side test is skipped.

    ``get_dem(bounds, work_srs, radius)`` may return a DEM path for the
    window (used for downloads); by default ``params.dem_path`` is used.
    """
    fb = feedback or Feedback()
    timer = StepTimer(fb)
    r0 = params.radius_m or initial_radius(params.line_coords, params.line_crs)
    margins = dict.fromkeys(SIDES, r0)
    side = params.side
    attempt = 0
    while True:
        attempt += 1
        fb.log('--- pass {}: window beyond the line W {:.0f} / S {:.0f} / E {:.0f} / N {:.0f} km'
               .format(attempt, *(margins[s] / 1000.0 for s in SIDES)))
        if get_dem is not None:
            work, _c, bounds, _lat = plan_frame(params.line_coords, params.line_crs, margins)
            with timer.step('Get DEM (download or cache)'):
                params.dem_path = get_dem(bounds, work, max(margins.values()))
        res = _run_once(params, margins, fb, timer, side)
        side = res.side                      # known now: no side test on later passes
        if not res.grow_sides or params.radius_m:
            break
        grow = [s for s in res.grow_sides if margins[s] < MAX_RADIUS_M]
        if not grow:
            break
        bigger = dict(margins)
        for s in grow:
            bigger[s] = min(2.0 * margins[s], MAX_RADIUS_M)
        if not params.fast:
            cells = _window_cells(params.line_coords, params.line_crs, bigger,
                                  res.grid.cell_size)
            if cells > terrain.MAX_FULL_RES_CELLS:   # checked before downloading anything
                fb.log('    stop growing: next window would hold {:,.0f} million cells'
                       .format(cells / 1e6))
                res.notes.append(Note(Note.WARNING,
                                      Msg('The reservoir continues beyond the analysis area, '
                                          'which cannot grow further at full resolution ({:,.0f} '
                                          'million cells). Turn on "Fast mode" to follow it '
                                          'further.', cells / 1e6)))
                break
        margins = bigger
        fb.set_status(tr('Reservoir reaches the {} edge of the window - extending it to '
                         '{:.0f} km…')
                      .format(tr(' and ').join(tr(SIDE_NAMES[s]) for s in grow),
                              max(margins[s] for s in grow) / 1000.0))
    _add_notes(res, params)
    res.timings = timer.steps
    fb.log('--- total {:.2f} s in {} pass(es); grid {:,} cells of {:.1f} m; reservoir {:,} cells'
           .format(timer.total, attempt, res.grid.z.size, res.grid.cell_size,
                   int(res.table.counts(res.water_level))))
    fb.set_progress(100)
    return res


def _run_once(params, margins, fb, timer=None, side=None):
    timer = timer or StepTimer(fb)
    res = Result()
    res.margins = dict(margins)
    res.radius_m = max(margins.values())
    side = side or params.side
    if len(params.line_coords) < 2:
        raise TerrainError(tr('The line needs at least two points.'))

    fb.set_status(tr('Reading elevation data…'))
    fb.set_progress(5)
    with timer.step('Read DEM window'):
        info = terrain.dem_info(params.dem_path)
        work, coords, bounds, lat = plan_frame(params.line_coords, params.line_crs, margins,
                                               terrain.make_srs(info['srs_wkt']))
        grid, grid_notes = terrain.read_dem_window(
            params.dem_path, work, bounds,
            max_cells=terrain.FAST_MODE_CELLS if params.fast else None, lat=lat,
            scale=params.dem_scale, offset=params.dem_offset)
    fb.log('    grid {} x {} = {:,} cells of {:.1f} m'.format(
        grid.shape[1], grid.shape[0], grid.z.size, grid.cell_size))
    res.notes = [Note(Note.INFO, t, 'fast' if t.startswith('Fast mode') else None)
                 for t in grid_notes]
    res.grid, res.line_coords = grid, coords
    res.fast = params.fast
    if fb.is_cancelled():
        raise hydro.Cancelled()

    # the line as a wall, and its ground profile
    fb.set_progress(15)
    with timer.step('Line as wall + ground profile'):
        blocked = terrain.rasterize_polyline(grid, coords)
        res.blocked = blocked
        st, pxs, pys, ground, seg_idx = _profile(grid, coords, grid.cell_size / 2.0)
    res.stations, res.ground = st, ground
    if not (np.isfinite(ground[0]) and np.isfinite(ground[-1])):
        raise TerrainError(tr('An end of the line is outside the DEM (no elevation there).'))
    res.end_levels = (float(ground[0]), float(ground[-1]))
    level = min(res.end_levels)

    k = int(np.nanargmin(ground))
    if ground[k] >= level - 1e-6:
        raise TerrainError(tr('The line does not cross a valley: no point along it is lower '
                              'than its ends.'))
    res.line_bed = float(ground[k])
    res.cap = _user_cap(params, res.line_bed)
    if res.cap is not None and res.cap[0] < level:
        level, res.level_source = res.cap
    if ground[k] >= level - 1e-6:
        raise TerrainError(tr('The maximum water level ({:.1f} m a.s.l.) is not above the '
                              'riverbed at the line ({:.1f} m a.s.l.): no reservoir.')
                           .format(level, ground[k]))
    thalweg = (float(pxs[k]), float(pys[k]))
    si = int(seg_idx[k])
    d = np.subtract(coords[si + 1], coords[si])
    d = d / (np.hypot(*d) or 1.0)
    with timer.step('Boundary mask + side cells'):
        open_mask = hydro.open_boundary_mask(grid.z)
        left, right = _side_cells(grid, blocked, open_mask, thalweg, d)
    if not left or not right:
        raise TerrainError(tr('The line is too close to the DEM edge or a no-data area.'))
    seed = {'left': _lowest(grid, left), 'right': _lowest(grid, right)}
    stop = {'left': _mask(grid.shape, right), 'right': _mask(grid.shape, left)}

    # which side is the reservoir?
    fb.set_status(tr('Finding the upstream side…'))
    fb.set_progress(25)
    floods = {}
    if side not in ('left', 'right'):
        for s in ('left', 'right'):
            with timer.step('Side test flood ({})'.format(s)):
                floods[s] = hydro.priority_flood(grid.z, seed[s], blocked, stop_cells=stop[s],
                                                 max_level=level, max_cells=250_000,
                                                 is_cancelled=fb.is_cancelled)
            fb.log('    {} side: {:,} cells, rise {:.1f} m, stop: {}'.format(
                s, floods[s].n_cells, floods[s].rise, floods[s].reason))
        fl, fr = floods['left'], floods['right']
        # the downstream side drains away along the river almost at once
        if abs(fl.rise - fr.rise) > 0.5:
            side = 'left' if fl.rise > fr.rise else 'right'
        else:
            side = 'left' if fl.seed_level >= fr.seed_level else 'right'
    res.side = side

    fb.set_status(tr('Filling the reservoir…'))
    fb.set_progress(40)
    flood = floods.get(side)
    if flood is None or flood.reason == hydro.STOP_CELL_LIMIT:
        with timer.step('Reservoir flood ({} side)'.format(side)):
            flood = hydro.priority_flood(grid.z, seed[side], blocked, stop_cells=stop[side],
                                         max_level=level, is_cancelled=fb.is_cancelled)
    fb.log('    reservoir flood: {:,} cells, stop: {} at {:.1f} m'.format(
        flood.n_cells, flood.reason, flood.limit_level))
    if flood.reason == hydro.STOP_MAX_LEVEL:
        water = level
    else:
        water = flood.limit_level
        res.limited_by = {hydro.STOP_BYPASS: 'saddle', hydro.STOP_EDGE: 'edge',
                          hydro.STOP_NODATA: 'nodata'}.get(flood.reason)
        if flood.pour_cell is not None:
            res.pour_point = tuple(float(v) for v in grid.cell_center(*flood.pour_cell))
        if flood.reason == hydro.STOP_EDGE and flood.stop_cell is not None:
            res.grow_sides = _window_edge_sides(grid, bounds, flood.stop_cell)
            res.window_can_grow = bool(res.grow_sides)
    res.spill = flood.spill
    wet = np.isfinite(flood.spill) & (flood.spill <= water)
    if wet.sum() < 1:
        raise TerrainError(tr('No reservoir forms behind this line. Try the other side '
                           '(Flip side) or check the DEM.'))
    res.water_level = float(water)
    with timer.step('Area-volume table'):
        res.table = hydro.CapacityTable(flood.spill[wet], grid.z[wet], grid.cell_area)
        res.bed_level = float(np.min(flood.spill[wet]))
        res.area_m2 = float(res.table.area(water))
        res.volume_m3 = float(res.table.volume(water))

    fb.set_status(tr('Tracing the shoreline…'))
    fb.set_progress(85)
    with timer.step('Shoreline polygon'):
        res.polygon_wkt, _a, _p = terrain.water_surface_polygon(grid, flood.spill, water,
                                                                blocked)
    return res


def _user_cap(params, line_bed):
    """The user's limit as (level m a.s.l., 'max' | 'depth'), the lower of the two."""
    caps = []
    if params.max_level is not None:
        caps.append((params.max_level, 'max'))
    if params.max_depth is not None:
        caps.append((line_bed + params.max_depth, 'depth'))
    return min(caps) if caps else None


def _add_notes(res, params=None):
    lo = min(res.end_levels)
    target = lo if res.cap is None else min(lo, res.cap[0])
    add = res.notes.append
    if not any(n.kind == 'fast' for n in res.notes):
        add(Note(Note.INFO, Msg('Computed at full DEM resolution ({:.1f} m cells).',
                                res.grid.cell_size), 'resolution'))
    if res.level_source == 'max':
        add(Note(Note.INFO, Msg('Water level limited to your maximum of {:.1f} m a.s.l.; the '
                                'lower end of the line is {:.1f} m higher ({:.1f} m a.s.l.).',
                                res.cap[0], lo - res.cap[0], lo)))
    elif res.level_source == 'depth':
        add(Note(Note.INFO, Msg('Water level limited to your maximum depth of {:.1f} m above the '
                                'riverbed at the line ({:.1f} m a.s.l.), i.e. {:.1f} m a.s.l.; '
                                'the lower end of the line is {:.1f} m higher.',
                                res.cap[0] - res.line_bed, res.line_bed, res.cap[0],
                                lo - res.cap[0])))
    elif res.cap is not None:
        res.cap_ignored = True
        wanted = (Msg('maximum water level ({:.1f} m a.s.l.)', res.cap[0])
                  if res.cap[1] == 'max' else
                  Msg('maximum depth ({:.1f} m, i.e. {:.1f} m a.s.l.)',
                      res.cap[0] - res.line_bed, res.cap[0]))
        add(Note(Note.WARNING, Msg('Your {} is higher than the line can hold: water would flow '
                                   'around its lower end at {:.1f} m a.s.l., so that level is '
                                   'used. Draw the line further up the valley sides to allow '
                                   'more.', wanted, lo), 'cap'))
    if res.limited_by == 'saddle':
        add(Note(Note.WARNING, Msg('Water escapes through a low point in the rim at {:.1f} m '
                                   'a.s.l., below the intended level ({:.1f} m a.s.l.). The '
                                   'reservoir is shown at {:.1f} m a.s.l.; the escape point is '
                                   'marked on the map.', res.water_level, target,
                                   res.water_level)))
    elif res.limited_by == 'edge':
        add(Note(Note.WARNING, Msg('The reservoir reaches the edge of the DEM at {:.1f} m '
                                   'a.s.l., so it is cut there. Use a DEM covering the whole '
                                   'valley.', res.water_level)))
    elif res.limited_by == 'nodata':
        add(Note(Note.WARNING, Msg('The reservoir reaches missing DEM data (no-data) at {:.1f} m '
                                   'a.s.l., so it is cut there.', res.water_level)))


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


def _window_edge_sides(grid, bounds, cell):
    """Sides ('w', 's', 'e', 'n') of the analysis window that ``cell`` lies on
    and that were cut by the window (a bigger window would show more); a side
    that is the DEM's own edge is left out."""
    rows, cols = grid.shape
    gx0, gy0, gx1, gy1 = grid.bounds
    bx0, by0, bx1, by1 = bounds
    tol = 1.5 * grid.cell_size
    r, c = cell
    sides = []
    if c == 0 and gx0 - bx0 <= tol:
        sides.append('w')
    if c == cols - 1 and bx1 - gx1 <= tol:
        sides.append('e')
    if r == 0 and by1 - gy1 <= tol:
        sides.append('n')
    if r == rows - 1 and gy0 - by0 <= tol:
        sides.append('s')
    return sides


def _lowest(grid, cells):
    return min(cells, key=lambda rc: grid.z[rc[0], rc[1]])


def _mask(shape, cells):
    m = np.zeros(shape, dtype=bool)
    for rr, cc in cells:
        m[rr, cc] = True
    return m
