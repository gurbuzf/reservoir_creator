# -*- coding: utf-8 -*-
"""Background task: optional DEM download + reservoir computation."""

import hashlib
import os
import traceback

from qgis.core import (Qgis, QgsApplication, QgsBlockingNetworkRequest, QgsMessageLog,
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
        cfg['GDAL_HTTP_PROXYUSERPWD'] = '{}:{}'.format(
            user, s.value('proxy/proxyPassword', '', type=str))
    return cfg


def dem_cache_dir():
    path = os.path.join(QgsApplication.qgisSettingsDirPath(), 'reservoir_creator', 'dem_cache')
    os.makedirs(path, exist_ok=True)
    return path


class _Feedback(analysis.Feedback):
    """Called from worker threads, so it never raises: an exception there would
    reach QGIS's error hook, which opens a dialog off the GUI thread and crashes
    QGIS.  If the task object is already gone the run is treated as cancelled."""

    def __init__(self, task):
        self.task = task

    def set_progress(self, percent):
        try:
            self.task.setProgress(float(percent))
        except RuntimeError:        # the task's C++ object was deleted
            pass

    def set_status(self, text):
        try:
            self.task.message.emit(str(text))
        except RuntimeError:
            pass

    def is_cancelled(self):
        try:
            return self.task.isCanceled()
        except RuntimeError:
            return True

    def log(self, text):
        # View > Panels > Log Messages > "Reservoir Creator" tab
        try:
            QgsMessageLog.logMessage(str(text), LOG_TAG, Qgis.MessageLevel.Info,
                                     notifyUser=False)
        except RuntimeError:
            pass


class ReservoirTask(QgsTask):
    """Runs in a worker thread; the dock reads ``result`` / ``error`` afterwards."""

    message = pyqtSignal(str)

    def __init__(self, params, download_source=None):
        super().__init__('Reservoir Creator', QgsTask.Flag.CanCancel)
        self.params = params
        self.download_source = download_source
        self.gdal_config = gdal_proxy_config()
        self.cache_dir = dem_cache_dir() if download_source else None
        self.result = None
        self.error = None
        self.downloaded_path = None
        self.download_notes = []
        self.run_id = 0          # set by the panel; results of an outdated run are dropped

    def run(self):
        fb = _Feedback(self)
        try:
            get_dem = (lambda b, w, r: self._download(b, w, fb)) if self.download_source else None
            self.result = analysis.run(self.params, fb, get_dem=get_dem)
            return True
        except hydro.Cancelled:
            self.error = 'Cancelled.'
        except TerrainError as e:
            self.error = str(e)
        except Exception as e:  # pragma: no cover - reported to the user
            self.error = '{}: {}'.format(type(e).__name__, e)
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)
        return False

    def _download(self, bounds, work, fb):
        """DEM mosaic for the window: cached tiles, downloading only the missing ones."""
        vrt, notes, n_tiles, n_new = dem_sources.fetch_tiles(
            self.download_source, bounds, work, self.cache_dir, fetch_text=qgis_fetch_text,
            feedback=fb, extra_gdal_config=self.gdal_config)
        fb.log('    {} window {:.0f} x {:.0f} km: {} tiles, {} downloaded, {} from cache'.format(
            self.download_source, (bounds[2] - bounds[0]) / 1000.0,
            (bounds[3] - bounds[1]) / 1000.0, n_tiles, n_new, n_tiles - n_new))
        for n in notes:
            if n not in self.download_notes:
                self.download_notes.append(n)
        self.downloaded_path = vrt
        return vrt
