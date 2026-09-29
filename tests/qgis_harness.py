# -*- coding: utf-8 -*-
"""Headless smoke test of the plugin inside a real QGIS (offscreen).

    QT_QPA_PLATFORM=offscreen python3 tests/qgis_harness.py [outdir] [--dark] [--download]

Loads the plugin with a minimal iface, draws the line with simulated mouse
clicks (the panel then runs by itself), checks the result, the charts and the
exports, and saves screenshots.  ``--download`` also tests a Copernicus
download and cancelling a download from the panel (needs internet).
"""
import gc
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
sys.path.insert(0, os.path.dirname(PLUGIN))
PKG = os.path.basename(PLUGIN)

from osgeo import gdal  # noqa: E402
from qgis.core import (QgsApplication, QgsCoordinateReferenceSystem, QgsPointXY,  # noqa: E402
                       QgsProject, QgsRasterLayer, QgsRectangle)
from qgis.gui import QgsMapCanvas, QgsMapMouseEvent, QgsMessageBar  # noqa: E402
from qgis.PyQt import sip  # noqa: E402
from qgis.PyQt.QtCore import QEvent, QEventLoop, QPoint, Qt  # noqa: E402
from qgis.PyQt.QtGui import QColor, QPalette  # noqa: E402
from qgis.PyQt.QtWidgets import QMainWindow, QToolBar  # noqa: E402

gdal.UseExceptions()
ARGS = [a for a in sys.argv[1:] if not a.startswith('--')]
OUT = ARGS[0] if ARGS else tempfile.mkdtemp()
DARK = '--dark' in sys.argv
os.makedirs(OUT, exist_ok=True)

app = QgsApplication([], True)
app.initQgis()
if DARK:
    pal = QPalette()
    for role, col in ((QPalette.ColorRole.Window, '#2b2b2b'), (QPalette.ColorRole.Base, '#202020'),
                      (QPalette.ColorRole.Text, '#eeeeee'), (QPalette.ColorRole.WindowText, '#eeeeee'),
                      (QPalette.ColorRole.Button, '#353535'), (QPalette.ColorRole.ButtonText, '#eeeeee'),
                      (QPalette.ColorRole.AlternateBase, '#262626'), (QPalette.ColorRole.Mid, '#555555')):
        pal.setColor(role, QColor(col))
    app.setPalette(pal)


class Iface:
    def __init__(self):
        self.win = QMainWindow()
        self.canvas = QgsMapCanvas(self.win)
        self.win.setCentralWidget(self.canvas)
        self.bar = QgsMessageBar()
        self.tb = QToolBar()

    def mapCanvas(self):
        return self.canvas

    def messageBar(self):
        return self.bar

    def mainWindow(self):
        return self.win

    def addDockWidget(self, area, dock):
        self.win.addDockWidget(area, dock)

    def removeDockWidget(self, dock):
        self.win.removeDockWidget(dock)

    def addToolBarIcon(self, a):
        self.tb.addAction(a)

    def removeToolBarIcon(self, a):
        self.tb.removeAction(a)

    def addPluginToMenu(self, m, a):
        pass

    def removePluginMenu(self, m, a):
        pass


iface = Iface()
iface.win.resize(1400, 1000)
crs = QgsCoordinateReferenceSystem('EPSG:32637')
QgsProject.instance().setCrs(crs)
dem = QgsRasterLayer(os.path.join(PLUGIN, 'data', 'dem_utm37.tif'), 'dem_utm37')
assert dem.isValid()
QgsProject.instance().addMapLayer(dem)
iface.canvas.setDestinationCrs(crs)
iface.canvas.setLayers([dem])
iface.canvas.resize(900, 900)
iface.canvas.setExtent(QgsRectangle(746800, 4516700, 747800, 4517600))
iface.win.show()
app.processEvents()


def shutdown():
    """Stop rendering and destroy the canvas *before* GDAL is shut down."""
    iface.canvas.stopRendering()
    iface.canvas.waitWhileRendering()
    QgsProject.instance().removeAllMapLayers()
    iface.canvas.setLayers([])
    sip.delete(iface.win)
    app.processEvents()
    app.exitQgis()


def wait_task(dock, limit=300):
    t0 = time.time()
    while dock.task is not None and time.time() - t0 < limit:
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)
    assert dock.task is None, 'task did not finish'


mod = __import__(PKG)
plugin = mod.classFactory(iface)
plugin.initGui()
plugin.action.setChecked(True)          # opens the panel
dock = plugin.dock
app.processEvents()
assert dock.isUserVisible()
assert iface.canvas.mapTool() is dock.tool, 'drawing tool should be active on open'
dock.dem_mode.set_index(0)
dock.dem_combo.setLayer(dem)


def click(x, y, button=Qt.MouseButton.LeftButton):
    pt = iface.canvas.getCoordinateTransform().transform(QgsPointXY(x, y))
    pos = QPoint(int(round(pt.x())), int(round(pt.y())))
    dock.tool.canvasMoveEvent(QgsMapMouseEvent(iface.canvas, QEvent.Type.MouseMove, pos,
                                               Qt.MouseButton.NoButton))
    dock.tool.canvasReleaseEvent(QgsMapMouseEvent(iface.canvas, QEvent.Type.MouseButtonRelease,
                                                  pos, button))


# draw the line: finishing the line starts the calculation by itself
click(747142.08, 4517298.23)
click(747466.56, 4517032.13)
click(747466.56, 4517032.13, Qt.MouseButton.RightButton)
assert dock.task is not None, 'finishing the line should start the calculation'
wait_task(dock)
r = dock.result
assert r is not None, dock.status_lbl.text()
print('line:', dock.line_info.text())
print('level %.2f (ends %.1f / %.1f)  volume %.1f million m3  area %.3f km2  side %s'
      % (r.water_level, r.end_levels[0], r.end_levels[1], r.volume_m3 / 1e6,
         r.area_m2 / 1e6, r.side))
assert abs(r.water_level - min(r.end_levels)) < 1e-6
assert dock.results.isVisible() and dock.water_band is not None
print('status:', dock.status_lbl.text())


class Ev:
    def __init__(self, ax, xd, yd):
        self.inaxes, self.xdata, self.ydata, self.button = ax, xd, yd, 1
        self.x, self.y = 250.0, 150.0


dock.curve_chart._on_move(Ev(dock.curve_chart.ax_v, 50.0, 900.0))
assert 'Volume' in dock.curve_chart.tip.get_text()
dock.profile_chart._on_move(Ev(dock.profile_chart.ax, 200.0, 850.0))
assert 'Water depth' in dock.profile_chart.tip.get_text()
dock.curve_chart._on_leave(None)
dock.profile_chart._on_leave(None)
print('charts OK')

outs = __import__(PKG + '.gui.outputs', fromlist=['x'])
layers = outs.add_to_project(r)
assert all(lyr.isValid() for lyr in layers)
outs.write_csv(r, os.path.join(OUT, 'table.csv'))
outs.write_geopackage(r, os.path.join(OUT, 'reservoir.gpkg'))
dock.curve_chart.save_png(os.path.join(OUT, 'chart_curve.png'))
dock.profile_chart.save_png(os.path.join(OUT, 'chart_profile.png'))
print('outputs OK:', [lyr.name() for lyr in layers])

# a presentation map: hillshade + water depth + outline + line
from qgis.core import QgsHillshadeRenderer, QgsMapRendererParallelJob, QgsMapSettings  # noqa
from qgis.PyQt.QtCore import QSize  # noqa: E402
hs = QgsRasterLayer(dem.source(), 'hillshade')
hs.setRenderer(QgsHillshadeRenderer(hs.dataProvider(), 1, 315, 45))
QgsProject.instance().addMapLayer(hs, False)
ms = QgsMapSettings()
ms.setLayers(layers + [hs])
ms.setDestinationCrs(crs)
ext = layers[1].extent()
ext.scale(1.08)
ms.setExtent(ext)
ms.setOutputSize(QSize(1400, 1000))
ms.setBackgroundColor(QColor('white'))
job = QgsMapRendererParallelJob(ms)
job.start()
job.waitForFinished()
job.renderedImage().save(os.path.join(OUT, 'map.png'))
layers = None

# flip side through the real task manager
dock.flip_side()
wait_task(dock)
print('flip OK: side', dock.result.side, 'level %.1f' % dock.result.water_level,
      dock.result.limited_by)
dock.flip_side()
wait_task(dock)
assert dock.result.side == 'left'

# screenshots
dock.setFloating(True)
dock.resize(420, 1800)
app.processEvents()
tag = '_dark' if DARK else ''
for i in range(3):
    dock.chart_tabs.setCurrentIndex(i)
    page = dock.scroll.widget()
    page.resize(dock.scroll.viewport().width(), page.sizeHint().height())
    app.processEvents()
    dock.widget().grab().save(os.path.join(OUT, 'panel_%d%s.png' % (i, tag)))
    page.grab().save(os.path.join(OUT, 'page_%d%s.png' % (i, tag)))
dock.chart_tabs.setCurrentIndex(0)

if '--download' in sys.argv:
    dock.dem_mode.set_index(1)
    dock.source_combo.setCurrentIndex(dock.source_combo.findData('cop30'))
    # cancel a download as soon as it starts
    cache = __import__(PKG + '.gui.task', fromlist=['x']).dem_cache_dir()
    for f in os.listdir(cache):
        os.remove(os.path.join(cache, f))
    dock.run()
    t0 = time.time()
    while 'Downloading' not in dock.status_lbl.text() and time.time() - t0 < 60:
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
    assert dock.cancel_btn.isVisible()
    dock.cancel_btn.click()
    wait_task(dock)
    assert dock.status_lbl.text() == 'Cancelled.', dock.status_lbl.text()
    assert not any(f.endswith('.part.tif') for f in os.listdir(cache))
    print('download cancel OK after %.1fs' % (time.time() - t0))
    dock.run()
    wait_task(dock)
    print('download OK: level %.1f volume %.1f million m3 | %s' % (
        dock.result.water_level, dock.result.volume_m3 / 1e6, dock.status_lbl.text()))

plugin.unload()
gc.collect()
print('unload OK; outputs in', OUT)
dock = None
shutdown()
