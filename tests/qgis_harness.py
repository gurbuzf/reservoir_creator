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
if os.environ.get('RC_FONT'):   # readable screenshots on the offscreen platform
    from qgis.PyQt.QtGui import QFont  # noqa: E402
    app.setFont(QFont(os.environ['RC_FONT'], 9))
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


# start from known panel settings (a standalone QGIS keeps its own settings,
# separate from the desktop profile, and earlier runs may have changed them)
from qgis.core import QgsSettings  # noqa: E402
for key, value in (('line_mode', 0), ('dem_mode', 0), ('theme', 'auto'), ('language', 'en'),
                   ('fast_mode', False), ('floating', True)):
    QgsSettings().setValue('ReservoirCreator/' + key, value)

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


# draw the line: nothing is computed until the user presses "Create reservoir"
click(747142.08, 4517298.23)
click(747466.56, 4517032.13)
click(747466.56, 4517032.13, Qt.MouseButton.RightButton)
assert dock.task is None, "finishing the line must not start the calculation"
assert "Create reservoir" in dock.status_lbl.text(), dock.status_lbl.text()
dock.run_btn.click()
assert dock.task is not None, "the Create reservoir button should start the calculation"
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

print('cell size %.1f m | notes: %s' % (dock.result.grid.cell_size,
                                        [n.text for n in dock.result.notes]))
assert not dock.result.fast

# maximum water level below the line end sets the level
cap = round(dock.result.water_level - 20.0, 1)
dock.use_max_level.setChecked(True)
dock.max_level.setValue(cap)
dock.run_btn.click()
wait_task(dock)
assert abs(dock.result.water_level - cap) < 0.01 and dock.result.level_source == 'max'
print('max level OK: %.1f m -> volume %.1f million m3' % (cap, dock.result.volume_m3 / 1e6))
dock.use_max_level.setChecked(False)
dock.run_btn.click()
wait_task(dock)

# opens as a separate window by default; the Dock button attaches it and back
assert dock.isFloating(), 'the panel should open as a separate window'
assert dock.dock_btn.text() == 'Dock'
dock.dock_btn.click()
app.processEvents()
assert not dock.isFloating() and dock.dock_btn.text() == 'Undock'
dock.dock_btn.click()
app.processEvents()
assert dock.isFloating()
print('dock/undock OK')

# changing a setting keeps the result but asks for a new run
dock.fast_mode.setChecked(True)
assert 'Create reservoir' in dock.status_lbl.text() and dock.task is None
dock.run()
wait_task(dock)
assert dock.result.fast
dock.fast_mode.setChecked(False)
print('fast mode OK')

# "Start over" forgets the line and the results and re-arms drawing
dock.run()                                  # also while a run is in progress
dock.reset()
wait_task(dock)
assert dock.result is None and not dock.results.isVisible(), 'reset should drop results'
assert dock.drawn_geom is None and dock.water_band is None and dock.line_band is None
assert dock.table.rowCount() == 0 and not dock.curve_chart.has_data
assert iface.canvas.mapTool() is dock.tool, 'drawing should be re-armed after reset'
assert dock.status_lbl.text() == 'Draw a line across a valley to begin.', dock.status_lbl.text()
print('reset OK:', dock.status_lbl.text())
click(747142.08, 4517298.23)
click(747466.56, 4517032.13)
click(747466.56, 4517032.13, Qt.MouseButton.RightButton)
dock.run_btn.click()
wait_task(dock)
assert dock.result is not None

# maximum depth above what the line can hold: warn and go ahead with the line
dock.use_max_level.setChecked(True)
dock.limit_kind.setCurrentIndex(1)
dock.max_level.setValue(500.0)
dock.run_btn.click()
wait_task(dock)
assert dock.result.cap_ignored and dock.result.level_source == 'line'
assert abs(dock.result.water_level - min(dock.result.end_levels)) < 1e-6
dock.use_max_level.setChecked(False)
dock.limit_kind.setCurrentIndex(0)
print('max depth OK: capped at the line end with a warning')

# regression: a paint while a chart redraw is pending must not repaint from
# inside the paint (Qt painter errors; crashed QGIS 3.40)
from qgis.PyQt.QtCore import qInstallMessageHandler  # noqa: E402
qt_msgs = []
old_handler = qInstallMessageHandler(lambda _m, _c, msg: qt_msgs.append(msg))
dock.chart_tabs.setCurrentIndex(0)
for _ in range(5):
    dock.curve_chart.refresh()
    dock.curve_chart.canvas.repaint()
    app.processEvents()
qInstallMessageHandler(old_handler)
assert not [m for m in qt_msgs if 'Painter' in m or 'paint device' in m.lower()], qt_msgs[:3]
print('paint regression OK')

# regression: choosing Dark / Türkçe from the real, open ⚙ menu (the rebuild
# must not delete the menu while its event loop is running)
from qgis.PyQt.QtCore import QTimer  # noqa: E402
from qgis.PyQt.QtWidgets import QToolButton  # noqa: E402
for label in ('Dark', 'Türkçe', 'English', 'Auto (follow QGIS)'):
    btn = next(b for b in dock.widget().findChildren(QToolButton)
               if b.objectName() == 'rcIcon' and b.menu() is not None)
    act = next(a for a in btn.menu().actions() if a.text() == label)
    QTimer.singleShot(150, act.trigger)
    QTimer.singleShot(300, btn.menu().close)
    btn.showMenu()
    for _ in range(10):
        app.processEvents()
assert dock.run_btn.text() == 'Create reservoir' and dock.result is not None
print('menu switch OK')

# References and Guide pages
from qgis.PyQt.QtWidgets import QLabel as _QLabel  # noqa: E402
for i, must in ((1, 'github.com/gurbuzf/reservoir_creator'), (1, 'doi.org/10.7717/peerj.19673'),
                (2, 'Create reservoir')):
    dock.page_switch.set_index(i)
    app.processEvents()
    text = ' '.join(lab.text() for lab in dock.pages.currentWidget().findChildren(_QLabel))
    assert must in text, (i, must)
    assert not dock.action_bar.isVisible()
dock.setFloating(True)
dock.resize(440, 1500)
for i in (1, 2):
    dock.page_switch.set_index(i)
    app.processEvents()
    dock.widget().grab().save(os.path.join(OUT, 'page_%s.png' % ('references', 'guide')[i - 1]))
dock.page_switch.set_index(0)
assert dock.action_bar.isVisible()
print('references + guide OK')

# theme and language rebuild the panel and keep the result
theme_mod = __import__(PKG + '.gui.theme', fromlist=['x'])
dock.set_theme('dark')
app.processEvents()
assert theme_mod.is_dark(dock.root), dock.root.palette().color(QPalette.ColorRole.Window).name()
assert dock.result is not None, 'result lost on rebuild'
assert dock.results.isVisible(), 'results hidden after rebuild'
dock.set_language('tr')
app.processEvents()
assert dock.run_btn.text() == 'Rezervuar oluştur', dock.run_btn.text()
assert dock.results.isVisible() and dock.water_band is not None
dock.setFloating(True)
dock.resize(440, 1800)
for i in range(2):
    dock.chart_tabs.setCurrentIndex(i)
    page = dock.scroll.widget()
    page.resize(dock.scroll.viewport().width(), page.sizeHint().height())
    app.processEvents()
    dock.widget().grab().save(os.path.join(OUT, 'panel_tr_dark_%d.png' % i))
dock.chart_tabs.setCurrentIndex(0)
dock.set_language('en')
dock.set_theme('light')
app.processEvents()
dock.widget().grab().save(os.path.join(OUT, 'panel_forced_light.png'))
dock.set_theme('auto')
assert dock.run_btn.text() == 'Create reservoir'
print('theme + language OK')

if '--download' in sys.argv:
    dock.dem_mode.set_index(1)
    dock.source_combo.setCurrentIndex(dock.source_combo.findData('cop30'))
    # cancel a download as soon as it starts
    cache = __import__(PKG + '.gui.task', fromlist=['x']).dem_cache_dir()
    import shutil  # noqa: E402
    shutil.rmtree(cache, ignore_errors=True)
    os.makedirs(cache, exist_ok=True)
    dock.run()
    t0 = time.time()
    while 'Downloading' not in dock.status_lbl.text() and time.time() - t0 < 60:
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
    assert dock.cancel_btn.isVisible()
    dock.cancel_btn.click()
    wait_task(dock)
    assert dock.status_lbl.text() == 'Cancelled.', dock.status_lbl.text()
    assert not any(f.endswith('.part.tif') for _d, _s, fs in os.walk(cache) for f in fs)
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
