# -*- coding: utf-8 -*-
"""Unit tests of the reservoir engine (no QGIS needed; numpy + GDAL only).

    python3 -m pytest tests
"""
import os

import numpy as np
import pytest
from osgeo import gdal, osr

from conftest import SAMPLE_AXIS, core

hydro = core('hydro')
analysis = core('analysis')
dem_sources = core('dem_sources')
terrain = core('terrain')


def make_dem(path, z, x0, y1, cell, epsg=32633, dtype=gdal.GDT_Float32, nodata=None):
    rows, cols = z.shape
    ds = gdal.GetDriverByName('GTiff').Create(path, cols, rows, 1, dtype)
    ds.SetGeoTransform((x0, cell, 0, y1, 0, -cell))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(epsg)
    ds.SetProjection(srs.ExportToWkt())
    if nodata is not None:
        ds.GetRasterBand(1).SetNoDataValue(nodata)
    ds.GetRasterBand(1).WriteArray(z)
    ds = None
    return path


def v_valley(tmp_path, s=0.2, g=0.01, cell=10.0, xmax=2000.0, ymin=-3000.0, ymax=6000.0,
             extra=None):
    """z = 100 + s|x| + g y : a straight V-shaped valley rising upstream (+y)."""
    xs = np.arange(-xmax + cell / 2, xmax, cell)
    ys = np.arange(ymax - cell / 2, ymin, -cell)
    X, Y = np.meshgrid(xs, ys)
    z = 100.0 + s * np.abs(X) + g * Y
    if extra is not None:
        z = extra(X, Y, z)
    return make_dem(str(tmp_path / 'valley.tif'), z.astype(np.float32), -xmax, ymax, cell)


def run(dem, line, crs='EPSG:32633', **kw):
    return analysis.run(analysis.Params(dem, line, crs, **kw))


def test_water_level_is_the_lower_line_end_and_matches_analytic_volume(tmp_path):
    s, g = 0.2, 0.01
    dem = v_valley(tmp_path, s, g)
    # ends at x=-150 (ground 130 m) and x=+100 (ground 120 m) -> level 120 m
    r = run(dem, [(-150, 0), (100, 0)])
    assert r.water_level == pytest.approx(120.0, abs=0.01)
    assert r.end_levels == (pytest.approx(130.0, abs=0.01), pytest.approx(120.0, abs=0.01))
    assert r.limited_by is None
    assert r.side == 'left'                       # drawn west->east, valley rises to the north
    d = 20.0
    assert r.area_m2 == pytest.approx(d ** 2 / (g * s), rel=0.03)        # A = D^2/(g s)
    assert r.volume_m3 == pytest.approx(d ** 3 / (3 * g * s), rel=0.03)  # V = D^3/(3 g s)
    lv, a, v = r.curve()
    assert lv[-1] == pytest.approx(120.0) and np.all(np.diff(v) >= 0)
    assert v[-1] == pytest.approx(r.volume_m3)
    assert r.polygon_wkt and 'POLYGON' in r.polygon_wkt


def test_drawing_direction_does_not_matter(tmp_path):
    dem = v_valley(tmp_path)
    a = run(dem, [(-150, 0), (100, 0)])
    b = run(dem, [(100, 0), (-150, 0)])
    assert b.side == 'right'
    assert a.volume_m3 == pytest.approx(b.volume_m3, rel=1e-6)


def test_low_saddle_lowers_the_level(tmp_path):
    # a notch in the east valley wall at y=1000 m, 5 m above... the valley floor there
    def notch(X, Y, z):
        cut = (np.abs(Y - 1000) < 30) & (X > 0)
        z[cut] = np.minimum(z[cut], 112.0)          # escape route at 112 m
        return z
    dem = v_valley(tmp_path, extra=notch)
    r = run(dem, [(-150, 0), (100, 0)])
    assert r.limited_by in ('saddle', 'edge')
    assert r.water_level == pytest.approx(112.0, abs=0.5)
    assert any('low point' in n.text or 'edge' in n.text for n in r.notes)


def test_isolated_hollow_is_not_counted(tmp_path):
    # a deep pit on the valley side, above the water level's shoreline
    def pit(X, Y, z):
        z[(X - 300) ** 2 + (Y - 500) ** 2 <= 30 ** 2] = 105.0
        return z
    dem = v_valley(tmp_path, extra=pit)
    r = run(dem, [(-150, 0), (100, 0)])
    row, col = r.grid.to_cell(300.0, 500.0)
    assert not (r.spill[int(round(float(row))), int(round(float(col)))] <= r.water_level)
    assert r.volume_m3 == pytest.approx(20.0 ** 3 / (3 * 0.01 * 0.2), rel=0.03)


def test_window_grows_until_the_reservoir_fits(tmp_path):
    # long flat valley: the reservoir is 10 km long, the first window is only 5 km
    dem = v_valley(tmp_path, s=0.2, g=0.002, ymax=14000.0)
    r = run(dem, [(-150, 0), (100, 0)])
    assert r.radius_m > 5000.0
    assert r.limited_by is None
    assert r.volume_m3 == pytest.approx(20.0 ** 3 / (3 * 0.002 * 0.2), rel=0.03)


def test_flip_side_puts_water_downstream(tmp_path):
    dem = v_valley(tmp_path)
    r = run(dem, [(-150, 0), (100, 0)], side='right')
    assert r.side == 'right'
    # downstream the water just runs off the DEM at the river-bed level
    assert r.limited_by == 'edge' and r.water_level < 101.0
    assert r.radius_m == pytest.approx(analysis.initial_radius([(-150, 0), (100, 0)],
                                                               'EPSG:32633'))  # no useless growth


def test_line_not_crossing_a_valley_is_rejected(tmp_path):
    dem = v_valley(tmp_path)
    with pytest.raises(terrain.TerrainError):
        run(dem, [(300, 0), (600, 0)])             # both on the same slope


def test_sample_dam(sample_dem):
    r = run(sample_dem, SAMPLE_AXIS, 'EPSG:32637')
    assert r.side == 'left'
    assert r.water_level == pytest.approx(min(r.end_levels))
    assert r.water_level == pytest.approx(931.2, abs=0.5)
    assert r.limited_by is None
    assert r.volume_m3 / 1e6 == pytest.approx(328.2, rel=0.02)
    assert r.area_m2 / 1e6 == pytest.approx(8.23, rel=0.03)
    assert r.bed_level == pytest.approx(811.0, abs=1.0)


def test_geographic_dem_is_reprojected(tmp_path, sample_dem):
    geo = str(tmp_path / 'dem_4326.tif')
    gdal.Warp(geo, sample_dem, dstSRS='EPSG:4326', resampleAlg='bilinear', srcNodata=0,
              dstNodata=-9999)
    r = run(geo, SAMPLE_AXIS, 'EPSG:32637')
    assert osr.SpatialReference(wkt=r.grid.srs_wkt).GetAuthorityCode(None) == '32637'
    assert r.volume_m3 / 1e6 == pytest.approx(328.2, rel=0.05)


def test_integer_decimetre_dem_is_scaled(tmp_path, sample_dem):
    """GEDTM30-like input: EPSG:4326, Int32 decimetres, no scale metadata."""
    src = gdal.Warp('', sample_dem, format='MEM', dstSRS='EPSG:4326', srcNodata=0,
                    dstNodata=-2147483648, outputType=gdal.GDT_Float64)
    a = src.GetRasterBand(1).ReadAsArray()
    a = np.where(a == -2147483648, a, np.round(a * 10)).astype(np.int32)
    dm = make_dem(str(tmp_path / 'dm.tif'), a, 0, 0, 1, dtype=gdal.GDT_Int32,
                  nodata=-2147483648)
    ds = gdal.Open(dm, gdal.GA_Update)
    ds.SetGeoTransform(src.GetGeoTransform())
    ds.SetProjection(src.GetProjection())
    ds = None
    work, _c, bounds, _lat = analysis.plan_frame(SAMPLE_AXIS, 'EPSG:32637', 5000)
    out, _n = dem_sources.download_dem('gedtm30', bounds, work, str(tmp_path / 'o.tif'),
                                       gedtm30_url=dm)
    z = gdal.Open(out).ReadAsArray()
    z = z[z != -9999]
    assert 700 < z.min() < 1000 and z.max() < 3000   # metres, not decimetres


def test_download_can_be_cancelled(tmp_path, sample_dem):
    class Stop(analysis.Feedback):
        def is_cancelled(self):
            return True
    work, _c, bounds, _lat = analysis.plan_frame(SAMPLE_AXIS, 'EPSG:32637', 5000)
    out = str(tmp_path / 'o.tif')
    with pytest.raises(hydro.Cancelled):
        dem_sources.download_dem('gedtm30', bounds, work, out, gedtm30_url=sample_dem,
                                 feedback=Stop())
    assert not os.path.exists(out)


def test_capacity_table_simple():
    t = hydro.CapacityTable(np.array([1.0, 1.0, 2.0, 3.0]), np.array([0.0, 1.0, 2.0, 3.0]), 10.0)
    assert t.area(0.5) == 0 and t.area(1.5) == 20.0
    assert t.volume(2.0) == pytest.approx(10.0 * (2 + 1 + 0))


def test_find_gedtm30_url_prefers_newest_mean_dtm():
    text = ('{"metadata":{"description":"<a href=\\"https://s3.opengeohub.org/global/edtm/'
            'gedtm_rf_m_30m_s_20060101_20151231_go_epsg.4326.3855_v20260201.tif\\">x</a> '
            'https://s3.opengeohub.org/global/edtm/gedtm_rf_m_30m_s_20060101_20151231_go_'
            'epsg.4326.3855_v20250611.tif https://s3.opengeohub.org/global/edtm/'
            'gedtm_rf_std_30m_s_v20260301.tif"}}')
    url = dem_sources.find_gedtm30_url(text)
    assert url.endswith('_v20260201.tif') and 'gedtm_rf_m_' in url
    assert dem_sources.resolve_gedtm30_url(lambda u: text) == (url, 'zenodo')
    assert dem_sources.resolve_gedtm30_url(lambda u: 1 / 0)[1] == 'fallback'


def test_copernicus_tiles():
    urls = dem_sources.copernicus_tile_urls(41.9, 40.7, 42.1, 40.9)
    assert len(urls) == 2
    assert urls[0].endswith('Copernicus_DSM_COG_10_N40_00_E041_00_DEM.tif')
