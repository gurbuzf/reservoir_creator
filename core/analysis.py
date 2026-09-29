# -*- coding: utf-8 -*-
"""
End-to-end reservoir analysis: DEM window -> dam barrier -> upstream
detection -> priority flood -> elevation-area-capacity model.

The entry point is :func:`run_analysis`, which returns a
:class:`ReservoirModel`.  The model answers every "what if the water level
were h?" question cheaply, so the GUI can scrub through water levels
interactively.
"""

import math

import numpy as np

from . import hydro, terrain
from .terrain import TerrainError


class Feedback:
    """Minimal progress/cancel interface (overridden by the QGIS task)."""

    def set_progress(self, percent):
        pass

    def set_status(self, text):
        pass

    def is_cancelled(self):
        return False


class AnalysisParams:
    """All user inputs of an analysis run.

    Elevations are in metres above the DEM's vertical datum.  ``None`` means
    "automatic" for the optional values.
    """

    def __init__(self, dem_path, dam_coords, dam_crs, **kw):
        self.dem_path = dem_path
        self.dam_coords = [(float(x), float(y)) for x, y in dam_coords]
        self.dam_crs = dam_crs
        self.radius_m = float(kw.get('radius_m', 10000.0))
        self.upstream = kw.get('upstream', 'auto')        # auto | left | right
        self.max_level = kw.get('max_level')
        self.step = kw.get('step')
        self.nwl = kw.get('nwl')
        self.mol = kw.get('mol')
        self.freeboard = float(kw.get('freeboard', 3.0))
        self.crest_width = float(kw.get('crest_width', 10.0))
        self.slope_us = float(kw.get('slope_us', 3.0))
        self.slope_ds = float(kw.get('slope_ds', 2.5))
        self.inflow_m3s = kw.get('inflow_m3s')
        self.max_cells = int(kw.get('max_cells', 6_000_000))
        self.dem_scale = kw.get('dem_scale')
        self.dem_offset = kw.get('dem_offset')


class Note:
    INFO, WARNING, CRITICAL = 'info', 'warning', 'critical'

    def __init__(self, level, text):
        self.level = level
        self.text = text

    def __repr__(self):
        return '[{}] {}'.format(self.level, self.text)


class ReservoirModel:
    """Result of an analysis.  All lengths in m, areas in m2, volumes in m3."""

    def __init__(self):
        self.params = None
        self.grid = None
        self.blocked = None
        self.flood = None
        self.table = None
        self.notes = []
        self.dam_coords = []            # in the working CRS
        self.stations = None            # dam axis profile
        self.profile_xy = None
        self.ground = None
        self.thalweg = None             # (x, y, z) lowest point on the axis
        self.upstream_side = None       # 'left' | 'right' of drawing direction
        self.upstream_auto = True
        self.seed_up = None
        self.seed_down = None
        self.bed_level = None           # lowest point in the reservoir
        self.max_level = None           # maximum impoundable level
        self.limit_reason = None
        self.pour_point = None          # (x, y) controlling max_level
        self.default_nwl = None
        self.step = None
        self.levels = None
        self._dist_cummax = None
        self._zmin_cummin = None

    # -- basic curve --------------------------------------------------------
    @property
    def srs_wkt(self):
        return self.grid.srs_wkt

    def area(self, level):
        return float(self.table.area(level))

    def volume(self, level):
        return float(self.table.volume(level))

    def clamp_level(self, level):
        return float(min(max(level, self.bed_level), self.max_level))

    def curve(self, step=None):
        """(levels, area_m2, volume_m3) for the EAC table."""
        step = step or self.step
        lv = hydro.level_series(self.bed_level, self.max_level, step)
        return lv, self.table.area(lv), self.table.volume(lv)

    # -- per level statistics -----------------------------------------------
    def _count(self, level):
        return int(self.table.counts(level))

    def max_depth(self, level):
        n = self._count(level)
        if n == 0:
            return 0.0
        return float(level - self._zmin_cummin[n - 1])

    def reservoir_length(self, level):
        """Longest path from the dam through the water body (m)."""
        n = self._count(level)
        if n == 0 or self._dist_cummax is None:
            return 0.0
        return float(self._dist_cummax[n - 1] + 0.5 * self.grid.cell_size)

    def dam(self, nwl):
        """Embankment figures for a normal water level ``nwl``."""
        p = self.params
        crest = nwl + p.freeboard
        emb = hydro.embankment(self.stations, self.ground, crest,
                               p.crest_width, p.slope_us, p.slope_ds)
        emb['crest_level'] = crest
        ends = [self.ground[0], self.ground[-1]]
        emb['axis_too_short'] = bool(np.nanmin(ends) < crest)
        return emb

    def stats(self, level, with_polygon=True):
        """Every planning indicator for a water level, as a dict."""
        p = self.params
        level = self.clamp_level(level)
        a = self.area(level)
        v = self.volume(level)
        s = {
            'level': level,
            'area_m2': a,
            'volume_m3': v,
            'mean_depth': v / a if a > 0 else 0.0,
            'max_depth': self.max_depth(level),
            'length_m': self.reservoir_length(level),
            'bed_level': self.bed_level,
            'max_level': self.max_level,
        }
        dam = self.dam(level)
        s.update({
            'crest_level': dam['crest_level'],
            'dam_height': dam['height'],
            'crest_length': dam['crest_length'],
            'fill_m3': dam['fill_volume'],
            'axis_too_short': dam['axis_too_short'],
            'storage_fill_ratio': v / dam['fill_volume'] if dam['fill_volume'] > 0 else float('nan'),
        })
        if p.mol is not None and p.mol > self.bed_level:
            dead = self.volume(min(p.mol, level))
            s['dead_m3'] = dead
            s['live_m3'] = v - dead
        if p.inflow_m3s:
            annual = p.inflow_m3s * hydro.SECONDS_PER_YEAR
            s['ci_ratio'] = v / annual
            s['trap_eff'] = hydro.brune_trap_efficiency(v, annual)
            s['residence_days'] = hydro.residence_time_days(v, p.inflow_m3s)
        if with_polygon:
            wkt, parea, shore = self.polygon(level)
            s['polygon_wkt'] = wkt
            s['shoreline_m'] = shore
            s['sdi'] = hydro.shoreline_development(shore, parea) if parea > 0 else float('nan')
        return s

    def polygon(self, level):
        return terrain.water_surface_polygon(self.grid, self.flood.spill, level, self.blocked)

    def depth_array(self, level):
        wet = self.flood.spill <= level
        return np.where(wet, level - self.grid.z, np.nan)

    def sizing(self, step=None):
        """Dam sizing curves over normal water levels.

        Returns dict of arrays: nwl, volume, fill, ratio, crest_length,
        height, axis_ok.
        """
        lv, _, vol = self.curve(step)
        keep = lv > self.bed_level + 1e-6
        lv, vol = lv[keep], vol[keep]
        out = {k: [] for k in ('fill', 'crest_length', 'height', 'axis_ok')}
        for h in lv:
            d = self.dam(h)
            out['fill'].append(d['fill_volume'])
            out['crest_length'].append(d['crest_length'])
            out['height'].append(d['height'])
            out['axis_ok'].append(not d['axis_too_short'])
        res = {k: np.asarray(v) for k, v in out.items()}
        res['nwl'] = lv
        res['volume'] = vol
        with np.errstate(divide='ignore', invalid='ignore'):
            res['ratio'] = np.where(res['fill'] > 0, vol / res['fill'], np.nan)
        return res


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def _profile(grid, coords, step):
    """Sample the DEM along the dam axis every ``step`` metres."""
    pts = np.asarray(coords, dtype=np.float64)
    seg = np.hypot(np.diff(pts[:, 0]), np.diff(pts[:, 1]))
    cum = np.concatenate(([0.0], np.cumsum(seg)))
    total = cum[-1]
    n = max(2, int(math.ceil(total / step)) + 1)
    st = np.linspace(0.0, total, n)
    st = np.unique(np.concatenate((st, cum)))
    xs = np.interp(st, cum, pts[:, 0])
    ys = np.interp(st, cum, pts[:, 1])
    seg_idx = np.clip(np.searchsorted(cum, st, side='right') - 1, 0, len(seg) - 1)
    return st, xs, ys, grid.sample(xs, ys), seg_idx


def _side_cells(grid, blocked, open_mask, centre_xy, direction, radius_cells=3):
    """Candidate seed cells left/right of the dam near its thalweg."""
    r, c = grid.to_cell(*centre_xy)
    r, c = int(round(float(r))), int(round(float(c)))
    rows, cols = grid.shape
    dx, dy = direction
    left, right = [], []
    for rr in range(max(1, r - radius_cells), min(rows - 1, r + radius_cells + 1)):
        for cc in range(max(1, c - radius_cells), min(cols - 1, c + radius_cells + 1)):
            if blocked[rr, cc] or open_mask[rr, cc] or np.isnan(grid.z[rr, cc]):
                continue
            x, y = grid.cell_center(rr, cc)
            cross = dx * (y - centre_xy[1]) - dy * (x - centre_xy[0])
            if cross > 0:
                left.append((rr, cc))
            elif cross < 0:
                right.append((rr, cc))
    return left, right


def _lowest(grid, cells):
    return min(cells, key=lambda rc: grid.z[rc[0], rc[1]])


def _cells_mask(shape, cells):
    m = np.zeros(shape, dtype=bool)
    for rr, cc in cells:
        m[rr, cc] = True
    return m


def plan_frame(dam_coords, dam_crs, radius_m, dem_srs=None):
    """Working CRS, dam coordinates and analysis bounds for a dam axis.

    The working CRS is the DEM's own CRS when it is projected in metres,
    otherwise the local UTM zone of the dam.

    Returns (work_srs, coords_in_work_crs, bounds, latitude)
    """
    dam_srs = terrain.make_srs(dam_crs)
    ll = terrain.transform_points(dam_coords, dam_srs, terrain.geographic_srs())
    lon = float(np.mean([p[0] for p in ll]))
    lat = float(np.mean([p[1] for p in ll]))
    if dem_srs is not None:
        work_srs = terrain.choose_working_srs(dem_srs, lon, lat)
    else:
        work_srs = terrain.utm_srs_for(lon, lat)
    coords = terrain.transform_points(dam_coords, dam_srs, work_srs)
    xs = [p[0] for p in coords]
    ys = [p[1] for p in coords]
    r = float(radius_m)
    bounds = (min(xs) - r, min(ys) - r, max(xs) + r, max(ys) + r)
    return work_srs, coords, bounds, lat


def run_analysis(params, feedback=None):
    """Run the reservoir analysis and return a :class:`ReservoirModel`."""
    fb = feedback or Feedback()
    model = ReservoirModel()
    model.params = params
    notes = model.notes

    if len(params.dam_coords) < 2:
        raise TerrainError('The dam axis needs at least two vertices.')

    # 1. working CRS and DEM window ----------------------------------------
    fb.set_status('Reading elevation data…')
    fb.set_progress(2)
    info = terrain.dem_info(params.dem_path)
    work_srs, coords, bounds, lat = plan_frame(
        params.dam_coords, params.dam_crs, params.radius_m,
        terrain.make_srs(info['srs_wkt']))
    model.dam_coords = coords
    grid, grid_notes = terrain.read_dem_window(
        params.dem_path, work_srs, bounds, max_cells=params.max_cells, lat=lat,
        scale=params.dem_scale, offset=params.dem_offset)
    notes.extend(Note(Note.INFO, t) for t in grid_notes)
    model.grid = grid
    if fb.is_cancelled():
        raise hydro.Cancelled()

    # 2. dam barrier and axis profile ---------------------------------------
    fb.set_status('Preparing dam axis…')
    fb.set_progress(10)
    blocked = terrain.rasterize_polyline(grid, coords)
    model.blocked = blocked
    st, pxs, pys, ground, seg_idx = _profile(grid, coords, grid.cell_size / 2.0)
    if np.isnan(ground).all():
        raise TerrainError('The dam axis lies outside the DEM (no elevations along it).')
    model.stations, model.ground = st, ground
    model.profile_xy = (pxs, pys)
    k = int(np.nanargmin(ground))
    model.thalweg = (float(pxs[k]), float(pys[k]), float(ground[k]))
    if np.isnan(ground).any():
        notes.append(Note(Note.WARNING, 'Part of the dam axis has no DEM data.'))
    if k in (0, len(ground) - 1):
        notes.append(Note(Note.WARNING,
                          'The lowest point of the dam axis is at one of its ends - '
                          'the axis may not cross the valley.'))

    si = int(seg_idx[k])
    d = np.subtract(coords[si + 1], coords[si])
    d = d / (np.hypot(*d) or 1.0)
    open_mask = hydro.open_boundary_mask(grid.z)
    left, right = _side_cells(grid, blocked, open_mask, model.thalweg[:2], d)
    if not left or not right:
        raise TerrainError('The dam axis is too close to the DEM edge or no-data area.')
    seed_l, seed_r = _lowest(grid, left), _lowest(grid, right)
    mask_l, mask_r = _cells_mask(grid.shape, left), _cells_mask(grid.shape, right)
    max_level = params.max_level if params.max_level is not None else math.inf
    progress = _flood_progress(fb, 15, 80, model.thalweg[2], params)

    # 3. upstream side ------------------------------------------------------
    reuse = None
    if params.upstream in ('left', 'right'):
        side = params.upstream
        model.upstream_auto = False
    else:
        fb.set_status('Detecting the upstream side…')
        cap = 250_000
        fl = hydro.priority_flood(grid.z, seed_l, blocked, stop_cells=mask_r,
                                  max_level=max_level, max_cells=cap,
                                  is_cancelled=fb.is_cancelled)
        fr = hydro.priority_flood(grid.z, seed_r, blocked, stop_cells=mask_l,
                                  max_level=max_level, max_cells=cap,
                                  is_cancelled=fb.is_cancelled)
        if abs(fl.rise - fr.rise) > 0.5:
            side = 'left' if fl.rise > fr.rise else 'right'
        else:
            side = 'left' if fl.seed_level >= fr.seed_level else 'right'
            notes.append(Note(Note.WARNING,
                              'Upstream side is ambiguous; please check the result '
                              'and flip the side if needed.'))
        chosen = fl if side == 'left' else fr
        if chosen.reason != hydro.STOP_CELL_LIMIT:
            reuse = chosen
    model.upstream_side = side
    seed_up, seed_down = (seed_l, seed_r) if side == 'left' else (seed_r, seed_l)
    stop_mask = mask_r if side == 'left' else mask_l
    model.seed_up = grid.cell_center(*seed_up)
    model.seed_down = grid.cell_center(*seed_down)

    # 4. main flood ---------------------------------------------------------
    fb.set_status('Flooding the reservoir…')
    fb.set_progress(15)
    flood = reuse or hydro.priority_flood(
        grid.z, seed_up, blocked, stop_cells=stop_mask, max_level=max_level,
        progress=progress, is_cancelled=fb.is_cancelled)
    model.flood = flood
    domain = np.isfinite(flood.spill) & (flood.spill < flood.limit_level + 1e-9)
    if flood.reason == hydro.STOP_MAX_LEVEL:
        domain = np.isfinite(flood.spill)
    if domain.sum() < 4:
        raise TerrainError('No reservoir forms behind this dam axis. Check the dam '
                           'position, the upstream side and the DEM.')
    model.limit_reason = flood.reason
    model.max_level = float(flood.limit_level)
    if flood.pour_cell is not None:
        model.pour_point = tuple(float(v) for v in grid.cell_center(*flood.pour_cell))
    _explain_limit(model, d)

    # 5. EAC model ----------------------------------------------------------
    fb.set_status('Building elevation-area-capacity curves…')
    fb.set_progress(82)
    sp = flood.spill[domain]
    zz = grid.z[domain]
    model.table = hydro.CapacityTable(sp, zz, grid.cell_area)
    order = np.argsort(sp, kind='stable')
    model._zmin_cummin = np.minimum.accumulate(zz[order])
    model.bed_level = float(np.min(sp))
    span = model.max_level - model.bed_level
    model.step = float(params.step) if params.step else hydro.nice_step(span)

    # reservoir length (geodesic distance from the dam's upstream face)
    fb.set_status('Measuring reservoir length…')
    fb.set_progress(88)
    face = np.zeros_like(blocked)
    face[1:, :] |= blocked[:-1, :]
    face[:-1, :] |= blocked[1:, :]
    face[:, 1:] |= blocked[:, :-1]
    face[:, :-1] |= blocked[:, 1:]
    try:
        dist = hydro.geodesic_distance(domain, face & domain, grid.cell_size,
                                       is_cancelled=fb.is_cancelled)
        dd = dist[domain][order]
        dd[~np.isfinite(dd)] = 0.0
        model._dist_cummax = np.maximum.accumulate(dd)
    except MemoryError:
        model._dist_cummax = None

    # default normal water level
    if params.nwl is not None:
        model.default_nwl = model.clamp_level(params.nwl)
    else:
        # the crest (NWL + freeboard) must stay within the drawn axis and
        # below the level at which water escapes
        top = model.max_level
        ends = [g for g in (model.ground[0], model.ground[-1]) if np.isfinite(g)]
        if ends:
            top = min(top, min(ends))
        guess = math.floor((top - params.freeboard) * 2.0) / 2.0
        model.default_nwl = model.clamp_level(max(guess, model.bed_level + model.step))
    if params.mol is not None and params.mol >= model.default_nwl:
        notes.append(Note(Note.WARNING, 'Minimum operating level is above the normal water level.'))

    fb.set_progress(100)
    fb.set_status('Done')
    return model


def _flood_progress(fb, p0, p1, z0, params):
    def cb(level, count):
        fb.set_status('Flooding… water level {:.1f} m ({:,} cells)'.format(level, count))
        if params.max_level is not None and params.max_level > z0:
            frac = (level - z0) / (params.max_level - z0)
        else:
            frac = 1.0 - 1.0 / (1.0 + count / 200000.0)
        fb.set_progress(int(p0 + (p1 - p0) * max(0.0, min(1.0, frac))))
    return cb


def _bank_of(model, point, axis_dir):
    """'left' or 'right' bank (looking downstream) of a map point."""
    tx, ty, _ = model.thalweg
    # unit normal pointing downstream
    nx, ny = -axis_dir[1], axis_dir[0]          # left of drawing direction
    if model.upstream_side == 'left':
        nx, ny = -nx, -ny                       # downstream is to the right
    # left bank = 90 deg counter-clockwise from the downstream direction
    lx, ly = -ny, nx
    return 'left' if (point[0] - tx) * lx + (point[1] - ty) * ly > 0 else 'right'


def _explain_limit(model, axis_dir):
    notes = model.notes
    lvl = model.max_level
    reason = model.limit_reason
    ends = [(model.dam_coords[0], model.ground[0]), (model.dam_coords[-1], model.ground[-1])]
    if reason == hydro.STOP_BYPASS:
        low_end = min(ends, key=lambda e: e[1] if np.isfinite(e[1]) else 1e9)
        tol = max(1.0, 0.1 * model.grid.cell_size)
        if np.isfinite(low_end[1]) and lvl >= low_end[1] - tol:
            bank = _bank_of(model, low_end[0], axis_dir)
            notes.append(Note(Note.INFO,
                              'Maximum impoundable level {:.1f} m: above it water flows around '
                              'the {} end of the dam axis (ground {:.1f} m). Extend the axis '
                              'into the {} abutment to impound higher.'
                              .format(lvl, bank, low_end[1], bank)))
        else:
            notes.append(Note(Note.WARNING,
                              'Maximum impoundable level {:.1f} m is controlled by a saddle away '
                              'from the dam (marked on the map). A saddle dam would be needed '
                              'to impound higher.'.format(lvl)))
    elif reason == hydro.STOP_EDGE:
        notes.append(Note(Note.WARNING,
                          'At {:.1f} m the reservoir reaches the edge of the analysis area. '
                          'Increase the analysis radius to see higher levels.'.format(lvl)))
    elif reason == hydro.STOP_NODATA:
        notes.append(Note(Note.WARNING,
                          'At {:.1f} m the reservoir reaches a DEM void (no-data). '
                          'Results above this level are unknown.'.format(lvl)))
    elif reason == hydro.STOP_MAX_LEVEL:
        notes.append(Note(Note.INFO, 'Analysis limited to the requested maximum level '
                                     '{:.1f} m.'.format(lvl)))
