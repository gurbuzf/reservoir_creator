# -*- coding: utf-8 -*-
"""
GDAL/OGR helpers: reading a DEM window in a metric CRS, rasterising the dam
axis, vectorising the water surface and writing rasters.

Only ``osgeo`` and ``numpy`` are used (both ship with every QGIS install), so
this module works inside QGIS, in a background task and in plain unit tests.
"""

import math

import numpy as np
from osgeo import gdal, ogr, osr

from .i18n import Msg, tr

# Elevations outside this range are treated as no-data (catches unflagged
# -9999 / -32768 / int32-min fill values).
VALID_Z_RANGE = (-1000.0, 9500.0)


class TerrainError(Exception):
    """Raised for user-facing problems with the DEM or the dam axis."""


# ---------------------------------------------------------------------------
# Spatial references
# ---------------------------------------------------------------------------

def make_srs(definition):
    """Build an ``osr.SpatialReference`` (x=easting/longitude axis order)."""
    srs = osr.SpatialReference()
    if isinstance(definition, osr.SpatialReference):
        srs.ImportFromWkt(definition.ExportToWkt())
    elif definition.upper().startswith(('EPSG:', 'ESRI:', 'IGNF:', 'OGC:')) or \
            definition.startswith('+proj'):
        srs.SetFromUserInput(definition)
    else:
        if srs.ImportFromWkt(definition) != 0:
            srs.SetFromUserInput(definition)
    srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    return srs


def is_metric_projected(srs):
    return bool(srs.IsProjected()) and abs(srs.GetLinearUnits() - 1.0) < 1e-6


def utm_srs_for(lon, lat):
    zone = int(math.floor((lon + 180.0) / 6.0)) % 60 + 1
    srs = osr.SpatialReference()
    srs.ImportFromEPSG((32600 if lat >= 0 else 32700) + zone)
    srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    return srs


def geographic_srs():
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    return srs


def transform_points(points, src_srs, dst_srs):
    if src_srs.IsSame(dst_srs):
        return [(float(x), float(y)) for x, y in points]
    ct = osr.CoordinateTransformation(src_srs, dst_srs)
    out = []
    for x, y in points:
        tx, ty, _ = ct.TransformPoint(float(x), float(y))
        out.append((tx, ty))
    return out


# ---------------------------------------------------------------------------
# Grid container
# ---------------------------------------------------------------------------

class Grid:
    """A north-up elevation grid in a metric CRS (NaN = no data)."""

    def __init__(self, z, geotransform, srs_wkt):
        self.z = z
        self.gt = tuple(geotransform)
        self.srs_wkt = srs_wkt

    @property
    def shape(self):
        return self.z.shape

    @property
    def cell_w(self):
        return abs(self.gt[1])

    @property
    def cell_h(self):
        return abs(self.gt[5])

    @property
    def cell_area(self):
        return self.cell_w * self.cell_h

    @property
    def cell_size(self):
        return math.sqrt(self.cell_area)

    @property
    def bounds(self):
        rows, cols = self.shape
        x0, y0 = self.gt[0], self.gt[3]
        return (x0, y0 + rows * self.gt[5], x0 + cols * self.gt[1], y0)

    def to_cell(self, x, y):
        """Fractional (row, col) of map coordinates (cell centre = integer)."""
        col = (np.asarray(x) - self.gt[0]) / self.gt[1] - 0.5
        row = (np.asarray(y) - self.gt[3]) / self.gt[5] - 0.5
        return row, col

    def cell_center(self, row, col):
        x = self.gt[0] + (np.asarray(col) + 0.5) * self.gt[1]
        y = self.gt[3] + (np.asarray(row) + 0.5) * self.gt[5]
        return x, y

    def sample(self, xs, ys):
        """Bilinear interpolation of the grid at map coordinates."""
        r, c = self.to_cell(xs, ys)
        r = np.atleast_1d(r).astype(np.float64)
        c = np.atleast_1d(c).astype(np.float64)
        rows, cols = self.shape
        r0 = np.clip(np.floor(r).astype(int), 0, rows - 2)
        c0 = np.clip(np.floor(c).astype(int), 0, cols - 2)
        fr = np.clip(r - r0, 0.0, 1.0)
        fc = np.clip(c - c0, 0.0, 1.0)
        z = self.z
        v = (z[r0, c0] * (1 - fr) * (1 - fc) + z[r0, c0 + 1] * (1 - fr) * fc +
             z[r0 + 1, c0] * fr * (1 - fc) + z[r0 + 1, c0 + 1] * fr * fc)
        outside = (r < -0.5) | (c < -0.5) | (r > rows - 0.5) | (c > cols - 0.5)
        v[outside] = np.nan
        return v

    def mem_dataset(self, array, gdal_type=gdal.GDT_Float64, nodata=None):
        rows, cols = array.shape
        ds = gdal.GetDriverByName('MEM').Create('', cols, rows, 1, gdal_type)
        ds.SetGeoTransform(self.gt)
        ds.SetProjection(self.srs_wkt)
        band = ds.GetRasterBand(1)
        if nodata is not None:
            band.SetNoDataValue(nodata)
        band.WriteArray(array)
        return ds


# ---------------------------------------------------------------------------
# DEM reading
# ---------------------------------------------------------------------------

def dem_info(path):
    try:
        ds = gdal.Open(path)
    except RuntimeError:            # gdal.UseExceptions() is active
        ds = None
    if ds is None:
        raise TerrainError(tr('Cannot open the DEM: {}').format(path))
    band = ds.GetRasterBand(1)
    info = {
        'srs_wkt': ds.GetProjection(),
        'gt': ds.GetGeoTransform(),
        'size': (ds.RasterXSize, ds.RasterYSize),
        'dtype': band.DataType,
        'is_integer': band.DataType in (gdal.GDT_Byte, gdal.GDT_Int16, gdal.GDT_UInt16,
                                        gdal.GDT_Int32, gdal.GDT_UInt32),
        'scale': band.GetScale(),
        'offset': band.GetOffset(),
        'nodata': band.GetNoDataValue(),
    }
    if not info['srs_wkt']:
        raise TerrainError(tr('The DEM has no coordinate reference system.'))
    return info


def choose_working_srs(dem_srs, lon, lat):
    """Use the DEM CRS when it is projected in metres, otherwise local UTM."""
    if is_metric_projected(dem_srs):
        return dem_srs
    return utm_srs_for(lon, lat)


def native_resolution_m(info, lat):
    """Approximate DEM cell size in metres."""
    srs = make_srs(info['srs_wkt'])
    gt = info['gt']
    dx, dy = abs(gt[1]), abs(gt[5])
    if srs.IsGeographic():
        dx *= 111320.0 * math.cos(math.radians(lat))
        dy *= 110574.0
    else:
        unit = srs.GetLinearUnits() or 1.0
        dx *= unit
        dy *= unit
    return math.sqrt(dx * dy)


def _finalise(z, nodata, scale, offset, notes):
    z = z.astype(np.float64)
    if nodata is not None:
        z[z == nodata] = np.nan
    else:
        # Many DEMs carry an unflagged collar / sea mask of exact zeros.
        zeros = z == 0
        if zeros.mean() > 0.01:
            z[zeros] = np.nan
            notes.append(Msg('The DEM has no no-data value; cells equal to 0 were treated '
                             'as no-data.'))
    if scale not in (None, 1.0) or offset not in (None, 0.0):
        z = z * (scale if scale is not None else 1.0) + (offset or 0.0)
    z[(z < VALID_Z_RANGE[0]) | (z > VALID_Z_RANGE[1])] = np.nan
    return z


FAST_MODE_CELLS = 6_000_000
MAX_FULL_RES_CELLS = 30_000_000   # ~240 MB per float64 array; beyond this QGIS may run out of memory


def _too_large(cells, res):
    return TerrainError(tr(
        'At full resolution ({:.1f} m cells) the analysis area holds {:,.0f} million cells, '
        'more than this computer can safely process ({:,.0f} million). Turn on "Fast mode" '
        'to reduce the resolution, or use a DEM clipped to the valley.')
        .format(res, cells / 1e6, MAX_FULL_RES_CELLS / 1e6))


def read_dem_window(path, work_srs, bounds, max_cells=None, lat=0.0,
                    scale=None, offset=None):
    """Read the DEM over ``bounds`` (work CRS) as a :class:`Grid`.

    The DEM is read natively when it already uses ``work_srs`` (no
    resampling); otherwise it is warped with bilinear resampling to a square
    grid at its native resolution.  The resolution is only reduced when the
    caller asks for it (``max_cells``, "Fast mode"): then large windows are
    coarsened to at most ``max_cells`` cells.  Without it a window above
    ``MAX_FULL_RES_CELLS`` is refused rather than silently coarsened.

    ``scale``/``offset`` override the band's own scaling (used for integer
    products such as GEDTM30, stored in decimetres).

    Returns (grid, notes)
    """
    info = dem_info(path)
    notes = []
    dem_srs = make_srs(info['srs_wkt'])
    if scale is None:
        scale = info['scale']
    if offset is None:
        offset = info['offset']
    gt = info['gt']
    minx, miny, maxx, maxy = bounds
    same = dem_srs.IsSame(work_srs) and gt[2] == 0 and gt[4] == 0

    if same:
        cols_total, rows_total = info['size']
        x0 = int(math.floor((minx - gt[0]) / gt[1]))
        x1 = int(math.ceil((maxx - gt[0]) / gt[1]))
        y0 = int(math.floor((maxy - gt[3]) / gt[5]))
        y1 = int(math.ceil((miny - gt[3]) / gt[5]))
        x0, x1 = max(0, x0), min(cols_total, x1)
        y0, y1 = max(0, y0), min(rows_total, y1)
        if x1 - x0 < 3 or y1 - y0 < 3:
            raise TerrainError(tr('The line lies outside the DEM.'))
        xs, ys = x1 - x0, y1 - y0
        if max_cells:
            factor = max(1, int(math.ceil(math.sqrt(xs * ys / float(max_cells)))))
        elif xs * ys > MAX_FULL_RES_CELLS:
            raise _too_large(xs * ys, abs(gt[1]))
        else:
            factor = 1
        ds = gdal.Open(path)
        band = ds.GetRasterBand(1)
        bx, by = max(3, xs // factor), max(3, ys // factor)
        if factor > 1:
            notes.append(Msg('Fast mode: DEM coarsened {}x to {:.1f} m cells.',
                             factor, abs(gt[1]) * xs / bx))
            arr = band.ReadAsArray(x0, y0, xs, ys, buf_xsize=bx, buf_ysize=by,
                                   resample_alg=gdal.GRIORA_Average)
        else:
            arr = band.ReadAsArray(x0, y0, xs, ys)
        new_gt = (gt[0] + x0 * gt[1], gt[1] * xs / float(bx), 0.0,
                  gt[3] + y0 * gt[5], 0.0, gt[5] * ys / float(by))
        z = _finalise(arr, info['nodata'], scale, offset, notes)
        return Grid(z, new_gt, work_srs.ExportToWkt()), notes

    res = native_resolution_m(info, lat)
    cells = (maxx - minx) * (maxy - miny) / (res * res)
    if max_cells and cells > max_cells:
        res *= math.sqrt(cells / float(max_cells))
        notes.append(Msg('Fast mode: DEM resampled to {:.1f} m cells.', res))
    elif not max_cells and cells > MAX_FULL_RES_CELLS:
        raise _too_large(cells, res)
    res = round(res, 3)
    warp_opts = gdal.WarpOptions(
        format='MEM', dstSRS=work_srs.ExportToWkt(),
        outputBounds=(minx, miny, maxx, maxy), xRes=res, yRes=res,
        resampleAlg='bilinear', outputType=gdal.GDT_Float64,
        dstNodata=-1.0e30, multithread=True)
    try:
        ds = gdal.Warp('', path, options=warp_opts)
    except RuntimeError as e:
        raise TerrainError(tr('Could not read/reproject the DEM: {}').format(e))
    if ds is None:
        raise TerrainError(tr('Could not read/reproject the DEM: {}')
                           .format(gdal.GetLastErrorMsg()))
    arr = ds.GetRasterBand(1).ReadAsArray()
    nodata = arr <= -1.0e29
    arr[nodata] = info['nodata'] if info['nodata'] is not None else 0.0
    z = _finalise(arr, info['nodata'], scale, offset, notes)
    z[nodata] = np.nan
    if np.isnan(z).all():
        raise TerrainError(tr('The DEM has no data around the line.'))
    return Grid(z, ds.GetGeoTransform(), work_srs.ExportToWkt()), notes


# ---------------------------------------------------------------------------
# Vector <-> raster
# ---------------------------------------------------------------------------

def _mem_layer(srs_wkt, geom_type):
    drv = ogr.GetDriverByName('Memory')
    src = drv.CreateDataSource('mem')
    srs = osr.SpatialReference()
    srs.ImportFromWkt(srs_wkt)
    lyr = src.CreateLayer('l', srs=srs, geom_type=geom_type)
    return src, lyr


def rasterize_polyline(grid, coords):
    """Boolean mask of every cell touched by the polyline ``coords``."""
    rows, cols = grid.shape
    ds = gdal.GetDriverByName('MEM').Create('', cols, rows, 1, gdal.GDT_Byte)
    ds.SetGeoTransform(grid.gt)
    ds.SetProjection(grid.srs_wkt)
    src, lyr = _mem_layer(grid.srs_wkt, ogr.wkbLineString)
    line = ogr.Geometry(ogr.wkbLineString)
    for x, y in coords:
        line.AddPoint_2D(float(x), float(y))
    feat = ogr.Feature(lyr.GetLayerDefn())
    feat.SetGeometry(line)
    lyr.CreateFeature(feat)
    gdal.RasterizeLayer(ds, [1], lyr, burn_values=[1], options=['ALL_TOUCHED=TRUE'])
    return ds.GetRasterBand(1).ReadAsArray().astype(bool)


def water_surface_polygon(grid, spill, level, blocked):
    """Vectorise the water surface at ``level``.

    Uses GDAL contour polygonisation on a DEM in which every cell that is
    not part of the reservoir is lifted above the water level, giving a
    smooth, sub-pixel shoreline.  Falls back to cell outlines if needed.

    Returns (wkt, area_m2, shoreline_m) or (None, 0, 0) if nothing is flooded.
    """
    wet = spill <= level
    if not wet.any():
        return None, 0.0, 0.0
    rr, cc = np.nonzero(wet)
    rows, cols = wet.shape
    r0, r1 = max(0, rr.min() - 2), min(rows, rr.max() + 3)
    c0, c1 = max(0, cc.min() - 2), min(cols, cc.max() + 3)
    z = grid.z[r0:r1, c0:c1]
    w = wet[r0:r1, c0:c1]
    b = blocked[r0:r1, c0:c1]
    lift = level + max(0.05, 0.01 * grid.cell_size)
    e = np.where(w, np.minimum(z, level - 1e-6), np.fmax(z, lift))
    e[b & ~w] = np.fmax(e[b & ~w], lift)
    e = np.where(np.isnan(e), lift, e)
    sub_gt = (grid.gt[0] + c0 * grid.gt[1], grid.gt[1], 0.0,
              grid.gt[3] + r0 * grid.gt[5], 0.0, grid.gt[5])
    sub = Grid(e, sub_gt, grid.srs_wkt)
    ds = sub.mem_dataset(e)
    src, lyr = _mem_layer(grid.srs_wkt, ogr.wkbMultiPolygon)
    lyr.CreateField(ogr.FieldDefn('ID', ogr.OFTInteger))
    lyr.CreateField(ogr.FieldDefn('ZMIN', ogr.OFTReal))
    lyr.CreateField(ogr.FieldDefn('ZMAX', ogr.OFTReal))
    geom = None
    try:
        err = gdal.ContourGenerateEx(
            ds.GetRasterBand(1), lyr,
            options=['FIXED_LEVELS={!r}'.format(float(level)), 'POLYGONIZE=YES',
                     'ID_FIELD=0', 'ELEV_FIELD_MIN=1', 'ELEV_FIELD_MAX=2'])
        if err == 0:
            for f in lyr:
                if abs(f['ZMAX'] - level) < 1e-6:
                    g = f.GetGeometryRef()
                    if g is not None and not g.IsEmpty():
                        geom = g.Clone() if geom is None else geom.Union(g)
    except Exception:  # pragma: no cover - very old GDAL
        geom = None
    if geom is None:
        geom = _polygonize_mask(sub, w)
    if geom is None or geom.IsEmpty():
        return None, 0.0, 0.0
    if not geom.IsValid() and hasattr(geom, 'MakeValid'):
        geom = geom.MakeValid()
    boundary = geom.GetBoundary()
    shoreline = boundary.Length() if boundary is not None else 0.0
    return geom.ExportToWkt(), geom.GetArea(), shoreline


def _polygonize_mask(grid, mask):
    ds = grid.mem_dataset(mask.astype(np.uint8), gdal.GDT_Byte)
    src, lyr = _mem_layer(grid.srs_wkt, ogr.wkbPolygon)
    lyr.CreateField(ogr.FieldDefn('v', ogr.OFTInteger))
    band = ds.GetRasterBand(1)
    gdal.Polygonize(band, band, lyr, 0, [])
    geom = None
    for f in lyr:
        if f['v'] == 1:
            g = f.GetGeometryRef().Clone()
            geom = g if geom is None else geom.Union(g)
    return geom


def write_geotiff(path, grid, array, nodata=-9999.0):
    drv = gdal.GetDriverByName('GTiff')
    rows, cols = array.shape
    ds = drv.Create(path, cols, rows, 1, gdal.GDT_Float32,
                    options=['COMPRESS=DEFLATE', 'PREDICTOR=3', 'TILED=YES'])
    if ds is None:
        raise TerrainError(tr('Cannot write {}').format(path))
    ds.SetGeoTransform(grid.gt)
    ds.SetProjection(grid.srs_wkt)
    band = ds.GetRasterBand(1)
    band.SetNoDataValue(nodata)
    band.WriteArray(np.where(np.isnan(array), nodata, array).astype(np.float32))
    band.FlushCache()
    ds = None
    return path
