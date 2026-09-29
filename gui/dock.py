# -*- coding: utf-8 -*-
"""The Reservoir Creator dock panel."""

import math
import os

from qgis.core import (Qgis, QgsApplication, QgsCoordinateTransform, QgsDistanceArea,
                       QgsGeometry, QgsMapLayerProxyModel, QgsPointXY, QgsProject,
                       QgsRasterLayer, QgsSettings, QgsWkbTypes)
from qgis.gui import (QgsCollapsibleGroupBox, QgsDockWidget, QgsDoubleSpinBox,
                      QgsMapLayerComboBox, QgsRubberBand, QgsVertexMarker)
from qgis.PyQt.QtCore import Qt, QTimer, QUrl
from qgis.PyQt.QtGui import QColor, QDesktopServices, QFont, QGuiApplication, QIcon
from qgis.PyQt.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFileDialog,
                                 QFormLayout, QFrame, QHBoxLayout, QHeaderView, QLabel,
                                 QMenu, QProgressBar, QPushButton, QScrollArea,
                                 QSlider, QTableWidget,
                                 QTableWidgetItem, QTabWidget, QToolButton, QVBoxLayout,
                                 QWidget)

from ..core import dem_sources, hydro
from ..core.analysis import AnalysisParams, Note
from . import outputs, theme
from .map_tools import DamAxisTool
from .task import ReservoirTask
from .widgets import (Banner, Card, Segmented, TileGrid, hint, primary_button,
                      scaled_font, stylesheet)

try:
    from .charts import CapacityChart, SectionChart, SizingChart
    HAS_MPL = True
except Exception:  # pragma: no cover - matplotlib missing
    HAS_MPL = False

SETTINGS = 'ReservoirCreator/'
HELP_URL = 'https://github.com/gurbuzf/reservoir_creator#readme'
AUTO = -9999.0       # sentinel minimum of optional spin boxes
RIGHT_ALIGN = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter


def _icon(name):
    return QgsApplication.getThemeIcon(name)


def _layer_filter(name):
    enum = getattr(Qgis, 'LayerFilter', None)
    if enum is not None:
        return getattr(enum, name)
    return getattr(QgsMapLayerProxyModel.Filter, name)


def optional_spin(minimum, maximum, decimals=1, suffix=' m', special='Auto', step=1.0):
    """Spin box whose minimum shows ``special`` and means "not set"."""
    sb = QgsDoubleSpinBox()
    sb.setDecimals(decimals)
    sb.setRange(AUTO, maximum)
    sb.setSingleStep(step)
    sb.setSuffix(suffix)
    sb.setSpecialValueText(special)
    sb.setShowClearButton(True)
    sb.setClearValue(AUTO)
    sb.setValue(AUTO)
    sb.setProperty('rc_min', minimum)
    return sb


def optional_value(sb):
    v = sb.value()
    return None if v <= AUTO + 1e-9 else float(v)


def spin(value, minimum, maximum, decimals=1, suffix=' m', step=1.0):
    sb = QgsDoubleSpinBox()
    sb.setDecimals(decimals)
    sb.setRange(minimum, maximum)
    sb.setSingleStep(step)
    sb.setSuffix(suffix)
    sb.setValue(value)
    sb.setShowClearButton(True)
    sb.setClearValue(value)
    return sb


class ReservoirDock(QgsDockWidget):
    """Dockable panel: set-up on the first tab, interactive results on the second."""

    def __init__(self, iface, plugin_dir, parent=None):
        super().__init__('Reservoir Creator', parent)
        self.setObjectName('ReservoirCreatorDock')
        self.iface = iface
        self.canvas = iface.mapCanvas()
        self.plugin_dir = plugin_dir
        self.model = None
        self.task = None
        self.stats = None
        self.axis_geom = None          # QgsGeometry of the drawn axis
        self.axis_crs = None
        self.axis_band = None
        self.water_band = None
        self.pour_marker = None
        self._updating = False
        self._last_upstream = 'auto'

        self.tool = DamAxisTool(self.canvas, theme.LIGHT['dam'])
        self.tool.axisCompleted.connect(self._axis_drawn)
        self.tool.status.connect(self._status)
        self.canvas.mapToolSet.connect(self._map_tool_changed)

        self.heavy_timer = QTimer(self)
        self.heavy_timer.setSingleShot(True)
        self.heavy_timer.setInterval(160)
        self.heavy_timer.timeout.connect(self._update_polygon)

        self._build()
        self._load_settings()
        self.visibilityChanged.connect(self._visibility_changed)

    # =====================================================================
    # UI construction
    # =====================================================================
    def _build(self):
        root = QWidget()
        root.setStyleSheet(stylesheet(root))
        v = QVBoxLayout(root)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(8)

        # header
        head = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(QIcon(os.path.join(self.plugin_dir, 'icons', 'icon.svg')).pixmap(30, 30))
        head.addWidget(logo, 0, Qt.AlignmentFlag.AlignTop)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        t = QLabel('Reservoir Creator')
        t.setFont(scaled_font(t, 1.35, QFont.Weight.DemiBold))
        s = hint('Elevation–area–capacity of a dam site from a DEM')
        titles.addWidget(t)
        titles.addWidget(s)
        head.addLayout(titles, 1)
        help_btn = QToolButton()
        help_btn.setIcon(_icon('/mActionHelpContents.svg'))
        help_btn.setToolTip('Open the documentation')
        help_btn.setAutoRaise(True)
        help_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(HELP_URL)))
        head.addWidget(help_btn, 0, Qt.AlignmentFlag.AlignTop)
        v.addLayout(head)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.addTab(self._build_setup(), _icon('/propertyicons/settings.svg'), 'Setup')
        self.tabs.addTab(self._build_results(), _icon('/mActionShowRasterCalculator.svg'),
                         'Results')
        self.tabs.setTabEnabled(1, False)
        v.addWidget(self.tabs, 1)

        # run bar (always visible)
        bar = QHBoxLayout()
        self.run_btn = primary_button('Run analysis')
        self.run_btn.setIcon(_icon('/mActionStart.svg'))
        self.run_btn.clicked.connect(self.run)
        self.cancel_btn = QPushButton('Cancel')
        self.cancel_btn.setVisible(False)
        self.cancel_btn.clicked.connect(self.cancel)
        bar.addWidget(self.run_btn, 1)
        bar.addWidget(self.cancel_btn)
        v.addLayout(bar)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setTextVisible(False)
        self.progress.setMaximumHeight(6)
        self.progress.setVisible(False)
        v.addWidget(self.progress)
        self.status_lbl = hint('Draw a dam axis across a valley to begin.')
        v.addWidget(self.status_lbl)

        self.setWidget(root)
        self.setMinimumWidth(360)

    def _scroll(self, inner):
        for combo in inner.findChildren(QComboBox):
            combo.setSizeAdjustPolicy(
                QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(12)
        area = QScrollArea()
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setWidget(inner)
        return area

    # -- set-up tab -----------------------------------------------------------
    def _build_setup(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 6, 4, 6)
        v.setSpacing(10)

        # 1. dam axis
        c1 = Card('1 · Dam axis', 'The line across the valley where the dam would stand.')
        self.axis_mode = Segmented(['Draw on map', 'From layer'],
                                   [_icon('/mActionCaptureLine.svg'),
                                    _icon('/mIconLineLayer.svg')])
        self.axis_mode.changed.connect(self._axis_mode_changed)
        c1.body.addWidget(self.axis_mode)
        draw_page = QWidget()
        dl = QVBoxLayout(draw_page)
        dl.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self.draw_btn = QPushButton('Draw dam axis')
        self.draw_btn.setIcon(_icon('/mActionCaptureLine.svg'))
        self.draw_btn.setCheckable(True)
        self.draw_btn.toggled.connect(self._draw_toggled)
        self.clear_btn = QPushButton('Clear')
        self.clear_btn.setIcon(_icon('/mActionDeleteSelected.svg'))
        self.clear_btn.clicked.connect(self.clear_axis)
        row.addWidget(self.draw_btn, 1)
        row.addWidget(self.clear_btn)
        dl.addLayout(row)
        dl.addWidget(hint('Click from one abutment to the other, right-click to finish. '
                          'Backspace removes the last vertex, Esc cancels. Snapping follows '
                          'the project settings.'))
        layer_page = QWidget()
        ll = QVBoxLayout(layer_page)
        ll.setContentsMargins(0, 0, 0, 0)
        self.line_combo = QgsMapLayerComboBox()
        self.line_combo.setFilters(_layer_filter('LineLayer'))
        self.line_combo.setAllowEmptyLayer(True)
        self.line_combo.layerChanged.connect(self._layer_axis_changed)
        self.selected_only = QCheckBox('Use the selected feature')
        self.selected_only.toggled.connect(self._layer_axis_changed)
        ll.addWidget(self.line_combo)
        ll.addWidget(self.selected_only)
        ll.addWidget(hint('The first (or selected) line feature is used as the dam axis.'))
        self.axis_pages = (draw_page, layer_page)
        for pg in self.axis_pages:
            c1.body.addWidget(pg)
        self.axis_info = QLabel('No dam axis yet.')
        self.axis_info.setObjectName('rcHint')
        c1.body.addWidget(self.axis_info)
        self.auto_run = QCheckBox('Run automatically when the axis is drawn')
        c1.body.addWidget(self.auto_run)
        v.addWidget(c1)

        # 2. elevation data
        c2 = Card('2 · Elevation data')
        self.dem_mode = Segmented(['Project layer', 'Download'],
                                  [_icon('/mIconRaster.svg'), _icon('/mActionAddWcsLayer.svg')])
        self.dem_mode.changed.connect(self._dem_mode_changed)
        c2.body.addWidget(self.dem_mode)
        p1 = QWidget()
        l1 = QVBoxLayout(p1)
        l1.setContentsMargins(0, 0, 0, 0)
        self.dem_combo = QgsMapLayerComboBox()
        self.dem_combo.setFilters(_layer_filter('RasterLayer'))
        self.dem_combo.setAllowEmptyLayer(True)
        l1.addWidget(self.dem_combo)
        l1.addWidget(hint('Use a bare-earth DTM for best results. Elevations in metres.'))
        p2 = QWidget()
        l2 = QVBoxLayout(p2)
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
        self.dem_pages = (p1, p2)
        for pg in self.dem_pages:
            c2.body.addWidget(pg)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.radius = spin(15.0, 1.0, 150.0, 1, ' km', 1.0)
        self.radius.setToolTip('Area analysed around the dam axis. Increase it if the '
                               'reservoir reaches the edge.')
        form.addRow('Analysis radius', self.radius)
        c2.body.addLayout(form)
        v.addWidget(c2)

        # 3. reservoir and dam
        c3 = Card('3 · Reservoir & dam')
        f3 = QFormLayout()
        f3.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.upstream = QComboBox()
        self.upstream.addItem('Auto-detect', 'auto')
        self.upstream.addItem('Left of the drawn line', 'left')
        self.upstream.addItem('Right of the drawn line', 'right')
        self.upstream.setToolTip('Side of the dam axis where the reservoir forms, relative to '
                                 'the direction in which the axis was drawn.')
        f3.addRow('Upstream side', self.upstream)
        self.nwl = optional_spin(-500, 9000)
        self.nwl.setToolTip('Normal (full supply) water level. Auto = maximum impoundable '
                            'level minus freeboard.')
        f3.addRow('Normal water level', self.nwl)
        self.mol = optional_spin(-500, 9000, special='None')
        self.mol.setToolTip('Minimum operating level: storage below it is dead storage.')
        f3.addRow('Min. operating level', self.mol)
        self.max_level = optional_spin(-500, 9000)
        self.max_level.setToolTip('Upper limit of the analysis. Auto = the level at which water '
                                  'would bypass the dam.')
        f3.addRow('Max. level to analyse', self.max_level)
        self.freeboard = spin(3.0, 0.0, 50.0, 1, ' m', 0.5)
        self.freeboard.setToolTip('Crest level = normal water level + freeboard.')
        f3.addRow('Freeboard', self.freeboard)
        self.step = optional_spin(0.01, 100, 2)
        self.step.setToolTip('Level increment of the table. Auto gives about 120 rows.')
        f3.addRow('Table step', self.step)
        c3.body.addLayout(f3)

        emb = QgsCollapsibleGroupBox('Embankment (fill estimate)')
        emb.setCollapsed(True)
        fe = QFormLayout(emb)
        self.crest_width = spin(10.0, 0.0, 100.0, 1, ' m', 1.0)
        self.slope_us = spin(3.0, 0.0, 10.0, 2, ' H:1V', 0.25)
        self.slope_ds = spin(2.5, 0.0, 10.0, 2, ' H:1V', 0.25)
        fe.addRow('Crest width', self.crest_width)
        fe.addRow('Upstream slope', self.slope_us)
        fe.addRow('Downstream slope', self.slope_ds)
        fe.addRow(hint('Trapezoidal section; foundation excavation is ignored.'))
        c3.body.addWidget(emb)

        hyd = QgsCollapsibleGroupBox('Hydrology (optional)')
        hyd.setCollapsed(True)
        fh = QFormLayout(hyd)
        self.inflow = optional_spin(0, 1e6, 2, ' m³/s', 'None', 1.0)
        self.inflow.setToolTip('Mean annual inflow. Enables residence time, capacity/inflow '
                               'ratio and sediment trap efficiency (Brune).')
        fh.addRow('Mean inflow', self.inflow)
        c3.body.addWidget(hyd)
        v.addWidget(c3)
        v.addStretch(1)
        self._source_changed()
        return self._scroll(page)

    # -- results tab ----------------------------------------------------------
    def _build_results(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 6, 4, 6)
        v.setSpacing(10)

        self.banner_box = QVBoxLayout()
        self.banner_box.setSpacing(4)
        v.addLayout(self.banner_box)

        # hero + level control
        card = Card('Water level')
        hero = QHBoxLayout()
        hv = QVBoxLayout()
        hv.setSpacing(0)
        self.hero_value = QLabel('–')
        self.hero_value.setFont(scaled_font(self, 2.4, QFont.Weight.DemiBold))
        self.hero_caption = hint('gross storage')
        hv.addWidget(self.hero_value)
        hv.addWidget(self.hero_caption)
        hero.addLayout(hv, 1)
        lv = QVBoxLayout()
        self.level_spin = QgsDoubleSpinBox()
        self.level_spin.setDecimals(2)
        self.level_spin.setSuffix(' m')
        self.level_spin.setSingleStep(0.5)
        self.level_spin.setMinimumWidth(110)
        self.level_spin.valueChanged.connect(self._spin_changed)
        self.reset_level = QToolButton()
        self.reset_level.setText('Reset')
        self.reset_level.setToolTip('Back to the suggested normal water level')
        self.reset_level.clicked.connect(self._reset_level)
        r = QHBoxLayout()
        r.addWidget(self.level_spin)
        r.addWidget(self.reset_level)
        lv.addLayout(r)
        hero.addLayout(lv)
        card.body.addLayout(hero)
        self.level_slider = QSlider(Qt.Orientation.Horizontal)
        self.level_slider.valueChanged.connect(self._slider_changed)
        card.body.addWidget(self.level_slider)
        rng = QHBoxLayout()
        self.range_lo = hint('')
        self.range_hi = hint('')
        self.range_hi.setAlignment(Qt.AlignmentFlag.AlignRight)
        rng.addWidget(self.range_lo)
        rng.addWidget(self.range_hi)
        card.body.addLayout(rng)
        v.addWidget(card)

        # tiles
        self.tiles = TileGrid(3)
        tt = self.tiles
        tt.add('area', 'Surface area', 'km²')
        tt.add('mean_depth', 'Mean depth', 'm', 'Storage ÷ surface area')
        tt.add('max_depth', 'Max. depth', 'm')
        tt.add('length', 'Reservoir length', 'km',
               'Longest path from the dam through the water body')
        tt.add('shore', 'Shoreline', 'km')
        tt.add('sdi', 'Shoreline index', '',
               'Shoreline development index P / (2√(πA)); 1 = circular lake')
        tt.add('crest', 'Crest level', 'm', 'Normal water level + freeboard')
        tt.add('height', 'Dam height', 'm', 'Crest level − lowest ground on the axis')
        tt.add('crest_len', 'Crest length', 'm')
        tt.add('fill', 'Embankment fill', 'hm³', 'Indicative trapezoidal embankment volume')
        tt.add('ratio', 'Storage : fill', ': 1',
               'Water-to-fill ratio - a screening indicator of site efficiency')
        tt.add('max_level', 'Max. impoundable', 'm',
               'Above this level water escapes around the dam / over a saddle')
        tt.add('dead', 'Dead storage', 'hm³', 'Storage below the minimum operating level')
        tt.add('live', 'Live storage', 'hm³', 'Storage between the MOL and the NWL')
        tt.add('bed', 'River bed at dam', 'm')
        tt.add('residence', 'Residence time', 'days', 'Storage ÷ mean inflow')
        tt.add('ci', 'Capacity / inflow', 'yr', 'Storage ÷ mean annual inflow volume (degree of regulation)')
        tt.add('trap', 'Trap efficiency', '%', 'Brune median curve (Dendy, 1974)')
        v.addWidget(self.tiles)

        # charts
        self.chart_tabs = QTabWidget()
        self.chart_tabs.setDocumentMode(True)
        if HAS_MPL:
            self.cap_chart = CapacityChart()
            self.sec_chart = SectionChart()
            self.size_chart = SizingChart()
            for ch in (self.cap_chart, self.sec_chart, self.size_chart):
                ch.levelPicked.connect(self._picked)
            self.chart_tabs.addTab(self._chart_page(self.cap_chart), 'Area–capacity')
            self.chart_tabs.addTab(self._chart_page(self.sec_chart), 'Dam axis')
            self.chart_tabs.addTab(self._chart_page(self.size_chart), 'Dam sizing')
        else:
            self.cap_chart = self.sec_chart = self.size_chart = None
            self.chart_tabs.addTab(hint('Install matplotlib to see charts.'), 'Charts')
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(['Water level (m)', 'Area (km²)', 'Storage (hm³)'])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.cellClicked.connect(lambda r, _c: self._picked(
            float(self.table.item(r, 0).data(Qt.ItemDataRole.UserRole))))
        tpage = QWidget()
        tl = QVBoxLayout(tpage)
        tl.setContentsMargins(0, 4, 0, 0)
        tl.addWidget(self.table)
        trow = QHBoxLayout()
        copy = QPushButton('Copy')
        copy.setIcon(_icon('/mActionEditCopy.svg'))
        copy.clicked.connect(self.copy_table)
        csvb = QPushButton('Export CSV…')
        csvb.setIcon(_icon('/mActionFileSave.svg'))
        csvb.clicked.connect(self.export_csv)
        trow.addWidget(copy)
        trow.addWidget(csvb)
        trow.addStretch(1)
        tl.addLayout(trow)
        self.table.setMinimumHeight(300)
        self.chart_tabs.addTab(tpage, 'Table')
        v.addWidget(self.chart_tabs)

        # actions
        act = QHBoxLayout()
        add = QPushButton('Add to map')
        add.setIcon(_icon('/mActionAddLayer.svg'))
        add.setToolTip('Add the reservoir outline, dam axis and water depth at the current '
                       'level as layers')
        add.clicked.connect(self.add_to_map)
        zoom = QToolButton()
        zoom.setIcon(_icon('/mActionZoomToLayer.svg'))
        zoom.setToolTip('Zoom to the reservoir')
        zoom.clicked.connect(self.zoom_to_reservoir)
        export = QToolButton()
        export.setText('Export')
        export.setIcon(_icon('/mActionSharingExport.svg'))
        export.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        export.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(export)
        for text, slot in (('GeoPackage (outline, axis, table)…', self.export_gpkg),
                           ('Water depth raster (GeoTIFF)…', self.export_depth),
                           ('Elevation–area–capacity table (CSV)…', self.export_csv),
                           ('Current chart (PNG)…', self.export_chart)):
            menu.addAction(text).triggered.connect(slot)
        export.setMenu(menu)
        flip = QToolButton()
        flip.setText('Flip upstream')
        flip.setIcon(_icon('/mActionReverseLine.svg'))
        flip.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        flip.setToolTip('Re-run with the reservoir on the other side of the dam axis')
        flip.clicked.connect(self.flip_upstream)
        act.addWidget(add, 1)
        act.addWidget(export)
        act.addWidget(flip)
        act.addWidget(zoom)
        v.addLayout(act)
        v.addStretch(1)
        return self._scroll(page)

    def _chart_page(self, chart):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.addWidget(chart)
        return w

    # =====================================================================
    # Settings
    # =====================================================================
    def _load_settings(self):
        s = QgsSettings()
        g = lambda k, d, t=float: s.value(SETTINGS + k, d, type=t)  # noqa: E731
        self.axis_mode.set_index(g('axis_mode', 0, int))
        self.dem_mode.set_index(g('dem_mode', 0, int))
        idx = self.source_combo.findData(g('source', 'gedtm30', str))
        self.source_combo.setCurrentIndex(max(0, idx))
        self.radius.setValue(g('radius_km', 15.0))
        self.freeboard.setValue(g('freeboard', 3.0))
        self.crest_width.setValue(g('crest_width', 10.0))
        self.slope_us.setValue(g('slope_us', 3.0))
        self.slope_ds.setValue(g('slope_ds', 2.5))
        self.auto_run.setChecked(g('auto_run', True, bool))
        self.add_dem.setChecked(g('add_dem', False, bool))
        dem_id = g('dem_layer', '', str)
        lyr = QgsProject.instance().mapLayer(dem_id) if dem_id else None
        if lyr is not None:
            self.dem_combo.setLayer(lyr)

    def _save_settings(self):
        s = QgsSettings()
        s.setValue(SETTINGS + 'axis_mode', self.axis_mode.index())
        s.setValue(SETTINGS + 'dem_mode', self.dem_mode.index())
        s.setValue(SETTINGS + 'source', self.source_combo.currentData())
        s.setValue(SETTINGS + 'radius_km', self.radius.value())
        s.setValue(SETTINGS + 'freeboard', self.freeboard.value())
        s.setValue(SETTINGS + 'crest_width', self.crest_width.value())
        s.setValue(SETTINGS + 'slope_us', self.slope_us.value())
        s.setValue(SETTINGS + 'slope_ds', self.slope_ds.value())
        s.setValue(SETTINGS + 'auto_run', self.auto_run.isChecked())
        s.setValue(SETTINGS + 'add_dem', self.add_dem.isChecked())
        lyr = self.dem_combo.currentLayer()
        s.setValue(SETTINGS + 'dem_layer', lyr.id() if lyr else '')

    # =====================================================================
    # Dam axis
    # =====================================================================
    @staticmethod
    def _stack_to(pages, i):
        for k, page in enumerate(pages):
            page.setVisible(k == i)

    def _axis_mode_changed(self, i):
        self._stack_to(self.axis_pages, i)
        if i == 1:
            self.draw_btn.setChecked(False)
            self._layer_axis_changed()
        else:
            self._show_axis()

    def _draw_toggled(self, on):
        if on:
            if self.canvas.mapTool() is not self.tool:
                self.canvas.setMapTool(self.tool)
            self._status('Click across the valley to draw the dam axis.')
        elif self.canvas.mapTool() is self.tool:
            self.canvas.unsetMapTool(self.tool)

    def _map_tool_changed(self, new, _old=None):
        if new is not self.tool and self.draw_btn.isChecked():
            self.draw_btn.blockSignals(True)
            self.draw_btn.setChecked(False)
            self.draw_btn.blockSignals(False)

    def activate_drawing(self):
        """Called when the dock opens: start drawing straight away."""
        if self.axis_mode.index() == 0 and self.axis_geom is None:
            self.draw_btn.setChecked(True)

    def _axis_drawn(self, geom):
        self.axis_geom = geom
        self.axis_crs = self.canvas.mapSettings().destinationCrs()
        self.draw_btn.setChecked(False)
        self._show_axis()
        if self.auto_run.isChecked() and self._dem_ready():
            self.run()
        elif not self._dem_ready():
            self._status('Dam axis drawn. Choose the elevation data and press Run.')

    def clear_axis(self):
        self.axis_geom = None
        self.axis_crs = None
        self._show_axis()
        self._clear_results_overlay()

    def _layer_axis_changed(self, *_args):
        self._show_axis()

    def _current_axis(self):
        """(list of (x, y), QgsCoordinateReferenceSystem) or (None, None)."""
        if self.axis_mode.index() == 0:
            if self.axis_geom is None:
                return None, None
            return self._polyline(self.axis_geom), self.axis_crs
        lyr = self.line_combo.currentLayer()
        if lyr is None:
            return None, None
        feats = lyr.selectedFeatures() if self.selected_only.isChecked() else []
        if not feats:
            feats = [f for _, f in zip(range(1), lyr.getFeatures())]
        if not feats:
            return None, None
        return self._polyline(feats[0].geometry()), lyr.crs()

    @staticmethod
    def _polyline(geom):
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

    def _show_axis(self):
        pts, crs = self._current_axis()
        if self.axis_band is not None:
            self.canvas.scene().removeItem(self.axis_band)
            self.axis_band = None
        if not pts:
            self.axis_info.setText('No dam axis yet.')
            return
        self.axis_band = QgsRubberBand(self.canvas, Qgis.GeometryType.Line)
        self.axis_band.setColor(QColor(theme.LIGHT['dam']))
        self.axis_band.setWidth(4)
        geom = QgsGeometry.fromPolylineXY([QgsPointXY(x, y) for x, y in pts])
        self.axis_band.setToGeometry(geom, crs)
        length = self._geodesic_length(geom, crs)
        self.axis_info.setText('✔ Dam axis: {:,.0f} m, {} vertices ({})'.format(
            length, len(pts), crs.authid() or 'custom CRS'))

    @staticmethod
    def _geodesic_length(geom, crs):
        d = QgsDistanceArea()
        d.setSourceCrs(crs, QgsProject.instance().transformContext())
        d.setEllipsoid(QgsProject.instance().ellipsoid() or 'WGS84')
        return d.measureLength(geom)

    # =====================================================================
    # Elevation data
    # =====================================================================
    def _dem_mode_changed(self, i):
        self._stack_to(self.dem_pages, i)

    def _source_changed(self, *_):
        src = dem_sources.SOURCES_BY_KEY[self.source_combo.currentData()]
        self.source_hint.setText('{} Licence: {}. Only the area around the dam is '
                                 'downloaded.'.format(src.description, src.license))
        self.source_hint.setToolTip(src.citation)

    def _dem_ready(self):
        return self.dem_mode.index() == 1 or self.dem_combo.currentLayer() is not None

    # =====================================================================
    # Running
    # =====================================================================
    def _collect_params(self, upstream=None):
        pts, crs = self._current_axis()
        if not pts:
            raise ValueError('Draw a dam axis or choose a line layer first.')
        download = None
        dem_path = None
        if self.dem_mode.index() == 0:
            lyr = self.dem_combo.currentLayer()
            if lyr is None:
                raise ValueError('Choose a DEM layer, or switch to "Download".')
            if lyr.providerType() != 'gdal':
                raise ValueError('The DEM must be a file-based raster (GDAL provider).')
            dem_path = lyr.source()
        else:
            download = self.source_combo.currentData()
        up = upstream or self.upstream.currentData()
        params = AnalysisParams(
            dem_path, pts, crs.toWkt(),
            radius_m=self.radius.value() * 1000.0, upstream=up,
            max_level=optional_value(self.max_level), step=optional_value(self.step),
            nwl=optional_value(self.nwl), mol=optional_value(self.mol),
            freeboard=self.freeboard.value(), crest_width=self.crest_width.value(),
            slope_us=self.slope_us.value(), slope_ds=self.slope_ds.value(),
            inflow_m3s=optional_value(self.inflow))
        if params.dem_path is None:
            params.dem_path = ''
        return params, download

    def run(self, upstream=None):
        if self.task is not None:
            return
        try:
            params, download = self._collect_params(upstream if isinstance(upstream, str) else None)
        except ValueError as e:
            self._message(str(e), Qgis.MessageLevel.Warning)
            return
        self._save_settings()
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
        if task.model is None:
            self._status(task.error or 'The analysis failed.')
            if task.error and task.error != 'Cancelled.':
                self._message(task.error, Qgis.MessageLevel.Critical)
            return
        if task.downloaded_path and self.add_dem.isChecked():
            src = dem_sources.SOURCES_BY_KEY[task.download_source]
            lyr = QgsRasterLayer(task.downloaded_path, '{} (download)'.format(src.short))
            if lyr.isValid():
                QgsProject.instance().addMapLayer(lyr)
        self.model = task.model
        self.model.notes[:0] = [Note(Note.INFO, n) for n in task.download_notes]
        if task.download_source:
            src = dem_sources.SOURCES_BY_KEY[task.download_source]
            self.model.notes.append(Note(Note.INFO, 'Elevation data: {} ({}).'.format(
                src.short, src.license)))
            if src.kind == 'DSM':
                self.model.notes.append(Note(
                    Note.WARNING, 'Copernicus GLO-30 is a surface model: forest canopy and '
                    'buildings raise the valley floor, so storage may be underestimated.'))
        self._show_results()
        self._status('Reservoir computed: bed {:.1f} m, maximum impoundable level {:.1f} m.'
                     .format(self.model.bed_level, self.model.max_level))

    def flip_upstream(self):
        if self.model is None:
            return
        self.run('right' if self.model.upstream_side == 'left' else 'left')

    # =====================================================================
    # Results
    # =====================================================================
    def _show_results(self):
        m = self.model
        # banners
        while self.banner_box.count():
            w = self.banner_box.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        for n in m.notes:
            self.banner_box.addWidget(Banner(n.level, n.text))

        # level controls
        self._updating = True
        lo, hi = m.bed_level, m.max_level
        self.level_spin.setRange(lo, hi)
        self.level_slider.setRange(int(math.floor(lo * 100)), int(math.ceil(hi * 100)))
        self.range_lo.setText('River bed {:.1f} m'.format(lo))
        self.range_hi.setText('Max. {:.1f} m'.format(hi))
        self._updating = False

        # table
        lv, a, v = m.curve()
        self.table.setRowCount(len(lv))
        for i, (h, aa, vv) in enumerate(zip(lv, a, v)):
            for j, text in enumerate(('{:.2f}'.format(h), theme.fmt_sig(aa / 1e6, 4),
                                      theme.fmt_sig(vv / 1e6, 5))):
                it = QTableWidgetItem(text)
                it.setTextAlignment(RIGHT_ALIGN)
                it.setData(Qt.ItemDataRole.UserRole, float(h))
                self.table.setItem(i, j, it)

        # optional tiles
        p = m.params
        has_mol = p.mol is not None and p.mol > m.bed_level
        for k in ('dead', 'live'):
            self.tiles.set_visible(k, has_mol)
        for k in ('residence', 'ci', 'trap'):
            self.tiles.set_visible(k, bool(p.inflow_m3s))
        self.tiles.set('max_level', theme.fmt(m.max_level, 1))
        self.tiles.set('bed', theme.fmt(m.thalweg[2], 1))

        # charts
        if HAS_MPL:
            self.cap_chart.set_data(lv, a, v, m.default_nwl, m.max_level, m.bed_level, p.mol)
            self.size_chart.set_data(m.sizing(), m.default_nwl, p.freeboard)

        self._show_pour_point()
        self.tabs.setTabEnabled(1, True)
        self.tabs.setCurrentIndex(1)
        self.set_level(m.default_nwl)

    def set_level(self, level):
        """Set the water level from any control (slider, spin box, charts)."""
        if self.model is None:
            return
        level = self.model.clamp_level(level)
        self._updating = True
        self.level_spin.setValue(level)
        self.level_slider.setValue(int(round(level * 100)))
        self._updating = False
        self._apply_level(level)

    def _spin_changed(self, value):
        if not self._updating:
            self._updating = True
            self.level_slider.setValue(int(round(value * 100)))
            self._updating = False
            self._apply_level(value)

    def _slider_changed(self, value):
        if not self._updating:
            self._updating = True
            self.level_spin.setValue(value / 100.0)
            self._updating = False
            self._apply_level(value / 100.0)

    def _picked(self, level):
        self.set_level(level)

    def _reset_level(self):
        if self.model is not None:
            self.set_level(self.model.default_nwl)

    def _apply_level(self, level):
        m = self.model
        if m is None:
            return
        level = m.clamp_level(level)
        s = m.stats(level, with_polygon=False)
        self.stats = s
        tt = self.tiles
        self.hero_value.setText('{} hm³'.format(theme.fmt_sig(s['volume_m3'] / 1e6, 4)))
        self.hero_caption.setText('gross storage at {:.2f} m · {} km² surface'.format(
            level, theme.fmt_sig(s['area_m2'] / 1e6, 3)))
        tt.set('area', theme.fmt_sig(s['area_m2'] / 1e6, 3))
        tt.set('mean_depth', theme.fmt(s['mean_depth'], 1))
        tt.set('max_depth', theme.fmt(s['max_depth'], 1))
        tt.set('length', theme.fmt(s['length_m'] / 1e3, 2))
        tt.set('crest', theme.fmt(s['crest_level'], 1))
        tt.set('height', theme.fmt(s['dam_height'], 1))
        tt.set('crest_len', '{:,.0f}'.format(s['crest_length']) + (' ⚠' if s['axis_too_short'] else ''))
        tt.set('fill', theme.fmt_sig(s['fill_m3'] / 1e6, 3))
        tt.set('ratio', theme.fmt(s['storage_fill_ratio'], 1))
        if 'dead_m3' in s:
            tt.set('dead', theme.fmt_sig(s['dead_m3'] / 1e6, 3))
            tt.set('live', theme.fmt_sig(s['live_m3'] / 1e6, 3))
        if 'trap_eff' in s:
            tt.set('residence', theme.fmt(s['residence_days'], 1))
            tt.set('ci', theme.fmt(s['ci_ratio'], 3))
            tt.set('trap', theme.fmt(s['trap_eff'], 0))
        tt.tiles['crest_len'].setToolTip(
            'The crest is above the ground at an end of the drawn axis - extend the axis.'
            if s['axis_too_short'] else '')
        if HAS_MPL:
            self.cap_chart.set_nwl(level)
            self.size_chart.set_nwl(level)
            dam = m.dam(level)
            self.sec_chart.set_data(m.stations, m.ground, level, dam['crest_level'], {
                'crest_length': dam['crest_length'], 'axis_too_short': dam['axis_too_short']})
        self.heavy_timer.start()

    def _update_polygon(self):
        """Debounced: vectorise the water surface, update the map and shoreline tiles."""
        m = self.model
        if m is None or self.stats is None:
            return
        level = self.stats['level']
        wkt, area, shore = m.polygon(level)
        self.stats['polygon_wkt'] = wkt
        self.stats['shoreline_m'] = shore
        self.stats['sdi'] = hydro.shoreline_development(shore, area) if area > 0 else float('nan')
        self.tiles.set('shore', theme.fmt(shore / 1e3, 1))
        self.tiles.set('sdi', theme.fmt(self.stats['sdi'], 2))
        if self.water_band is None:
            self.water_band = QgsRubberBand(self.canvas, Qgis.GeometryType.Polygon)
            c = QColor(theme.LIGHT['storage'])
            self.water_band.setStrokeColor(c)
            c.setAlpha(80)
            self.water_band.setFillColor(c)
            self.water_band.setWidth(1)
        if wkt:
            self.water_band.setToGeometry(QgsGeometry.fromWkt(wkt), outputs.model_crs(m))
        else:
            self.water_band.reset(Qgis.GeometryType.Polygon)

    def _show_pour_point(self):
        if self.pour_marker is not None:
            self.canvas.scene().removeItem(self.pour_marker)
            self.pour_marker = None
        m = self.model
        if m is None or m.pour_point is None or m.limit_reason not in (hydro.STOP_BYPASS,
                                                                      hydro.STOP_EDGE):
            return
        tr = QgsCoordinateTransform(outputs.model_crs(m), self.canvas.mapSettings().destinationCrs(),
                                    QgsProject.instance())
        pt = tr.transform(QgsPointXY(*m.pour_point))
        mk = QgsVertexMarker(self.canvas)
        mk.setCenter(pt)
        mk.setIconType(QgsVertexMarker.IconType.ICON_X)
        mk.setColor(QColor(theme.LIGHT['critical']))
        mk.setIconSize(14)
        mk.setPenWidth(3)
        mk.setToolTip('Spill point: water escapes here above {:.1f} m'.format(m.max_level))
        self.pour_marker = mk

    def _clear_results_overlay(self):
        for attr in ('water_band', 'pour_marker'):
            item = getattr(self, attr)
            if item is not None:
                self.canvas.scene().removeItem(item)
                setattr(self, attr, None)

    # =====================================================================
    # Outputs
    # =====================================================================
    def _full_stats(self):
        if self.model is None or self.stats is None:
            return None
        if 'polygon_wkt' not in self.stats:
            self._update_polygon()
        return self.stats

    def add_to_map(self):
        s = self._full_stats()
        if s is None:
            return
        outputs.add_to_project(self.model, s)
        self._message('Reservoir at {:.1f} m added to the project.'.format(s['level']),
                      Qgis.MessageLevel.Success)

    def zoom_to_reservoir(self):
        s = self._full_stats()
        if s is None or not s.get('polygon_wkt'):
            return
        geom = QgsGeometry.fromWkt(s['polygon_wkt'])
        tr = QgsCoordinateTransform(outputs.model_crs(self.model),
                                    self.canvas.mapSettings().destinationCrs(),
                                    QgsProject.instance())
        rect = tr.transformBoundingBox(geom.boundingBox())
        rect.scale(1.1)
        self.canvas.setExtent(rect)
        self.canvas.refresh()

    def _ask_path(self, title, filt, default):
        folder = QgsSettings().value(SETTINGS + 'last_dir', os.path.expanduser('~'), type=str)
        path, _ = QFileDialog.getSaveFileName(self, title, os.path.join(folder, default), filt)
        if path:
            QgsSettings().setValue(SETTINGS + 'last_dir', os.path.dirname(path))
        return path

    def _level_tag(self):
        return 'nwl_{:.1f}m'.format(self.stats['level']).replace('.', '_')

    def export_csv(self):
        if self.model is None:
            return
        path = self._ask_path('Export elevation–area–capacity table', 'CSV (*.csv)',
                              'reservoir_eac.csv')
        if path:
            outputs.write_csv(self.model, path)
            self._message('Table written to {}'.format(path), Qgis.MessageLevel.Success)

    def export_gpkg(self):
        s = self._full_stats()
        if s is None:
            return
        path = self._ask_path('Export to GeoPackage', 'GeoPackage (*.gpkg)',
                              'reservoir_{}.gpkg'.format(self._level_tag()))
        if path:
            try:
                outputs.write_geopackage(self.model, s, path)
                self._message('Written {}'.format(path), Qgis.MessageLevel.Success)
            except IOError as e:
                self._message(str(e), Qgis.MessageLevel.Critical)

    def export_depth(self):
        s = self._full_stats()
        if s is None:
            return
        path = self._ask_path('Export water depth raster', 'GeoTIFF (*.tif)',
                              'water_depth_{}.tif'.format(self._level_tag()))
        if path:
            lyr = outputs.depth_raster(self.model, s['level'], path)
            QgsProject.instance().addMapLayer(lyr)
            self._message('Written {}'.format(path), Qgis.MessageLevel.Success)

    def export_chart(self):
        if not HAS_MPL or self.model is None:
            return
        charts = [self.cap_chart, self.sec_chart, self.size_chart]
        i = self.chart_tabs.currentIndex()
        chart = charts[i] if i < len(charts) else charts[0]
        names = ['area_capacity', 'dam_axis', 'dam_sizing']
        path = self._ask_path('Save chart', 'PNG image (*.png)',
                              '{}.png'.format(names[charts.index(chart)]))
        if path:
            chart.save_png(path)

    def copy_table(self):
        if self.model is not None:
            QGuiApplication.clipboard().setText(outputs.table_text(self.model))
            self._status('Table copied to the clipboard (tab separated).')

    # =====================================================================
    # Misc
    # =====================================================================
    def _status(self, text):
        self.status_lbl.setText(text)

    def _message(self, text, level=Qgis.MessageLevel.Info):
        self.iface.messageBar().pushMessage('Reservoir Creator', text, level=level, duration=6)
        self._status(text)

    def _visibility_changed(self, visible):
        for item in (self.axis_band, self.water_band, self.pour_marker):
            if item is not None:
                item.setVisible(visible)
        if not visible and self.canvas.mapTool() is self.tool:
            self.canvas.unsetMapTool(self.tool)

    def cleanup(self):
        """Remove every canvas item and disconnect (plugin unload)."""
        if self.task is not None:
            self.task.cancel()
        if self.canvas.mapTool() is self.tool:
            self.canvas.unsetMapTool(self.tool)
        self.heavy_timer.stop()
        try:
            self.canvas.mapToolSet.disconnect(self._map_tool_changed)
        except TypeError:
            pass
        for item in (self.axis_band, self.water_band, self.pour_marker):
            if item is not None:
                self.canvas.scene().removeItem(item)
        self.axis_band = self.water_band = self.pour_marker = None
        # Release canvas-bound helpers now, while the canvas still exists: if Python
        # collected them after QGIS destroyed the canvas their destructors would crash.
        self.tool.release()
        self.tool.deleteLater()
        self.tool = None
