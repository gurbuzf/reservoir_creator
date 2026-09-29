# -*- coding: utf-8 -*-
"""The Reservoir Creator panel: draw a line, pick a DEM, get the reservoir."""

import os

from qgis.core import (Qgis, QgsApplication, QgsCoordinateTransform, QgsDistanceArea,
                       QgsGeometry, QgsMapLayerProxyModel, QgsPointXY, QgsProject,
                       QgsRasterLayer, QgsSettings, QgsWkbTypes)
from qgis.gui import QgsDockWidget, QgsMapLayerComboBox, QgsRubberBand, QgsVertexMarker
from qgis.PyQt.QtCore import Qt, QTimer, QUrl
from qgis.PyQt.QtGui import QColor, QDesktopServices, QFont, QGuiApplication, QIcon
from qgis.PyQt.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFileDialog,
                                 QFrame, QHBoxLayout, QHeaderView, QLabel, QMenu,
                                 QProgressBar, QPushButton, QScrollArea, QTableWidget,
                                 QTableWidgetItem, QTabWidget, QToolButton, QVBoxLayout,
                                 QWidget)

from ..core import analysis, dem_sources
from ..core.analysis import Note
from . import outputs, theme
from .map_tools import DamAxisTool
from .task import ReservoirTask
from .widgets import Banner, Card, Segmented, TileGrid, hint, primary_button, scaled_font, stylesheet

try:
    from .charts import CurveChart, ProfileChart
    HAS_MPL = True
except Exception:  # pragma: no cover - matplotlib missing
    HAS_MPL = False

SETTINGS = 'ReservoirCreator/'
HELP_URL = 'https://github.com/gurbuzf/reservoir_creator#readme'
RIGHT_ALIGN = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter


def _icon(name):
    return QgsApplication.getThemeIcon(name)


def _layer_filter(name):
    enum = getattr(Qgis, 'LayerFilter', None)
    return getattr(enum if enum is not None else QgsMapLayerProxyModel.Filter, name)


class ReservoirDock(QgsDockWidget):

    def __init__(self, iface, plugin_dir, parent=None):
        super().__init__('Reservoir Creator', parent)
        self.setObjectName('ReservoirCreatorDock')
        self.iface = iface
        self.canvas = iface.mapCanvas()
        self.plugin_dir = plugin_dir
        self.result = None
        self.task = None
        self.drawn_geom = None
        self.drawn_crs = None
        self.line_band = None
        self.water_band = None
        self.escape_marker = None

        self.tool = DamAxisTool(self.canvas, theme.LIGHT['dam'])
        self.tool.axisCompleted.connect(self._line_drawn)
        self.tool.status.connect(self._status)
        self.canvas.mapToolSet.connect(self._map_tool_changed)

        # owned by the panel, so it can never fire after the panel is deleted
        self.scroll_timer = QTimer(self)
        self.scroll_timer.setSingleShot(True)
        self.scroll_timer.setInterval(0)

        self._build()
        self.scroll_timer.timeout.connect(
            lambda: self.scroll.ensureWidgetVisible(self.results, 0, 0))
        self._load_settings()

    # ------------------------------------------------------------------ UI
    def _build(self):
        root = QWidget()
        root.setStyleSheet(stylesheet(root))
        outer = QVBoxLayout(root)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(8)

        head = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(QIcon(os.path.join(self.plugin_dir, 'icons', 'icon.svg')).pixmap(30, 30))
        head.addWidget(logo, 0, Qt.AlignmentFlag.AlignTop)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        title = QLabel('Reservoir Creator')
        title.setFont(scaled_font(title, 1.35, QFont.Weight.DemiBold))
        titles.addWidget(title)
        titles.addWidget(hint('Draw a line across a valley to see the reservoir behind it'))
        head.addLayout(titles, 1)
        help_btn = QToolButton()
        help_btn.setIcon(_icon('/mActionHelpContents.svg'))
        help_btn.setToolTip('Open the documentation')
        help_btn.setAutoRaise(True)
        help_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(HELP_URL)))
        head.addWidget(help_btn, 0, Qt.AlignmentFlag.AlignTop)
        outer.addLayout(head)

        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 4, 0)
        v.setSpacing(10)
        v.addWidget(self._line_card())
        v.addWidget(self._dem_card())
        self.results = self._results_card()
        self.results.setVisible(False)
        v.addWidget(self.results)
        v.addStretch(1)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setWidget(page)
        outer.addWidget(self.scroll, 1)

        bar = QHBoxLayout()
        self.run_btn = primary_button('Create reservoir')
        self.run_btn.setIcon(_icon('/mActionStart.svg'))
        self.run_btn.clicked.connect(lambda: self.run())
        self.cancel_btn = QPushButton('Cancel')
        self.cancel_btn.setIcon(_icon('/mTaskCancel.svg'))
        self.cancel_btn.setToolTip('Stop the download / calculation')
        self.cancel_btn.setVisible(False)
        self.cancel_btn.clicked.connect(self.cancel)
        bar.addWidget(self.run_btn, 1)
        bar.addWidget(self.cancel_btn)
        outer.addLayout(bar)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setTextVisible(False)
        self.progress.setMaximumHeight(6)
        self.progress.setVisible(False)
        outer.addWidget(self.progress)
        self.status_lbl = hint('Draw a line across a valley to begin.')
        outer.addWidget(self.status_lbl)

        for combo in page.findChildren(QComboBox):
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(12)
        self.setWidget(root)
        self.setMinimumWidth(340)

    def _line_card(self):
        card = Card('1 · Dam line',
                    'The water level is the ground height at the lower end of the line.')
        self.line_mode = Segmented(['Draw on map', 'From layer'],
                                   [_icon('/mActionCaptureLine.svg'), _icon('/mIconLineLayer.svg')])
        self.line_mode.changed.connect(self._line_mode_changed)
        card.body.addWidget(self.line_mode)

        self.draw_page = QWidget()
        dl = QVBoxLayout(self.draw_page)
        dl.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self.draw_btn = QPushButton('Draw line')
        self.draw_btn.setIcon(_icon('/mActionCaptureLine.svg'))
        self.draw_btn.setCheckable(True)
        self.draw_btn.toggled.connect(self._draw_toggled)
        clear = QPushButton('Clear')
        clear.setIcon(_icon('/mActionDeleteSelected.svg'))
        clear.clicked.connect(self.clear)
        row.addWidget(self.draw_btn, 1)
        row.addWidget(clear)
        dl.addLayout(row)
        dl.addWidget(hint('Click from one side of the valley to the other, right-click to '
                          'finish. Backspace removes the last point, Esc cancels.'))
        card.body.addWidget(self.draw_page)

        self.layer_page = QWidget()
        ll = QVBoxLayout(self.layer_page)
        ll.setContentsMargins(0, 0, 0, 0)
        self.line_combo = QgsMapLayerComboBox()
        self.line_combo.setFilters(_layer_filter('LineLayer'))
        self.line_combo.setAllowEmptyLayer(True)
        self.line_combo.layerChanged.connect(lambda *_: self._show_line())
        self.selected_only = QCheckBox('Use the selected feature')
        self.selected_only.toggled.connect(lambda *_: self._show_line())
        ll.addWidget(self.line_combo)
        ll.addWidget(self.selected_only)
        card.body.addWidget(self.layer_page)

        self.line_info = hint('No line yet.')
        card.body.addWidget(self.line_info)
        return card

    def _dem_card(self):
        card = Card('2 · Elevation data (DEM)')
        self.dem_mode = Segmented(['Project layer', 'Download'],
                                  [_icon('/mIconRaster.svg'), _icon('/mActionAddWcsLayer.svg')])
        self.dem_mode.changed.connect(self._dem_mode_changed)
        card.body.addWidget(self.dem_mode)
        self.dem_page = QWidget()
        l1 = QVBoxLayout(self.dem_page)
        l1.setContentsMargins(0, 0, 0, 0)
        self.dem_combo = QgsMapLayerComboBox()
        self.dem_combo.setFilters(_layer_filter('RasterLayer'))
        self.dem_combo.setAllowEmptyLayer(True)
        l1.addWidget(self.dem_combo)
        card.body.addWidget(self.dem_page)
        self.dl_page = QWidget()
        l2 = QVBoxLayout(self.dl_page)
        l2.setContentsMargins(0, 0, 0, 0)
        self.source_combo = QComboBox()
        for src in dem_sources.SOURCES:
            self.source_combo.addItem(src.name, src.key)
        self.source_combo.currentIndexChanged.connect(self._source_changed)
        l2.addWidget(self.source_combo)
        self.source_hint = hint('')
        l2.addWidget(self.source_hint)
        self.add_dem = QCheckBox('Add the downloaded DEM to the project')
        l2.addWidget(self.add_dem)
        card.body.addWidget(self.dl_page)
        self._source_changed()
        return card

    def _results_card(self):
        card = Card('Reservoir')
        self.banner_box = QVBoxLayout()
        self.banner_box.setSpacing(4)
        card.body.addLayout(self.banner_box)
        self.tiles = TileGrid(2)
        self.tiles.add('level', 'Water level', 'm', 'Ground height at the lower end of the line')
        self.tiles.add('volume', 'Volume', 'million m³')
        self.tiles.add('area', 'Surface area', 'km²')
        self.tiles.add('depth', 'Max. depth', 'm', 'Water level − lowest point of the reservoir')
        card.body.addWidget(self.tiles)

        self.chart_tabs = QTabWidget()
        self.chart_tabs.setDocumentMode(True)
        if HAS_MPL:
            self.curve_chart = CurveChart()
            self.profile_chart = ProfileChart(min_height=240)
            self.chart_tabs.addTab(self.curve_chart, 'Area && volume')
            self.chart_tabs.addTab(self.profile_chart, 'Line profile')
        else:
            self.curve_chart = self.profile_chart = None
            self.chart_tabs.addTab(hint('Install matplotlib to see the charts.'), 'Charts')
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(['Level (m)', 'Area (km²)', 'Volume (million m³)'])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setMinimumHeight(280)
        self.chart_tabs.addTab(self.table, 'Table')
        card.body.addWidget(self.chart_tabs)

        act = QHBoxLayout()
        add = QPushButton('Add to map')
        add.setIcon(_icon('/mActionAddLayer.svg'))
        add.setToolTip('Add the reservoir outline, the line and the water depth as layers')
        add.clicked.connect(self.add_to_map)
        export = QToolButton()
        export.setText('Export')
        export.setIcon(_icon('/mActionFileSave.svg'))
        export.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        export.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(export)
        for text, slot in (('GeoPackage (outline, line, table)…', self.export_gpkg),
                           ('Water depth (GeoTIFF)…', self.export_depth),
                           ('Table (CSV)…', self.export_csv),
                           ('Copy table', self.copy_table),
                           ('Chart image (PNG)…', self.export_chart)):
            menu.addAction(text).triggered.connect(slot)
        export.setMenu(menu)
        flip = QToolButton()
        flip.setIcon(_icon('/mActionReverseLine.svg'))
        flip.setToolTip('Wrong side? Put the reservoir on the other side of the line')
        flip.clicked.connect(self.flip_side)
        zoom = QToolButton()
        zoom.setIcon(_icon('/mActionZoomToLayer.svg'))
        zoom.setToolTip('Zoom to the reservoir')
        zoom.clicked.connect(self.zoom_to_reservoir)
        act.addWidget(add, 1)
        act.addWidget(export)
        act.addWidget(flip)
        act.addWidget(zoom)
        card.body.addLayout(act)
        return card

    # ------------------------------------------------------------ settings
    def _load_settings(self):
        s = QgsSettings()
        self.line_mode.set_index(s.value(SETTINGS + 'line_mode', 0, type=int))
        self.dem_mode.set_index(s.value(SETTINGS + 'dem_mode', 0, type=int))
        i = self.source_combo.findData(s.value(SETTINGS + 'source', 'gedtm30', type=str))
        self.source_combo.setCurrentIndex(max(0, i))
        self.add_dem.setChecked(s.value(SETTINGS + 'add_dem', False, type=bool))

    def _save_settings(self):
        s = QgsSettings()
        s.setValue(SETTINGS + 'line_mode', self.line_mode.index())
        s.setValue(SETTINGS + 'dem_mode', self.dem_mode.index())
        s.setValue(SETTINGS + 'source', self.source_combo.currentData())
        s.setValue(SETTINGS + 'add_dem', self.add_dem.isChecked())

    # ---------------------------------------------------------------- line
    def _line_mode_changed(self, i):
        self.draw_page.setVisible(i == 0)
        self.layer_page.setVisible(i == 1)
        if i == 1:
            self.draw_btn.setChecked(False)
        self._show_line()

    def _draw_toggled(self, on):
        if on:
            if self.canvas.mapTool() is not self.tool:
                self.canvas.setMapTool(self.tool)
            self._status('Click across the valley; right-click to finish.')
        elif self.canvas.mapTool() is self.tool:
            self.canvas.unsetMapTool(self.tool)

    def _map_tool_changed(self, new, _old=None):
        if new is not self.tool and self.draw_btn.isChecked():
            self.draw_btn.blockSignals(True)
            self.draw_btn.setChecked(False)
            self.draw_btn.blockSignals(False)

    def activate_drawing(self):
        """Called when the panel opens: start drawing straight away."""
        if self.line_mode.index() == 0:
            self.draw_btn.setChecked(True)

    def _line_drawn(self, geom):
        self.drawn_geom = geom
        self.drawn_crs = self.canvas.mapSettings().destinationCrs()
        self.draw_btn.setChecked(False)
        self._show_line()
        if self._dem_ready():
            self.run()
        else:
            self._status('Line drawn. Now choose the elevation data (step 2).')

    def clear(self):
        self.drawn_geom = None
        self.drawn_crs = None
        self._clear_overlays()
        self._show_line()
        self.results.setVisible(False)
        self.result = None

    def _current_line(self):
        if self.line_mode.index() == 0:
            if self.drawn_geom is None:
                return None, None
            return self._points(self.drawn_geom), self.drawn_crs
        lyr = self.line_combo.currentLayer()
        if lyr is None:
            return None, None
        feats = lyr.selectedFeatures() if self.selected_only.isChecked() else []
        if not feats:
            feats = [f for _, f in zip(range(1), lyr.getFeatures())]
        if not feats:
            return None, None
        return self._points(feats[0].geometry()), lyr.crs()

    @staticmethod
    def _points(geom):
        if geom is None or geom.isEmpty():
            return None
        g = QgsGeometry(geom)
        if QgsWkbTypes.isCurvedType(g.wkbType()):
            g = QgsGeometry(g.constGet().segmentize())
        if g.isMultipart():
            parts = g.asMultiPolyline()
            pts = parts[0] if parts else []
        else:
            pts = g.asPolyline()
        pts = [(p.x(), p.y()) for p in pts]
        return pts if len(pts) >= 2 else None

    def _show_line(self):
        if self.line_band is not None:
            self.canvas.scene().removeItem(self.line_band)
            self.line_band = None
        pts, crs = self._current_line()
        if not pts:
            self.line_info.setText('No line yet.')
            return
        geom = QgsGeometry.fromPolylineXY([QgsPointXY(x, y) for x, y in pts])
        self.line_band = QgsRubberBand(self.canvas, Qgis.GeometryType.Line)
        self.line_band.setColor(QColor(theme.LIGHT['dam']))
        self.line_band.setWidth(4)
        self.line_band.setToGeometry(geom, crs)
        d = QgsDistanceArea()
        d.setSourceCrs(crs, QgsProject.instance().transformContext())
        d.setEllipsoid(QgsProject.instance().ellipsoid() or 'WGS84')
        self.line_info.setText('✔ Line: {:,.0f} m long'.format(d.measureLength(geom)))

    # ----------------------------------------------------------------- DEM
    def _dem_mode_changed(self, i):
        self.dem_page.setVisible(i == 0)
        self.dl_page.setVisible(i == 1)

    def _source_changed(self, *_):
        src = dem_sources.SOURCES_BY_KEY[self.source_combo.currentData()]
        self.source_hint.setText('{} Only the area around the line is downloaded; you can '
                                 'cancel at any time.'.format(src.description))
        self.source_hint.setToolTip(src.citation)

    def _dem_ready(self):
        return self.dem_mode.index() == 1 or self.dem_combo.currentLayer() is not None

    # ----------------------------------------------------------------- run
    def run(self, side='auto'):
        if self.task is not None:
            return
        pts, crs = self._current_line()
        if not pts:
            self._message('Draw a line across the valley first (step 1).', Qgis.MessageLevel.Warning)
            return
        download = None
        dem_path = ''
        if self.dem_mode.index() == 0:
            lyr = self.dem_combo.currentLayer()
            if lyr is None:
                self._message('Choose a DEM layer, or switch to "Download" (step 2).',
                              Qgis.MessageLevel.Warning)
                return
            if lyr.providerType() != 'gdal':
                self._message('The DEM must be a file-based raster layer.',
                              Qgis.MessageLevel.Warning)
                return
            dem_path = lyr.source()
        else:
            download = self.source_combo.currentData()
        self._save_settings()
        params = analysis.Params(dem_path, pts, crs.toWkt(), side=side)
        self.task = ReservoirTask(params, download)
        self.task.progressChanged.connect(lambda p: self.progress.setValue(int(p)))
        self.task.message.connect(self._status)
        self.task.taskCompleted.connect(self._task_done)
        self.task.taskTerminated.connect(self._task_done)
        self._set_running(True)
        QgsApplication.taskManager().addTask(self.task)

    def cancel(self):
        if self.task is not None:
            self.task.cancel()
            self._status('Cancelling…')

    def _set_running(self, running):
        self.run_btn.setEnabled(not running)
        self.cancel_btn.setVisible(running)
        self.progress.setVisible(running)
        self.progress.setValue(0)

    def _task_done(self):
        task, self.task = self.task, None
        self._set_running(False)
        if task is None:
            return
        if task.result is None:
            if task.error == 'Cancelled.':
                self._status('Cancelled.')
            else:
                self._message(task.error or 'Something went wrong.', Qgis.MessageLevel.Critical)
            return
        res = task.result
        if task.download_source:
            src = dem_sources.SOURCES_BY_KEY[task.download_source]
            res.notes[:0] = [Note(Note.INFO, n) for n in task.download_notes]
            res.notes.append(Note(Note.INFO, 'Elevation data: {} ({}).'.format(
                src.short, src.license)))
            if task.downloaded_path and self.add_dem.isChecked():
                lyr = QgsRasterLayer(task.downloaded_path, '{} (download)'.format(src.short))
                if lyr.isValid():
                    QgsProject.instance().addMapLayer(lyr)
        self.result = res
        self._show_result()

    def flip_side(self):
        if self.result is not None:
            self.run('right' if self.result.side == 'left' else 'left')

    # ------------------------------------------------------------- results
    def _show_result(self):
        r = self.result
        while self.banner_box.count():
            w = self.banner_box.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        for n in r.notes:
            self.banner_box.addWidget(Banner(n.level, n.text))
        self.tiles.set('level', theme.fmt(r.water_level, 1))
        self.tiles.set('volume', theme.fmt_sig(r.volume_m3 / 1e6, 4))
        self.tiles.set('area', theme.fmt_sig(r.area_m2 / 1e6, 3))
        self.tiles.set('depth', theme.fmt(r.max_depth, 1))

        lv, a, v = r.curve()
        self.table.setRowCount(len(lv))
        for i, row in enumerate(zip(lv, a, v)):
            texts = ('{:.2f}'.format(row[0]), theme.fmt_sig(row[1] / 1e6, 4),
                     theme.fmt_sig(row[2] / 1e6, 5))
            for j, text in enumerate(texts):
                it = QTableWidgetItem(text)
                it.setTextAlignment(RIGHT_ALIGN)
                self.table.setItem(i, j, it)
        if HAS_MPL:
            self.curve_chart.set_data(lv, a, v, r.water_level)
            self.profile_chart.set_data(r.stations, r.ground, r.water_level)

        self._clear_overlays()
        crs = outputs.result_crs(r)
        if r.polygon_wkt:
            self.water_band = QgsRubberBand(self.canvas, Qgis.GeometryType.Polygon)
            c = QColor(theme.LIGHT['storage'])
            self.water_band.setStrokeColor(c)
            c.setAlpha(80)
            self.water_band.setFillColor(c)
            self.water_band.setWidth(1)
            self.water_band.setToGeometry(QgsGeometry.fromWkt(r.polygon_wkt), crs)
        if r.limited_by == 'saddle' and r.pour_point is not None:
            tr = QgsCoordinateTransform(crs, self.canvas.mapSettings().destinationCrs(),
                                        QgsProject.instance())
            mk = QgsVertexMarker(self.canvas)
            mk.setCenter(tr.transform(QgsPointXY(*r.pour_point)))
            mk.setIconType(QgsVertexMarker.IconType.ICON_X)
            mk.setColor(QColor(theme.LIGHT['critical']))
            mk.setIconSize(14)
            mk.setPenWidth(3)
            self.escape_marker = mk
        self.results.setVisible(True)
        self.scroll_timer.start()
        self._status('Reservoir at {:.1f} m: {} million m³, {} km².'.format(
            r.water_level, theme.fmt_sig(r.volume_m3 / 1e6, 4), theme.fmt_sig(r.area_m2 / 1e6, 3)))

    def _clear_overlays(self):
        for attr in ('water_band', 'escape_marker'):
            item = getattr(self, attr)
            if item is not None:
                self.canvas.scene().removeItem(item)
                setattr(self, attr, None)

    # ------------------------------------------------------------- outputs
    def add_to_map(self):
        if self.result is not None:
            outputs.add_to_project(self.result)
            self._message('Reservoir added to the project.', Qgis.MessageLevel.Success)

    def zoom_to_reservoir(self):
        r = self.result
        if r is None or not r.polygon_wkt:
            return
        tr = QgsCoordinateTransform(outputs.result_crs(r),
                                    self.canvas.mapSettings().destinationCrs(),
                                    QgsProject.instance())
        rect = tr.transformBoundingBox(QgsGeometry.fromWkt(r.polygon_wkt).boundingBox())
        rect.scale(1.1)
        self.canvas.setExtent(rect)
        self.canvas.refresh()

    def _ask_path(self, title, filt, default):
        folder = QgsSettings().value(SETTINGS + 'last_dir', os.path.expanduser('~'), type=str)
        path, _ = QFileDialog.getSaveFileName(self, title, os.path.join(folder, default), filt)
        if path:
            QgsSettings().setValue(SETTINGS + 'last_dir', os.path.dirname(path))
        return path

    def export_csv(self):
        if self.result is None:
            return
        path = self._ask_path('Export table', 'CSV (*.csv)', 'reservoir_table.csv')
        if path:
            outputs.write_csv(self.result, path)
            self._message('Saved {}'.format(path), Qgis.MessageLevel.Success)

    def export_gpkg(self):
        if self.result is None:
            return
        path = self._ask_path('Export to GeoPackage', 'GeoPackage (*.gpkg)', 'reservoir.gpkg')
        if path:
            try:
                outputs.write_geopackage(self.result, path)
                self._message('Saved {}'.format(path), Qgis.MessageLevel.Success)
            except IOError as e:
                self._message(str(e), Qgis.MessageLevel.Critical)

    def export_depth(self):
        if self.result is None:
            return
        path = self._ask_path('Export water depth', 'GeoTIFF (*.tif)', 'water_depth.tif')
        if path:
            QgsProject.instance().addMapLayer(outputs.depth_raster(self.result, path))
            self._message('Saved {}'.format(path), Qgis.MessageLevel.Success)

    def export_chart(self):
        if not HAS_MPL or self.result is None:
            return
        chart = self.profile_chart if self.chart_tabs.currentIndex() == 1 else self.curve_chart
        name = 'line_profile.png' if chart is self.profile_chart else 'area_volume.png'
        path = self._ask_path('Save chart', 'PNG image (*.png)', name)
        if path:
            chart.save_png(path)

    def copy_table(self):
        if self.result is not None:
            QGuiApplication.clipboard().setText(outputs.table_text(self.result))
            self._status('Table copied to the clipboard.')

    # --------------------------------------------------------------- misc
    def _status(self, text):
        self.status_lbl.setText(text)

    def _message(self, text, level=Qgis.MessageLevel.Info):
        self.iface.messageBar().pushMessage('Reservoir Creator', text, level=level, duration=6)
        self._status(text)

    def cleanup(self):
        """Remove every canvas item (plugin unload)."""
        self.scroll_timer.stop()
        if self.task is not None:
            self.task.cancel()
        if self.canvas.mapTool() is self.tool:
            self.canvas.unsetMapTool(self.tool)
        try:
            self.canvas.mapToolSet.disconnect(self._map_tool_changed)
        except TypeError:
            pass
        self._clear_overlays()
        if self.line_band is not None:
            self.canvas.scene().removeItem(self.line_band)
            self.line_band = None
        # release canvas-bound helpers while the canvas still exists
        self.tool.release()
        self.tool.deleteLater()
        self.tool = None
