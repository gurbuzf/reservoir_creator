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

import hashlib
import math
import os
import re
import threading
import time
import urllib.request

import numpy as np
from osgeo import gdal

from . import hydro, terrain
from .i18n import Msg, tr

GEDTM30_ZENODO_RECORD = '18887460'
GEDTM30_FALLBACK_URL = ('https://s3.opengeohub.org/global/edtm/'
                        'gedtm_rf_m_30m_s_20060101_20151231_go_epsg.4326.3855_v20250611.tif')
COPERNICUS_BASE = 'https://copernicus-dem-30m.s3.amazonaws.com'


class DemSource:
    def __init__(self, key, name, short, kind, description, citation, license_, links=()):
        self.key = key
        self.links = links          # (label, url) pairs for the References page
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
        'CC-BY 4.0',
        (('doi:10.7717/peerj.19673', 'https://doi.org/10.7717/peerj.19673'),
         ('Zenodo', 'https://zenodo.org/records/' + GEDTM30_ZENODO_RECORD),
         ('CC-BY 4.0', 'https://creativecommons.org/licenses/by/4.0/'))),
    DemSource(
        'cop30', 'Copernicus GLO-30 - global surface model (DSM), 30 m', 'Copernicus GLO-30',
        'DSM',
        'Surface model: includes forest canopy and buildings, which makes valleys '
        'look shallower. Heights: EGM2008.',
        'Copernicus DEM GLO-30, (c) DLR e.V. 2010-2014 and (c) Airbus Defence and Space '
        'GmbH 2014-2018, provided under COPERNICUS by the European Union and ESA.',
        'Copernicus DEM licence',
        (('AWS Open Data', 'https://registry.opendata.aws/copernicus-dem/'),
         ('Copernicus DEM', 'https://spacedata.copernicus.eu/collections/copernicus-digital-elevation-model'))),
]
SOURCES_BY_KEY = {s.key: s for s in SOURCES}

_HTTP_OPTIONS = {
    'GDAL_DISABLE_READDIR_ON_OPEN': 'EMPTY_DIR',
    'CPL_VSIL_CURL_ALLOWED_EXTENSIONS': '.tif,.TIF,.tiff,.vrt',
    'GDAL_HTTP_MAX_RETRY': '4',
    'GDAL_HTTP_RETRY_DELAY': '2',
    # The GEDTM30 server's speed swings from ~2 MB/s to ~25 KB/s, and one
    # 2048x2048 COG tile is 5-7 MB, so a fixed total timeout cuts slow but
    # healthy transfers.  Give up only when the transfer actually stalls.
    'GDAL_HTTP_CONNECTTIMEOUT': '30',
    'GDAL_HTTP_TIMEOUT': '1800',
    'GDAL_HTTP_LOW_SPEED_TIME': '60',
    'GDAL_HTTP_LOW_SPEED_LIMIT': '1024',
    # s3.opengeohub.org (GEDTM30) truncates multi-range / merged-range
    # responses ("got N bytes, expected M"), so fetch one range per request...
    'GDAL_HTTP_MULTIRANGE': 'SINGLE_GET',
    'GDAL_HTTP_MERGE_CONSECUTIVE_RANGES': 'NO',
    # ...but many of them in parallel: one-at-a-time made a 30 km Copernicus
    # window take ~27 s instead of ~2 s.
    'GDAL_NUM_THREADS': 'ALL_CPUS',
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


_DOWNLOAD_ATTEMPTS = 3


def _is_transient(error):
    """True for network read errors worth retrying (truncated / timed-out blocks)."""
    if not error:
        return False
    low = error.lower()
    return any(t in low for t in ('read error', 'readblock failed', 'timed out', 'timeout',
                                  'curl error', 'http error', 'connection'))


def _run_cancellable(func, check_cancel, on_tick, tick=0.25):
    """Run ``func`` in a worker thread, returning (result, error_message).

    GDAL only calls the progress callback between blocks, and a single block
    can take minutes on a slow server, so cancellation is polled here instead:
    ``check_cancel`` raises straight away and the worker is abandoned (it
    aborts at its next progress callback and only ever writes to memory).
    """
    box = {}

    def work():
        try:
            box['result'] = func()
            if box['result'] is None:   # GDAL's last error is per thread
                box['error'] = gdal.GetLastErrorMsg()
        except Exception as e:          # gdal.UseExceptions() is active
            box['error'] = str(e)

    worker = threading.Thread(target=work, name='ReservoirCreator-download', daemon=True)
    start = time.monotonic()
    worker.start()
    while worker.is_alive():
        worker.join(tick)
        check_cancel()
        on_tick(time.monotonic() - start)
    return box.get('result'), box.get('error')


def _gdal_path(url):
    return '/vsicurl/' + url if url.startswith(('http://', 'https://')) else url


def _open_source(source_key, lon0, lat0, lon1, lat1, fetch_text, gedtm30_url, notes,
                 check_cancel):
    """GDAL source for the lon/lat box: (path or dataset, scale, offset, nodata).

    Returns None when the source has no data there (Copernicus over the sea).
    """
    if source_key == 'gedtm30':
        url = gedtm30_url or gedtm30_location(fetch_text, notes)
        src = _gdal_path(url)
        try:
            ds = gdal.Open(src)
        except RuntimeError:        # gdal.UseExceptions() is active
            ds = None
        if ds is None:
            raise terrain.TerrainError(
                tr('Could not open GEDTM30 at {}. Check your internet connection / proxy.')
                .format(url))
        band = ds.GetRasterBand(1)
        is_int = band.DataType in (gdal.GDT_Int16, gdal.GDT_Int32, gdal.GDT_UInt16,
                                   gdal.GDT_UInt32)
        # Integer releases (<= v20250611) store decimetres; the Float32
        # release (v1.2) stores metres but still carries a stale 0.1
        # scale tag, so the data type decides, not the tag.
        scale = 0.1 if is_int else 1.0
        return src, scale, band.GetOffset() or 0.0, band.GetNoDataValue()
    if source_key == 'cop30':
        tiles = []
        for u in copernicus_tile_urls(lon0, lat0, lon1, lat1):
            check_cancel()
            try:
                if gdal.VSIStatL('/vsicurl/' + u) is not None:
                    tiles.append('/vsicurl/' + u)
            except RuntimeError:
                pass
        if not tiles:
            return None
        src = gdal.BuildVRT('', tiles, options=gdal.BuildVRTOptions(resolution='highest'))
        if src is None:
            raise terrain.TerrainError(tr('Could not assemble Copernicus tiles.'))
        return src, 1.0, 0.0, src.GetRasterBand(1).GetNoDataValue()
    raise ValueError('Unknown DEM source ' + source_key)


_gedtm30_url_cache = {}


def gedtm30_location(fetch_text=None, notes=None):
    """GEDTM30 COG URL, looked up on Zenodo once per session."""
    if 'url' not in _gedtm30_url_cache:
        url, origin = resolve_gedtm30_url(fetch_text)
        _gedtm30_url_cache['url'] = url
        _gedtm30_url_cache['note'] = origin == 'fallback'
    if notes is not None and _gedtm30_url_cache['note']:
        notes.append(Msg('Zenodo could not be reached; using the known GEDTM30 location.'))
    return _gedtm30_url_cache['url']


def _cancel_check(feedback):
    def check_cancel():
        if feedback is not None and feedback.is_cancelled():
            raise hydro.Cancelled()
    return check_cancel


def _read_with_retries(read, check_cancel, show):
    """Run ``read()`` cancellably, retrying transient network errors."""
    result, error = None, None
    for attempt in range(_DOWNLOAD_ATTEMPTS):
        result, error = _run_cancellable(read, check_cancel,
                                         lambda s, attempt=attempt: show(attempt, s))
        check_cancel()
        if result is not None or not _is_transient(error):
            break
        # a block arrived cut short (slow / flaky server): the blocks that
        # did arrive are in GDAL's /vsicurl/ cache, so a retry resumes
    return result, error


def _download_failed(error, name):
    return terrain.TerrainError(
        tr('Download failed: {}\nThe {} server may be slow or unreachable right now; '
           'try again later or choose another DEM source.').format(
               error or gdal.GetLastErrorMsg(), name))


def download_dem(source_key, bounds, work_srs, out_path, fetch_text=None,
                 feedback=None, extra_gdal_config=None, gedtm30_url=None):
    """Download the DEM window ``bounds`` (in ``work_srs``) to a GeoTIFF.

    The result is a Float32 GeoTIFF in metres, in ``work_srs``, at the
    source's native ~30 m resolution.  ``gedtm30_url`` overrides the Zenodo
    look-up (a URL or a local/self-hosted copy).  Returns (out_path, notes).
    The plugin itself uses :func:`fetch_tiles`, which caches and reuses tiles.
    """
    notes = []
    check_cancel = _cancel_check(feedback)
    name = SOURCES_BY_KEY[source_key].short
    if feedback:
        feedback.set_status(tr('Locating {}…').format(name))
    lon0, lat0, lon1, lat1 = _lonlat_bounds(bounds, work_srs)
    options = dict(_HTTP_OPTIONS)
    options.update(extra_gdal_config or {})
    with _GdalConfig(options):
        opened = _open_source(source_key, lon0, lat0, lon1, lat1, fetch_text, gedtm30_url,
                              notes, check_cancel)
        if opened is None:
            raise terrain.TerrainError(tr('No Copernicus GLO-30 tiles cover this area '
                                          '(open sea?) or the server is unreachable.'))
        src, scale, offset, nodata = opened
        check_cancel()
        if feedback:
            feedback.set_status(tr('Downloading {} (only the area around the line)… '
                                   'press Cancel to stop').format(name))
        done = [0.0]

        def progress(complete, _message, _data):
            # Called by GDAL, in a worker thread, while it reads; returning 0
            # aborts.  It must never raise: an exception here reaches QGIS's
            # error hook in that thread, which opens a dialog off the GUI thread
            # and crashes QGIS.  Any failure (e.g. the task is gone) = stop.
            try:
                done[0] = complete
                return 0 if feedback is not None and feedback.is_cancelled() else 1
            except Exception:
                return 0

        res = 30.0   # both products are 1 arc-second (~30 m)
        warp_opts = gdal.WarpOptions(
            format='MEM', dstSRS=work_srs.ExportToWkt(), outputBounds=bounds,
            xRes=res, yRes=res, resampleAlg='bilinear', outputType=gdal.GDT_Float64,
            srcNodata=nodata, dstNodata=-1.0e30, multithread=True, callback=progress)

        def show(attempt, elapsed):
            if feedback is None:
                return
            feedback.set_progress(5 + 60 * done[0])
            feedback.set_status(tr('Downloading {}… {:.0f}% · {:.0f} s{} (press Cancel to '
                                   'stop)').format(name, 100 * done[0], elapsed,
                                                   tr(', retry {}').format(attempt)
                                                   if attempt else ''))

        mem, error = _read_with_retries(lambda: gdal.Warp('', src, options=warp_opts),
                                        check_cancel, show)
        if mem is None:
            raise _download_failed(error, name)
        arr = mem.GetRasterBand(1).ReadAsArray()
        missing = arr <= -1.0e29
        arr = arr * (scale if scale is not None else 1.0) + offset
        arr[missing] = np.nan
        arr[(arr < terrain.VALID_Z_RANGE[0]) | (arr > terrain.VALID_Z_RANGE[1])] = np.nan
        if np.isnan(arr).all():
            raise terrain.TerrainError(tr('The downloaded DEM contains no data for this area.'))
        grid = terrain.Grid(arr, mem.GetGeoTransform(), work_srs.ExportToWkt())
        terrain.write_geotiff(out_path, grid, arr)
    return out_path, notes


# ---------------------------------------------------------------------------
# Tile cache
# ---------------------------------------------------------------------------
#
# Downloads are split into fixed 0.25 deg tiles (~22-28 km) kept in native
# lon/lat and full resolution.  When the analysis window grows, or another
# line is drawn nearby, only the tiles not yet on disk are fetched.  Tiles
# overlap by a few pixels so the mosaic never has a seam of no-data.

TILE_DEG = 0.25
TILE_NODATA = -9999.0
_TILE_PAD_DEG = 3.0 / 3600.0


def tiles_for(lon0, lat0, lon1, lat1):
    """(ix, iy) indices of the tiles covering the lon/lat box."""
    return [(ix, iy)
            for iy in range(int(math.floor(lat0 / TILE_DEG)), int(math.floor(lat1 / TILE_DEG)) + 1)
            for ix in range(int(math.floor(lon0 / TILE_DEG)), int(math.floor(lon1 / TILE_DEG)) + 1)]


def _tile_name(ix, iy):
    lon, lat = ix * TILE_DEG, iy * TILE_DEG
    return '{}{:07.3f}_{}{:06.3f}.tif'.format('E' if lon >= 0 else 'W', abs(lon),
                                              'N' if lat >= 0 else 'S', abs(lat))


def tile_folder(cache_dir, source_key, fetch_text=None, gedtm30_url=None):
    """Per-source (and, for GEDTM30, per-release) tile folder."""
    key = source_key
    if source_key == 'gedtm30':
        url = gedtm30_url or gedtm30_location(fetch_text)
        key += '_' + hashlib.sha1(url.encode('utf-8')).hexdigest()[:8]
    folder = os.path.join(cache_dir, 'tiles', key)
    os.makedirs(folder, exist_ok=True)
    return folder


def download_tile(source_key, ix, iy, out_path, fetch_text=None, feedback=None,
                  extra_gdal_config=None, gedtm30_url=None, show=None):
    """Download one tile to ``out_path`` (Float32 metres, lon/lat, native resolution).

    Returns the notes.  ``show(attempt, elapsed_s)`` is called while waiting.
    """
    notes = []
    check_cancel = _cancel_check(feedback)
    p = _TILE_PAD_DEG
    lon0, lat0 = ix * TILE_DEG - p, iy * TILE_DEG - p
    lon1, lat1 = (ix + 1) * TILE_DEG + p, (iy + 1) * TILE_DEG + p
    options = dict(_HTTP_OPTIONS)
    options.update(extra_gdal_config or {})
    tmp = out_path + '.part.tif'
    try:
        with _GdalConfig(options):
            opened = _open_source(source_key, lon0, lat0, lon1, lat1, fetch_text,
                                  gedtm30_url, notes, check_cancel)
            if opened is None:                      # no land here: an empty tile
                n = int(round((lat1 - lat0) * 3600))
                arr = np.full((n, n), TILE_NODATA, dtype=np.float32)
                gt = (lon0, (lon1 - lon0) / n, 0.0, lat1, 0.0, -(lat1 - lat0) / n)
            else:
                src, scale, offset, nodata = opened
                opts = gdal.TranslateOptions(format='MEM', projWin=[lon0, lat1, lon1, lat0],
                                             outputType=gdal.GDT_Float64)
                mem, error = _read_with_retries(lambda: gdal.Translate('', src, options=opts),
                                                check_cancel, show or (lambda a, s: None))
                if mem is None:
                    raise _download_failed(error, SOURCES_BY_KEY[source_key].short)
                arr = mem.GetRasterBand(1).ReadAsArray()
                bad = ~np.isfinite(arr)
                if nodata is not None:
                    bad |= arr == nodata
                arr = arr * (scale if scale is not None else 1.0) + offset
                bad |= (arr < terrain.VALID_Z_RANGE[0]) | (arr > terrain.VALID_Z_RANGE[1])
                arr = np.where(bad, TILE_NODATA, arr).astype(np.float32)
                gt = mem.GetGeoTransform()
            ds = gdal.GetDriverByName('GTiff').Create(
                tmp, arr.shape[1], arr.shape[0], 1, gdal.GDT_Float32,
                ['COMPRESS=DEFLATE', 'PREDICTOR=3', 'TILED=YES'])
            ds.SetGeoTransform(gt)
            ds.SetProjection(terrain.geographic_srs().ExportToWkt())
            band = ds.GetRasterBand(1)
            band.SetNoDataValue(TILE_NODATA)
            band.WriteArray(arr)
            ds = None
        os.replace(tmp, out_path)
    finally:
        if os.path.exists(tmp):             # cancelled or failed: no partial file
            os.remove(tmp)
    return notes


def fetch_tiles(source_key, bounds, work_srs, cache_dir, fetch_text=None, feedback=None,
                extra_gdal_config=None, gedtm30_url=None):
    """Make sure every tile covering ``bounds`` (in ``work_srs``) is on disk.

    Returns (vrt_path, notes, n_tiles, n_downloaded): a VRT mosaic of the
    tiles, in lon/lat at native resolution.
    """
    notes = []
    name = SOURCES_BY_KEY[source_key].short
    if feedback:
        feedback.set_status(tr('Locating {}…').format(name))
    if source_key == 'gedtm30' and not gedtm30_url:
        gedtm30_url = gedtm30_location(fetch_text, notes)
    folder = tile_folder(cache_dir, source_key, fetch_text, gedtm30_url)
    wanted = tiles_for(*_lonlat_bounds(bounds, work_srs))
    paths = [os.path.join(folder, _tile_name(ix, iy)) for ix, iy in wanted]
    missing = [(t, p) for t, p in zip(wanted, paths) if not os.path.exists(p)]
    for k, ((ix, iy), path) in enumerate(missing):
        def show(attempt, elapsed, k=k):
            if feedback is None:
                return
            feedback.set_progress(5 + 60.0 * k / len(missing))
            feedback.set_status(tr('Downloading {}: tile {} of {} · {:.0f} s{} (press Cancel '
                                   'to stop)').format(name, k + 1, len(missing), elapsed,
                                                      tr(', retry {}').format(attempt)
                                                      if attempt else ''))
        show(0, 0.0)
        for n in download_tile(source_key, ix, iy, path, fetch_text, feedback,
                               extra_gdal_config, gedtm30_url, show):
            if n not in notes:
                notes.append(n)
    key = hashlib.sha1('|'.join(sorted(paths)).encode('utf-8')).hexdigest()[:12]
    vrt = os.path.join(folder, 'mosaic_{}.vrt'.format(key))
    if not os.path.exists(vrt):
        ds = gdal.BuildVRT(vrt, paths, options=gdal.BuildVRTOptions(
            resolution='highest', srcNodata=TILE_NODATA, VRTNodata=TILE_NODATA))
        if ds is None:
            raise terrain.TerrainError(tr('Could not assemble the DEM tiles: {}')
                                       .format(gdal.GetLastErrorMsg()))
        ds = None
    return vrt, notes, len(paths), len(missing)
