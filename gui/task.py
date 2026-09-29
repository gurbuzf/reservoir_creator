# -*- coding: utf-8 -*-
"""Background task: optional DEM download + reservoir analysis."""

import hashlib
import os
import traceback

from qgis.core import (QgsApplication, QgsBlockingNetworkRequest, QgsMessageLog, Qgis,
                       QgsSettings, QgsTask)
from qgis.PyQt.QtCore import QUrl, pyqtSignal
from qgis.PyQt.QtNetwork import QNetworkRequest

from ..core import analysis, dem_sources, hydro
from ..core.terrain import TerrainError

LOG_TAG = 'Reservoir Creator'


def qgis_fetch_text(url):
    """HTTP GET through QGIS' network stack (honours proxy / auth settings)."""
    req = QgsBlockingNetworkRequest()
    err = req.get(QNetworkRequest(QUrl(url)), forceRefresh=True)
    if err != QgsBlockingNetworkRequest.ErrorCode.NoError:
        raise IOError(req.errorMessage())
    return bytes(req.reply().content()).decode('utf-8', 'replace')


def gdal_proxy_config():
    """GDAL HTTP options mirroring the QGIS proxy settings."""
    s = QgsSettings()
    if not s.value('proxy/proxyEnabled', False, type=bool):
        return {}
    host = s.value('proxy/proxyHost', '', type=str)
    port = s.value('proxy/proxyPort', '', type=str)
    if not host:
        return {}
    cfg = {'GDAL_HTTP_PROXY': '{}:{}'.format(host, port) if port else host}
    user = s.value('proxy/proxyUser', '', type=str)
    if user:
        cfg['GDAL_HTTP_PROXYUSERPWD'] = '{}:{}'.format(user, s.value('proxy/proxyPassword', '',
                                                                      type=str))
    return cfg


def dem_cache_dir():
    path = os.path.join(QgsApplication.qgisSettingsDirPath(), 'reservoir_creator', 'dem_cache')
    os.makedirs(path, exist_ok=True)
    return path


class _Feedback(analysis.Feedback):
    def __init__(self, task):
        self.task = task

    def set_progress(self, percent):
        self.task.setProgress(float(percent))

    def set_status(self, text):
        self.task.message.emit(text)

    def is_cancelled(self):
        return self.task.isCanceled()


class ReservoirTask(QgsTask):
    """Runs in a worker thread; results are read in ``taskCompleted``."""

    message = pyqtSignal(str)

    def __init__(self, params, download_source=None, gedtm30_url=None):
        super().__init__('Reservoir Creator analysis', QgsTask.Flag.CanCancel)
        self.params = params
        self.download_source = download_source
        self.gedtm30_url = gedtm30_url or None
        self.gdal_config = gdal_proxy_config()
        self.cache_dir = dem_cache_dir() if download_source else None
        self.model = None
        self.error = None
        self.downloaded_path = None
        self.download_notes = []

    def run(self):
        fb = _Feedback(self)
        try:
            if self.download_source:
                self._download(fb)
            self.model = analysis.run_analysis(self.params, fb)
            return True
        except hydro.Cancelled:
            self.error = 'Cancelled.'
        except TerrainError as e:
            self.error = str(e)
        except Exception as e:  # pragma: no cover - reported to the user
            self.error = '{}: {}'.format(type(e).__name__, e)
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)
        return False

    def _download(self, fb):
        p = self.params
        work, _coords, bounds, _lat = analysis.plan_frame(p.dam_coords, p.dam_crs, p.radius_m)
        key = '{}|{}|{}'.format(self.download_source, work.ExportToWkt(),
                                ','.join('{:.0f}'.format(b) for b in bounds))
        digest = hashlib.sha1(key.encode('utf-8')).hexdigest()[:12]
        out = os.path.join(self.cache_dir, '{}_{}.tif'.format(self.download_source, digest))
        if os.path.exists(out):
            fb.set_status('Using cached {} download…'.format(
                dem_sources.SOURCES_BY_KEY[self.download_source].short))
        else:
            fb.set_progress(1)
            tmp = out + '.part.tif'
            _path, notes = dem_sources.download_dem(
                self.download_source, bounds, work, tmp, fetch_text=qgis_fetch_text,
                feedback=fb, extra_gdal_config=self.gdal_config, gedtm30_url=self.gedtm30_url)
            os.replace(tmp, out)
            self.download_notes = notes
        self.downloaded_path = out
        p.dem_path = out
