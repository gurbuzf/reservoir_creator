# -*- coding: utf-8 -*-
"""Headless smoke test of the plugin inside a real QGIS (offscreen).

    QT_QPA_PLATFORM=offscreen python3 tests/qgis_harness.py [outdir] [--dark]

Loads the plugin with a minimal iface, draws the dam axis with simulated
mouse clicks, runs the analysis on the sample data, exercises every export
and saves screenshots of the dock.
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
sys.path.insert(0, os.path.dirname(PLUGIN))
from osgeo import gdal  # noqa: E402
gdal.UseExceptions()
PKG = os.path.basename(PLUGIN)

from qgis.core import (QgsApplication, QgsCoordinateReferenceSystem, QgsPointXY,  # noqa: E402
                       QgsProject, QgsRasterLayer, QgsRectangle)
from qgis.gui import QgsMapCanvas, QgsMapMouseEvent, QgsMessageBar  # noqa: E402
from qgis.PyQt.QtCore import QEvent, QPoint, Qt  # noqa: E402
from qgis.PyQt.QtGui import QColor, QPalette  # noqa: E402
from qgis.PyQt.QtWidgets import QMainWindow, QToolBar  # noqa: E402

OUT = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith('--') else tempfile.mkdtemp()
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
        self.messages = []
        self.bar.widgetAdded.connect(lambda w: self.messages.append(w.text() if hasattr(w, 'text') else ''))

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

STOP = os.environ.get('RC_STOP', '')


def shutdown():
    """Stop rendering and destroy the canvas *before* GDAL is shut down."""
    from qgis.PyQt import sip
    iface.canvas.stopRendering()
    iface.canvas.waitWhileRendering()
    QgsProject.instance().removeAllMapLayers()
    iface.canvas.setLayers([])
    sip.delete(iface.win)
    app.processEvents()
    app.exitQgis()


def stage(name):
    """Debug helper: RC_STOP=<name> ends the run here with a normal teardown."""
    if STOP != name:
        return
    import gc
    plugin.unload()
    gc.collect()
    shutdown()
    sys.exit(0)


mod = __import__(PKG)
plugin = mod.classFactory(iface)
plugin.initGui()
plugin.action.setChecked(True)          # opens the dock
dock = plugin.dock
app.processEvents()
assert dock.isUserVisible()
assert iface.canvas.mapTool() is dock.tool, 'drawing tool should be active on open'
stage('open')

dock.dem_mode.set_index(0)
dock.dem_combo.setLayer(dem)
dock.auto_run.setChecked(False)
dock.mol.setValue(850.0)
dock.inflow.setValue(25.0)

# draw the dam axis with simulated clicks
def click(x, y, button=Qt.MouseButton.LeftButton):
    pt = iface.canvas.getCoordinateTransform().transform(QgsPointXY(x, y))
    pos = QPoint(int(round(pt.x())), int(round(pt.y())))
    for et in (QEvent.Type.MouseMove, QEvent.Type.MouseButtonRelease):
        ev = QgsMapMouseEvent(iface.canvas, et, pos,
                              button if et != QEvent.Type.MouseMove else Qt.MouseButton.NoButton)
        (dock.tool.canvasMoveEvent if et == QEvent.Type.MouseMove else dock.tool.canvasReleaseEvent)(ev)

click(747142.08, 4517298.23)
click(747466.56, 4517032.13)
click(747466.56, 4517032.13, Qt.MouseButton.RightButton)
app.processEvents()
assert dock.axis_geom is not None, 'axis not captured'
print('axis:', dock.axis_info.text())
stage('drawn')

# run synchronously (same code path as the task manager, minus threading)
params, download = dock._collect_params()
from importlib import import_module  # noqa: E402
task_mod = import_module(PKG + '.gui.task')
task = task_mod.ReservoirTask(params, download)
ok = task.run()
assert ok, task.error
dock.task = task
dock._task_done()
app.processEvents()
del task
stage('analysed')
m = dock.model
print('upstream', m.upstream_side, 'bed', m.bed_level, 'max', m.max_level, m.limit_reason,
      'nwl', m.default_nwl)
dock.heavy_timer.stop()
dock._update_polygon()
s = dock.stats
print('storage hm3 %.2f area km2 %.3f shore km %.1f' % (s['volume_m3'] / 1e6, s['area_m2'] / 1e6,
                                                     s['shoreline_m'] / 1e3))
for n in m.notes:
    print('  note:', n)

# chart interaction: pick a level from the capacity chart
dock.cap_chart.levelPicked.emit(900.0)
assert abs(dock.level_spin.value() - 900.0) < 1e-6
dock._update_polygon()
dock.set_level(m.default_nwl)
dock._update_polygon()

# hover / click simulation on every chart
class Ev:
    def __init__(self, ax, xd, yd, button=1):
        self.inaxes, self.xdata, self.ydata, self.button = ax, xd, yd, button
        self.x, self.y = 250.0, 150.0


cap, sec, siz = dock.cap_chart, dock.sec_chart, dock.size_chart
cap._on_move(Ev(cap.ax_v, 50.0, 900.0))
assert cap.tip.get_visible() and 'Storage' in cap.tip.get_text()
sec._on_move(Ev(sec.ax, 200.0, 850.0))
assert 'Ground' in sec.tip.get_text()
siz._on_move(Ev(siz.ax2, 900.0, 10.0))
assert 'Crest length' in siz.tip.get_text()
siz._on_click(Ev(siz.ax1, 880.0, 1.0))
assert abs(dock.level_spin.value() - 880.0) < 1e-6
cap._on_leave(None)
dock.set_level(m.default_nwl)
dock._update_polygon()
print('chart interaction OK')
stage('charts')

# outputs
outs = import_module(PKG + '.gui.outputs')
layers = outs.add_to_project(m, dock._full_stats())
assert all(lyr.isValid() for lyr in layers), [lyr.name() for lyr in layers if not lyr.isValid()]
print('layers:', [lyr.name() for lyr in layers], 'features', layers[1].featureCount())

# a presentation map: hillshade + water depth + outline + dam axis
from qgis.core import (QgsHillshadeRenderer, QgsMapRendererParallelJob,  # noqa: E402
                       QgsMapSettings)
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
del layers
stage('layers')
outs.write_csv(m, os.path.join(OUT, 'eac.csv'))
outs.write_geopackage(m, dock._full_stats(), os.path.join(OUT, 'reservoir.gpkg'))
for i, ch in enumerate((dock.cap_chart, dock.sec_chart, dock.size_chart)):
    ch.save_png(os.path.join(OUT, 'chart_%d.png' % i))

# screenshots of the dock
dock.setFloating(True)
dock.resize(430, 1900)
dock.tabs.setCurrentIndex(0)
app.processEvents()
tag = '_dark' if DARK else ''
dock.widget().grab().save(os.path.join(OUT, 'dock_setup%s.png' % tag))
dock.tabs.setCurrentIndex(1)
for i in range(4):
    dock.chart_tabs.setCurrentIndex(i)
    app.processEvents()
    area = dock.tabs.widget(1)
    inner = area.widget()
    inner.resize(area.viewport().width(), inner.sizeHint().height())
    app.processEvents()
    inner.grab().save(os.path.join(OUT, 'dock_results_%d%s.png' % (i, tag)))
iface.canvas.refreshAllLayers()
app.processEvents()
iface.canvas.grab().save(os.path.join(OUT, 'canvas%s.png' % tag))

# real asynchronous runs through the QGIS task manager
if '--async' in sys.argv:
    import time
    from qgis.PyQt.QtCore import QEventLoop

    def wait_task(limit=300):
        t0 = time.time()
        while dock.task is not None and time.time() - t0 < limit:
            app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 100)
        assert dock.task is None, 'task did not finish'

    before = dock.model.upstream_side
    dock.flip_upstream()
    wait_task()
    print('async flip OK:', before, '->', dock.model.upstream_side,
          'max %.1f' % dock.model.max_level, dock.model.limit_reason)
    dock.upstream.setCurrentIndex(0)
    dock.dem_mode.set_index(1)
    dock.source_combo.setCurrentIndex(dock.source_combo.findData('cop30'))
    dock.add_dem.setChecked(True)
    dock.run()
    wait_task()
    assert dock.model.params.dem_path.endswith('.tif'), dock.status_lbl.text()
    print('async download OK:', os.path.basename(dock.model.params.dem_path),
          'V(927) %.1f hm3' % (dock.model.volume(927.0) / 1e6), '| status:', dock.status_lbl.text())
    print('  project layers:', [lyr.name() for lyr in QgsProject.instance().mapLayers().values()])

# unload
plugin.unload()
import gc; app.processEvents(); gc.collect(); app.processEvents(); print("after unload+gc OK")
if "--reload" in sys.argv:
    plugin = mod.classFactory(iface); plugin.initGui(); plugin.action.setChecked(True); app.processEvents(); plugin.unload(); gc.collect(); print("reload OK")
print('unloaded OK; outputs in', OUT)
dock = None
shutdown()
