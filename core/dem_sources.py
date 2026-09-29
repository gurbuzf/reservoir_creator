# -*- coding: utf-8 -*-
"""
Online DEM sources.

Only the window around the dam is fetched: the sources are Cloud Optimised
GeoTIFFs read through GDAL's ``/vsicurl/`` driver, so a reservoir study
downloads a few megabytes rather than the global dataset.

GEDTM30
    Global Ensemble Digital Terrain Model, 30 m (OpenGeoHub, CC-BY 4.0).
    A *bare-earth* DTM fused from Copernicus DEM, ALOS AW3D30 and
    ICESat-2 / GEDI, i.e. with vegetation and buildings removed - the right
    choice for reservoir volumes.  The COG location is looked up from the
    Zenodo record at run time, with a known URL as fallback.
    Ho, Y.-F. et al. (2025) PeerJ 13:e19673, doi:10.7717/peerj.19673

Copernicus GLO-30
    Copernicus DEM 30 m (ESA / Airbus), served on AWS Open Data.  This is a
    *surface* model (DSM): forest canopy and buildings are included, which
    biases volumes low in vegetated valleys.
"""

import math
import re
import urllib.request

import numpy as np
from osgeo import gdal

from . import hydro, terrain

GEDTM30_ZENODO_RECORD = '18887460'
GEDTM30_FALLBACK_URL = ('https://s3.opengeohub.org/global/edtm/'
                        'gedtm_rf_m_30m_s_20060101_20151231_go_epsg.4326.3855_v20250611.tif')
COPERNICUS_BASE = 'https://copernicus-dem-30m.s3.amazonaws.com'


class DemSource:
    def __init__(self, key, name, short, kind, description, citation, license_):
        self.key = key
        self.name = name
        self.short = short
        self.kind = kind
        self.description = description
        self.citation = citation
        self.license = license_


SOURCES = [
    DemSource(
        'gedtm30', 'GEDTM30 - global bare-earth DTM, 30 m', 'GEDTM30', 'DTM',
        'Bare-earth terrain (vegetation and buildings removed). Recommended for '
        'reservoir studies. Heights: EGM2008.',
        'Ho, Y.-F., Grohmann, C.H., Lindsay, J., Reuter, H.I., Parente, L., Witjes, M., '
        'Hengl, T. (2025). GEDTM30: global ensemble digital terrain model at 30 m. '
        'PeerJ 13:e19673. https://zenodo.org/records/' + GEDTM30_ZENODO_RECORD,
        'CC-BY 4.0'),
    DemSource(
        'cop30', 'Copernicus GLO-30 - global surface model (DSM), 30 m', 'Copernicus GLO-30',
        'DSM',
        'Surface model: includes forest canopy and buildings, which makes valleys '
        'look shallower. Heights: EGM2008.',
        'Copernicus DEM GLO-30, (c) DLR e.V. 2010-2014 and (c) Airbus Defence and Space '
        'GmbH 2014-2018, provided under COPERNICUS by the European Union and ESA.',
        'Copernicus DEM licence'),
]
SOURCES_BY_KEY = {s.key: s for s in SOURCES}

_HTTP_OPTIONS = {
    'GDAL_DISABLE_READDIR_ON_OPEN': 'EMPTY_DIR',
    'CPL_VSIL_CURL_ALLOWED_EXTENSIONS': '.tif,.TIF,.tiff,.vrt',
    'GDAL_HTTP_MAX_RETRY': '4',
    'GDAL_HTTP_RETRY_DELAY': '2',
    'GDAL_HTTP_TIMEOUT': '60',
    'GDAL_HTTP_MULTIRANGE': 'YES',
    'GDAL_HTTP_MERGE_CONSECUTIVE_RANGES': 'YES',
    'VSI_CACHE': 'TRUE',
}


class _GdalConfig:
    """Temporarily set GDAL configuration options."""

    def __init__(self, options):
        self.options = options
        self.saved = {}

    def __enter__(self):
        for k, v in self.options.items():
            self.saved[k] = gdal.GetConfigOption(k)
            gdal.SetConfigOption(k, v)
        return self

    def __exit__(self, *exc):
        for k, v in self.saved.items():
            gdal.SetConfigOption(k, v)
        return False


def default_fetch_text(url, timeout=20):
    req = urllib.request.Request(url, headers={'Accept': 'application/json',
                                               'User-Agent': 'QGIS-ReservoirCreator'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode('utf-8', 'replace')


# ---------------------------------------------------------------------------
# GEDTM30
# ---------------------------------------------------------------------------

_TIF_URL = re.compile(r'https?://[^\s"\'<>\\]+?\.tif(?:/content)?(?=[\s"\'<>\\?]|$)')


def find_gedtm30_url(text):
    """Pick the GEDTM30 mean-elevation COG URL out of a Zenodo record."""
    candidates = []
    for url in set(_TIF_URL.findall(text)):
        name = url.rsplit('/', 2)[-2] if url.endswith('/content') else url.rsplit('/', 1)[-1]
        low = name.lower()
        if 'dtm' not in low:
            continue
        if any(t in low for t in ('std', 'mask', 'sd_', '_sd', 'hillshade', 'slope')):
            continue
        if not re.search(r'(_m_|rf_m|_mean)', low):
            continue
        version = re.findall(r'v(\d{8})', low)
        candidates.append((version[-1] if version else '', 's3' in url, url))
    if not candidates:
        return None
    candidates.sort()
    return candidates[-1][2]


def resolve_gedtm30_url(fetch_text=None):
    """Return (url, origin) of the most recent GEDTM30 COG."""
    fetch_text = fetch_text or default_fetch_text
    api = 'https://zenodo.org/api/records/' + GEDTM30_ZENODO_RECORD
    for url in (api + '/versions/latest', api):
        try:
            text = fetch_text(url)
        except Exception:
            continue
        if not text:
            continue
        found = find_gedtm30_url(text)
        if found:
            return found, 'zenodo'
    return GEDTM30_FALLBACK_URL, 'fallback'


# ---------------------------------------------------------------------------
# Copernicus GLO-30
# ---------------------------------------------------------------------------

def copernicus_tile_urls(lon_min, lat_min, lon_max, lat_max):
    urls = []
    for lat in range(int(math.floor(lat_min)), int(math.floor(lat_max)) + 1):
        for lon in range(int(math.floor(lon_min)), int(math.floor(lon_max)) + 1):
            ns = 'N' if lat >= 0 else 'S'
            ew = 'E' if lon >= 0 else 'W'
            name = 'Copernicus_DSM_COG_10_{}{:02d}_00_{}{:03d}_00_DEM'.format(
                ns, abs(lat), ew, abs(lon))
            urls.append('{}/{}/{}.tif'.format(COPERNICUS_BASE, name, name))
    return urls


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def _lonlat_bounds(bounds, work_srs):
    minx, miny, maxx, maxy = bounds
    pts = [(minx, miny), (minx, maxy), (maxx, miny), (maxx, maxy),
           ((minx + maxx) / 2, miny), ((minx + maxx) / 2, maxy),
           (minx, (miny + maxy) / 2), (maxx, (miny + maxy) / 2)]
    ll = terrain.transform_points(pts, work_srs, terrain.geographic_srs())
    lons = [p[0] for p in ll]
    lats = [p[1] for p in ll]
    pad = 0.002
    return min(lons) - pad, min(lats) - pad, max(lons) + pad, max(lats) + pad


def _gdal_path(url):
    return '/vsicurl/' + url if url.startswith(('http://', 'https://')) else url


def download_dem(source_key, bounds, work_srs, out_path, fetch_text=None,
                 feedback=None, extra_gdal_config=None, gedtm30_url=None):
    """Download the DEM window ``bounds`` (in ``work_srs``) to a GeoTIFF.

    The result is a Float32 GeoTIFF in metres, in ``work_srs``, at the
    source's native ~30 m resolution.  ``gedtm30_url`` overrides the Zenodo
    look-up (a URL or a local/self-hosted copy).  Returns (out_path, notes).
    """
    notes = []

    def check_cancel():
        if feedback is not None and feedback.is_cancelled():
            raise hydro.Cancelled()

    if feedback:
        feedback.set_status('Locating {}…'.format(SOURCES_BY_KEY[source_key].short))
    lon0, lat0, lon1, lat1 = _lonlat_bounds(bounds, work_srs)
    options = dict(_HTTP_OPTIONS)
    options.update(extra_gdal_config or {})
    with _GdalConfig(options):
        if source_key == 'gedtm30':
            if gedtm30_url:
                url = gedtm30_url
            else:
                url, origin = resolve_gedtm30_url(fetch_text)
                if origin == 'fallback':
                    notes.append('Zenodo could not be reached; using the known GEDTM30 location.')
            src = _gdal_path(url)
            try:
                ds = gdal.Open(src)
            except RuntimeError:        # gdal.UseExceptions() is active
                ds = None
            if ds is None:
                raise terrain.TerrainError(
                    'Could not open GEDTM30 at {}. Check your internet connection / proxy.'
                    .format(url))
            band = ds.GetRasterBand(1)
            is_int = band.DataType in (gdal.GDT_Int16, gdal.GDT_Int32, gdal.GDT_UInt16,
                                       gdal.GDT_UInt32)
            scale = band.GetScale()
            if scale in (None, 1.0) and is_int:
                scale = 0.1      # GEDTM30 stores elevation in decimetres
            offset = band.GetOffset() or 0.0
            nodata = band.GetNoDataValue()
            ds = None
        elif source_key == 'cop30':
            urls = copernicus_tile_urls(lon0, lat0, lon1, lat1)
            tiles = []
            for u in urls:
                check_cancel()
                try:
                    if gdal.VSIStatL('/vsicurl/' + u) is not None:
                        tiles.append('/vsicurl/' + u)
                except RuntimeError:
                    pass
            if not tiles:
                raise terrain.TerrainError('No Copernicus GLO-30 tiles cover this area '
                                           '(open sea?) or the server is unreachable.')
            src = gdal.BuildVRT('', tiles, options=gdal.BuildVRTOptions(resolution='highest'))
            if src is None:
                raise terrain.TerrainError('Could not assemble Copernicus tiles.')
            scale, offset, nodata = 1.0, 0.0, src.GetRasterBand(1).GetNoDataValue()
        else:
            raise ValueError('Unknown DEM source ' + source_key)

        check_cancel()
        name = SOURCES_BY_KEY[source_key].short
        if feedback:
            feedback.set_status('Downloading {} (only the area around the line)… '
                                'press Cancel to stop'.format(name))

        def progress(complete, _message, _data):
            # called by GDAL while it reads; returning 0 aborts the download
            if feedback is None:
                return 1
            if feedback.is_cancelled():
                return 0
            feedback.set_progress(5 + 60 * complete)
            feedback.set_status('Downloading {}… {:.0f}% (press Cancel to stop)'
                                .format(name, 100 * complete))
            return 1

        res = 30.0   # both products are 1 arc-second (~30 m)
        warp_opts = gdal.WarpOptions(
            format='MEM', dstSRS=work_srs.ExportToWkt(), outputBounds=bounds,
            xRes=res, yRes=res, resampleAlg='bilinear', outputType=gdal.GDT_Float64,
            srcNodata=nodata, dstNodata=-1.0e30, multithread=True, callback=progress)
        try:
            mem = gdal.Warp('', src, options=warp_opts)
        except RuntimeError as e:
            check_cancel()
            raise terrain.TerrainError('Download failed: {}'.format(e))
        check_cancel()
        if mem is None:
            raise terrain.TerrainError('Download failed: {}'.format(gdal.GetLastErrorMsg()))
        arr = mem.GetRasterBand(1).ReadAsArray()
        missing = arr <= -1.0e29
        arr = arr * (scale if scale is not None else 1.0) + offset
        arr[missing] = np.nan
        arr[(arr < terrain.VALID_Z_RANGE[0]) | (arr > terrain.VALID_Z_RANGE[1])] = np.nan
        if np.isnan(arr).all():
            raise terrain.TerrainError('The downloaded DEM contains no data for this area.')
        grid = terrain.Grid(arr, mem.GetGeoTransform(), work_srs.ExportToWkt())
        terrain.write_geotiff(out_path, grid, arr)
    return out_path, notes

