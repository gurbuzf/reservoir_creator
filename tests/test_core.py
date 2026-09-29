# -*- coding: utf-8 -*-
"""Unit tests of the hydrology engine (no QGIS needed; numpy + GDAL only).

    python3 -m pytest tests
"""
import math

import numpy as np
import pytest
from osgeo import gdal, osr

from conftest import SAMPLE_AXIS, core

hydro = core('hydro')
terrain = core('terrain')
analysis = core('analysis')
dem_sources = core('dem_sources')


def make_dem(path, z, x0, y1, cell, epsg=32633, nodata=None, dtype=gdal.GDT_Float32):
    rows, cols = z.shape
    ds = gdal.GetDriverByName('GTiff').Create(path, cols, rows, 1, dtype)
    ds.SetGeoTransform((x0, cell, 0, y1, 0, -cell))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(epsg)
    ds.SetProjection(srs.ExportToWkt())
    b = ds.GetRasterBand(1)
    if nodata is not None:
        b.SetNoDataValue(nodata)
    b.WriteArray(z)
    ds = None
    return path


def v_valley(tmp_path, s=0.2, g=0.01, cell=10.0, xmax=2000.0, ymin=-3000.0, ymax=6000.0,
             pit=None):
    """z = 100 + s|x| + g y : a straight V-shaped valley rising upstream (+y)."""
    xs = np.arange(-xmax + cell / 2, xmax, cell)
    ys = np.arange(ymax - cell / 2, ymin, -cell)
    X, Y = np.meshgrid(xs, ys)
    z = 100.0 + s * np.abs(X) + g * Y
    if pit is not None:
        px, py, r, bottom = pit
        z[(X - px) ** 2 + (Y - py) ** 2 <= r * r] = bottom
    return make_dem(str(tmp_path / 'valley.tif'), z.astype(np.float32), -xmax, ymax, cell)


# ---------------------------------------------------------------------------
# analytic validation
# ---------------------------------------------------------------------------

def test_v_valley_matches_analytic_area_and_volume(tmp_path):
    s, g = 0.2, 0.01
    dem = v_valley(tmp_path, s, g)
    p = analysis.AnalysisParams(dem, [(-1000, 0), (1000, 0)], 'EPSG:32633', radius_m=8000)
    m = analysis.run_analysis(p)
    assert m.upstream_side == 'left'          # drawn west->east, reservoir to the north
    assert m.limit_reason == hydro.STOP_EDGE  # valley leaves the DEM at y = 6000
    assert m.max_level == pytest.approx(100 + g * 6000, abs=1.0)
    for depth in (10.0, 30.0, 50.0):
        h = 100.0 + depth
        area = depth ** 2 / (g * s)                 # A = D^2 / (g s)
        vol = depth ** 3 / (3 * g * s)              # V = D^3 / (3 g s)
        assert m.area(h) == pytest.approx(area, rel=0.03)
        assert m.volume(h) == pytest.approx(vol, rel=0.03)
        # the V-bottom lies between cell centres: the last s*cell/(2g) metres of the
        # (sub-pixel wide) tail cannot be resolved
        assert m.reservoir_length(h) == pytest.approx(depth / g, abs=0.2 * 10 / (2 * g) + 10)


def test_bypass_around_short_dam(tmp_path):
    dem = v_valley(tmp_path, s=0.2, g=0.05)
    # ends of the axis at |x| = 500 -> ground 200 m; water goes round above that
    p = analysis.AnalysisParams(dem, [(500, 0), (-500, 0)], 'EPSG:32633', radius_m=8000)
    m = analysis.run_analysis(p)
    assert m.upstream_side == 'right'         # drawn east->west, reservoir to the north
    assert m.limit_reason == hydro.STOP_BYPASS
    assert 199.0 <= m.max_level <= 206.0
    assert m.default_nwl <= 200.0 - p.freeboard + 1e-9
    assert any('around' in n.text for n in m.notes)


def test_isolated_depression_is_not_counted(tmp_path):
    # a 180 m deep pit on the valley side where the ground is ~230 m
    dem = v_valley(tmp_path, pit=(600.0, 1000.0, 40.0, 180.0))
    p = analysis.AnalysisParams(dem, [(-1000, 0), (1000, 0)], 'EPSG:32633', radius_m=8000,
                                max_level=150.0)
    m = analysis.run_analysis(p)
    grid = m.grid
    r, c = grid.to_cell(600.0, 1000.0)
    assert not np.isfinite(m.flood.spill[int(round(float(r))), int(round(float(c)))])
    assert m.limit_reason == hydro.STOP_MAX_LEVEL
    # a level above the pit bottom must not include it
    assert m.volume(150.0) == pytest.approx(50.0 ** 3 / (3 * 0.01 * 0.2), rel=0.03)


def test_explicit_upstream_side_is_respected(tmp_path):
    dem = v_valley(tmp_path)
    p = analysis.AnalysisParams(dem, [(-1000, 0), (1000, 0)], 'EPSG:32633', radius_m=8000,
                                upstream='right')
    m = analysis.run_analysis(p)
    assert m.upstream_side == 'right' and not m.upstream_auto
    assert m.max_level < 102.0                  # downstream side drains at once


# ---------------------------------------------------------------------------
# sample data (regression against an independent scipy flood-fill check)
# ---------------------------------------------------------------------------

def test_sample_dam(sample_dem):
    p = analysis.AnalysisParams(sample_dem, SAMPLE_AXIS, 'EPSG:32637', radius_m=15000)
    m = analysis.run_analysis(p)
    assert m.upstream_side == 'left'
    assert m.limit_reason == hydro.STOP_BYPASS
    assert m.max_level == pytest.approx(945.0, abs=2.0)
    assert m.volume(927.0) / 1e6 == pytest.approx(294.7, rel=0.02)
    assert m.area(927.0) / 1e6 == pytest.approx(7.6, rel=0.03)
    assert any('treated as no-data' in n.text for n in m.notes)   # zero collar
    s = m.stats(m.default_nwl)
    assert s['polygon_wkt'].startswith('MULTIPOLYGON') or s['polygon_wkt'].startswith('POLYGON')
    assert 0 < s['dam_height'] < 200
    assert s['shoreline_m'] > 0 and s['sdi'] > 1
    lv, a, v = m.curve()
    assert np.all(np.diff(v) >= 0) and np.all(np.diff(a) >= 0)
    sz = m.sizing()
    assert len(sz['nwl']) == len(sz['fill'])


def test_geographic_dem_is_reprojected(tmp_path, sample_dem):
    geo = str(tmp_path / 'dem_4326.tif')
    gdal.Warp(geo, sample_dem, dstSRS='EPSG:4326', resampleAlg='bilinear', srcNodata=0,
              dstNodata=-9999)
    p = analysis.AnalysisParams(geo, SAMPLE_AXIS, 'EPSG:32637', radius_m=15000)
    m = analysis.run_analysis(p)
    auth = osr.SpatialReference(wkt=m.grid.srs_wkt).GetAuthorityCode(None)
    assert auth == '32637'                    # local UTM chosen automatically
    assert m.volume(900.0) / 1e6 == pytest.approx(136.0, rel=0.04)


def test_integer_decimetre_dem_is_scaled(tmp_path, sample_dem):
    """GEDTM30-like input: EPSG:4326, Int32 decimetres, no scale metadata."""
    src = gdal.Warp('', sample_dem, format='MEM', dstSRS='EPSG:4326', srcNodata=0,
                    dstNodata=-2147483648, outputType=gdal.GDT_Float64)
    a = src.GetRasterBand(1).ReadAsArray()
    a = np.where(a == -2147483648, a, np.round(a * 10)).astype(np.int32)
    dm = gdal.GetDriverByName('GTiff').Create(str(tmp_path / 'dm.tif'), src.RasterXSize,
                                              src.RasterYSize, 1, gdal.GDT_Int32)
    dm.SetGeoTransform(src.GetGeoTransform())
    dm.SetProjection(src.GetProjection())
    dm.GetRasterBand(1).SetNoDataValue(-2147483648)
    dm.GetRasterBand(1).WriteArray(a)
    dm = None
    work, _c, bounds, _lat = analysis.plan_frame(SAMPLE_AXIS, 'EPSG:32637', 15000)
    out, _notes = dem_sources.download_dem('gedtm30', bounds, work, str(tmp_path / 'o.tif'),
                                           gedtm30_url=str(tmp_path / 'dm.tif'))
    ds = gdal.Open(out)
    z = ds.GetRasterBand(1).ReadAsArray()
    z = z[z != -9999]
    assert 700 < z.min() < 1000 and z.max() < 3000   # metres, not decimetres


# ---------------------------------------------------------------------------
# small pieces
# ---------------------------------------------------------------------------

def test_capacity_table_simple():
    spill = np.array([1.0, 1.0, 2.0, 3.0])
    z = np.array([0.0, 1.0, 2.0, 3.0])
    t = hydro.CapacityTable(spill, z, cell_area=10.0)
    assert t.area(0.5) == 0
    assert t.area(1.5) == 20.0
    assert t.volume(2.0) == pytest.approx(10.0 * ((2 - 0) + (2 - 1) + (2 - 2)))


def test_embankment_rectangular_valley():
    st = np.array([0.0, 10.0, 10.0001, 90.0, 90.0001, 100.0])
    g = np.array([50.0, 50.0, 0.0, 0.0, 50.0, 50.0])
    e = hydro.embankment(st, g, 20.0, crest_width=5.0, slope_us=2.0, slope_ds=2.0)
    assert e['crest_length'] == pytest.approx(80.0, abs=0.1)
    assert e['height'] == pytest.approx(20.0)
    section = 5 * 20 + 0.5 * 4 * 20 ** 2               # b H + (m1 + m2) H^2 / 2
    assert e['fill_volume'] == pytest.approx(section * 80.0, rel=0.01)


def test_brune_trap_efficiency_matches_curve():
    # Brune median curve: ~87 % at C/I = 0.1, ~97 % at C/I = 1
    assert hydro.brune_trap_efficiency(0.1, 1.0) == pytest.approx(85.2, abs=1.0)
    assert hydro.brune_trap_efficiency(1.0, 1.0) == pytest.approx(97.0, abs=0.5)
    assert math.isnan(hydro.brune_trap_efficiency(1.0, 0.0))


def test_levels_and_steps():
    assert hydro.nice_step(120.0) == 1.0
    lv = hydro.level_series(811.0, 945.0, 2.0)
    assert lv[0] == 811.0 and lv[-1] == 945.0 and np.all(np.diff(lv) > 0)
    assert hydro.shoreline_development(2 * math.sqrt(math.pi * 100.0), 100.0) == pytest.approx(1)


def test_find_gedtm30_url_prefers_newest_mean_dtm():
    text = ('{"files":[{"links":{"self":"https://zenodo.org/api/records/1/files/'
            'gedtm_rf_std_30m_s_v20260101.tif/content"}}],"metadata":{"description":'
            '"<a href=\\"https://s3.opengeohub.org/global/edtm/gedtm_rf_m_30m_s_20060101_'
            '20151231_go_epsg.4326.3855_v20260201.tif\\">x</a> https://s3.opengeohub.org/'
            'global/edtm/gedtm_rf_m_30m_s_20060101_20151231_go_epsg.4326.3855_v20250611.tif '
            'https://s3.opengeohub.org/global/edtm/gedtm_mask_c_30m_s_v20260201.tif"}}')
    url = dem_sources.find_gedtm30_url(text)
    assert url.endswith('_v20260201.tif') and 'gedtm_rf_m_' in url
    assert dem_sources.resolve_gedtm30_url(lambda u: text) == (url, 'zenodo')
    assert dem_sources.resolve_gedtm30_url(lambda u: 1 / 0)[1] == 'fallback'


def test_copernicus_tiles():
    urls = dem_sources.copernicus_tile_urls(41.9, 40.7, 42.1, 40.9)
    assert len(urls) == 2
    assert urls[0].endswith('Copernicus_DSM_COG_10_N40_00_E041_00_DEM.tif')
    assert dem_sources.copernicus_tile_urls(-0.5, -0.5, -0.4, -0.4)[0].endswith(
        'Copernicus_DSM_COG_10_S01_00_W001_00_DEM.tif')
