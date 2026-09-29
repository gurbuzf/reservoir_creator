# -*- coding: utf-8 -*-
"""The Reservoir Creator panel: draw a line, pick a DEM, get the reservoir."""

import os

from qgis.core import (Qgis, QgsApplication, QgsCoordinateTransform, QgsDistanceArea,
                       QgsGeometry, QgsMapLayerProxyModel, QgsPointXY, QgsProject,
                       QgsRasterLayer, QgsSettings, QgsWkbTypes)
from qgis.gui import QgsDockWidget, QgsMapLayerComboBox, QgsRubberBand, QgsVertexMarker
from qgis.PyQt.QtCore import QObject, Qt, QTimer, QUrl
from qgis.PyQt.QtGui import QColor, QDesktopServices, QFont, QGuiApplication, QIcon
from qgis.PyQt.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox,
                                 QDoubleSpinBox, QFileDialog, QFrame, QHBoxLayout,
                                 QHeaderView, QLabel, QMenu, QProgressBar, QScrollArea,
                                 QStackedWidget, QTableWidget, QTableWidgetItem, QTabWidget,
                                 QToolButton, QVBoxLayout, QWidget)

try:  # Qt6 (QGIS 4)
    from qgis.PyQt.QtGui import QActionGroup
except ImportError:  # Qt5 (QGIS 3)
    from qgis.PyQt.QtWidgets import QActionGroup

from ..core import analysis, dem_sources, terrain
from ..core.analysis import Note
from ..core.i18n import LANGUAGES, Msg, language, set_language, tr
from . import outputs, theme
from .map_tools import DamAxisTool
from .task import ReservoirTask
from .widgets import (Banner, Card, ResultHero, Segmented, hint, icon_button, pill_button,
                      primary_button, scaled_font, stylesheet)

try:
    from .charts import CurveChart, ProfileChart
    HAS_MPL = True
except Exception:  # pragma: no cover - matplotlib missing
    HAS_MPL = False

SETTINGS = 'ReservoirCreator/'
REPO_URL = 'https://github.com/gurbuzf/reservoir_creator'
HELP_URL = REPO_URL + '#readme'
ISSUES_URL = REPO_URL + '/issues'
RIGHT_ALIGN = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
LIMIT_LEVEL, LIMIT_DEPTH = 0, 1


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
        self.run_id = 0
        self.drawn_geom = None
        self.drawn_crs = None
        self.line_band = None
        self.water_band = None
        self.escape_marker = None
        self.root = None
        self._suggested = {}            # starting values for the limit, from the last result
        s = QgsSettings()
        self.theme_mode = s.value(SETTINGS + 'theme', 'auto', type=str)
        if self.theme_mode not in theme.MODES:
            self.theme_mode = 'auto'
        set_language(s.value(SETTINGS + 'language', 'en', type=str))

        self.tool = DamAxisTool(self.canvas, theme.LIGHT['dam'])
        self.tool.axisCompleted.connect(self._line_drawn)
        self.tool.status.connect(self._status)
        self.canvas.mapToolSet.connect(self._map_tool_changed)

        # owned by the panel, so it can never fire after the panel is deleted
        self.scroll_timer = QTimer(self)
        self.scroll_timer.setSingleShot(True)
        self.scroll_timer.setInterval(0)
        self.scroll_timer.timeout.connect(
            lambda: self.scroll.ensureWidgetVisible(self.results, 0, 0))

        self._build()
        self.topLevelChanged.connect(self._placement_changed)
        self._placement_changed(self.isFloating(), remember=False)
        self._load_settings()

    # ------------------------------------------------------------------ UI
    def _build(self):
        theme.set_mode(self.theme_mode)
        root = QWidget()
        root.setObjectName('rcRoot')
        root.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        root.setStyleSheet(stylesheet(root))
        self.root = root
        outer = QVBoxLayout(root)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(8)

        head = QHBoxLayout()
        head.setSpacing(8)
        logo = QLabel()
        logo.setPixmap(QIcon(os.path.join(self.plugin_dir, 'icons', 'icon.svg')).pixmap(36, 36))
        head.addWidget(logo, 0, Qt.AlignmentFlag.AlignVCenter)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        title = QLabel('Reservoir Creator')
        title.setFont(scaled_font(title, 1.4, QFont.Weight.Bold))
        titles.addWidget(title)
        sub = hint(tr('Draw a line across a valley, see the reservoir'))
        sub.setWordWrap(False)
        titles.addWidget(sub)
        head.addLayout(titles, 1)
        self.dock_btn = pill_button(tr('Dock'), _icon('/mDockify.svg'))
        self.dock_btn.clicked.connect(self.toggle_docked)
        head.addWidget(self.dock_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        reset_btn = icon_button(_icon('/mActionRefresh.svg'),
                                tr('Start over: clear the line and the results'))
        reset_btn.clicked.connect(self.reset)
        head.addWidget(reset_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        head.addWidget(self._settings_button(), 0, Qt.AlignmentFlag.AlignVCenter)
        outer.addLayout(head)
        outer.addSpacing(2)
        self.page_switch = Segmented([tr('Reservoir'), tr('References'), tr('Guide')])
        outer.addWidget(self.page_switch)

        page = QWidget()
        page.setObjectName('rcPage')
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 4, 0)
        v.setSpacing(12)
        v.addWidget(self._line_card())
        v.addWidget(self._dem_card())
        self.results = self._results_card()
        self.results.setVisible(False)
        v.addWidget(self.results)
        v.addStretch(1)
        self.scroll = QScrollArea()
        self.scroll.setObjectName('rcScroll')
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setWidget(page)
        self.scroll.viewport().setAutoFillBackground(False)
        self.pages = QStackedWidget()
        self.pages.addWidget(self.scroll)
        self.pages.addWidget(self._scroll_page(self._references_cards()))
        self.pages.addWidget(self._scroll_page(self._guide_cards()))
        self.page_switch.changed.connect(self._page_changed)
        outer.addWidget(self.pages, 1)

        self.action_bar = QWidget()
        bar = QHBoxLayout(self.action_bar)
        bar.setContentsMargins(0, 0, 0, 0)
        self.run_btn = primary_button(tr('Create reservoir'))
        self.run_btn.clicked.connect(lambda: self.run())
        self.cancel_btn = pill_button(tr('Cancel'), _icon('/mTaskCancel.svg'))
        self.cancel_btn.setToolTip(tr('Stop the download / calculation'))
        self.cancel_btn.setVisible(False)
        self.cancel_btn.clicked.connect(self.cancel)
        bar.addWidget(self.run_btn, 1)
        bar.addWidget(self.cancel_btn)
        outer.addWidget(self.action_bar)
        self.progress = QProgressBar()
        self.progress.setObjectName('rcProgress')
        self.progress.setRange(0, 100)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(4)
        self.progress.setVisible(False)
        outer.addWidget(self.progress)
        self.status_lbl = hint(tr('Draw a line across a valley to begin.'))
        outer.addWidget(self.status_lbl)

        for combo in page.findChildren(QComboBox):
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(10)
        old = self.widget()
        self.setWidget(root)
        if old is not None:     # silence the old widgets until Qt deletes them
            old.hide()
            for child in old.findChildren(QObject):
                child.blockSignals(True)
            old.blockSignals(True)
            old.deleteLater()
        self.setMinimumWidth(340)
        if HAS_MPL:     # the charts were drawn before they joined the themed panel
            self.curve_chart.refresh()
            self.profile_chart.refresh()

    # ------------------------------------------------ references and guide
    def _page_changed(self, i):
        self.pages.setCurrentIndex(i)
        self.action_bar.setVisible(i == 0)     # "Create reservoir" belongs to the analysis

    def _scroll_page(self, cards):
        page = QWidget()
        page.setObjectName('rcPage')
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 4, 0)
        v.setSpacing(12)
        for card in cards:
            v.addWidget(card)
        v.addStretch(1)
        area = QScrollArea()
        area.setObjectName('rcScroll')
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        area.setWidget(page)
        area.viewport().setAutoFillBackground(False)
        return area

    def _rich(self, html):
        t = theme.tokens(self.root)
        lab = QLabel(html.replace('<a ', '<a style="color:{}; text-decoration:none;" '
                                  .format(t['action_hover'])))
        lab.setWordWrap(True)
        lab.setTextFormat(Qt.TextFormat.RichText)
        lab.setOpenExternalLinks(True)
        lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        return lab

    @staticmethod
    def _link(text, url):
        return '<a href="{}">{}</a>'.format(url, text)

    def _plugin_version(self):
        try:
            with open(os.path.join(self.plugin_dir, 'metadata.txt'), encoding='utf-8') as f:
                for line in f:
                    if line.startswith('version='):
                        return line.split('=', 1)[1].strip()
        except OSError:
            pass
        return ''

    def _references_cards(self):
        muted = theme.tokens(self.root)['muted']
        plugin = Card(tr('Reservoir Creator'))
        plugin.body.addWidget(self._rich(
            '{}<br><span style="color:{}">{}</span>'.format(
                tr('Version {} · by Faruk Gurbuz').format(self._plugin_version()), muted,
                tr('Free and open source, GNU General Public License v3.'))))
        plugin.body.addWidget(self._rich(' &nbsp;·&nbsp; '.join((
            self._link(tr('GitHub repository'), REPO_URL),
            self._link(tr('Report an issue'), ISSUES_URL),
            self._link(tr('Documentation'), HELP_URL)))))

        data = Card(tr('Elevation data'),
                    tr('Please cite the elevation data you use in your work.'))
        for src in dem_sources.SOURCES:
            links = ' &nbsp;·&nbsp; '.join(self._link(label, url) for label, url in src.links)
            data.body.addWidget(self._rich(
                '<b>{}</b><br>{}<br><span style="color:{}">{}<br>{}: {}</span><br>{}'.format(
                    tr(src.name), tr(src.description), muted, src.citation, tr('Licence'),
                    src.license, links)))

        built = Card(tr('Built with'))
        built.body.addWidget(self._rich(' &nbsp;·&nbsp; '.join((
            self._link('QGIS', 'https://qgis.org'), self._link('GDAL', 'https://gdal.org'),
            self._link('NumPy', 'https://numpy.org'),
            self._link('Matplotlib', 'https://matplotlib.org'),
            self._link('Claude Opus 5.5', 'https://www.anthropic.com/claude')))))
        return [plugin, data, built]

    def _guide_cards(self):
        steps = (
            (tr('Draw the dam line'),
             tr('In step 1 choose "Draw on map" and click from one side of the valley to the '
                'other; right-click to finish (Backspace removes the last point, Esc cancels). '
                'Or choose "From layer" to use a line layer.')),
            (tr('Choose the elevation data'),
             tr('In step 2 pick a DEM layer from the project, or "Download": GEDTM30 (bare '
                'earth, recommended) or Copernicus GLO-30 (surface model). Only the area around '
                'the line is downloaded, and it is kept for later runs.')),
            (tr('Set a limit (optional)'),
             tr('Tick "Limit the water level" to use a design maximum water level (m a.s.l.) or '
                'a maximum depth above the riverbed at the line. Without a limit the water rises '
                'to the lower end of the line.')),
            (tr('Create the reservoir'),
             tr('Press "Create reservoir". The analysis area grows by itself until the whole '
                'reservoir fits; you can cancel at any time.')),
            (tr('Read the results'),
             tr('Step 3 shows the stored volume, the water level, the surface area and the '
                'maximum depth, the elevation–area–volume curves, the ground profile along the '
                'line and the table. Hover over the charts for exact values.')),
            (tr('Use the results'),
             tr('"Add to map" adds the outline, the line and a water-depth raster; "Export" '
                'saves a GeoPackage, a GeoTIFF, a CSV table or a chart image.')),
        )
        guide = Card(tr('How to use'))
        guide.body.addWidget(self._rich(''.join(
            '<p style="margin-bottom:6px"><b>{}. {}</b><br>{}</p>'.format(i, title, text)
            for i, (title, text) in enumerate(steps, 1))))
        tips = Card(tr('Tips'))
        tips.body.addWidget(self._rich('<ul style="margin-left:-20px">{}</ul>'.format(''.join(
            '<li style="margin-bottom:4px">{}</li>'.format(tip) for tip in (
                tr('If the reservoir appears on the downstream side, press the ⇄ button to '
                   'compute the other side of the line.'),
                tr('For very large areas turn on "Fast mode" in step 2: lower resolution, '
                   'faster.'),
                tr('A warning about a low point in the rim means the water would escape there '
                   'first; the point is marked on the map.'),
                tr('"Start over" (↻) clears the line and the results. Theme and language are in '
                   'the ⚙ menu.'),
                tr('Step timings are written to View ▸ Panels ▸ Log Messages, tab "Reservoir '
                   'Creator".'))))))
        tips.body.addWidget(self._rich(self._link(tr('Full documentation on GitHub'), HELP_URL)))
        return [guide, tips]

    def _settings_button(self):
        btn = icon_button(_icon('/mActionOptions.svg'), tr('Theme, language and help'))
        btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(btn)
        menu.addSection(tr('Theme'))
        group = QActionGroup(menu)
        for mode, text in (('auto', tr('Auto (follow QGIS)')), ('light', tr('Light')),
                           ('dark', tr('Dark'))):
            a = menu.addAction(text)
            a.setCheckable(True)
            a.setChecked(mode == self.theme_mode)
            group.addAction(a)
            a.triggered.connect(lambda _c=False, m=mode: self.set_theme(m))
        menu.addSection(tr('Language'))
        lang_group = QActionGroup(menu)
        for code, name in LANGUAGES:
            a = menu.addAction(name)
            a.setCheckable(True)
            a.setChecked(code == language())
            lang_group.addAction(a)
            a.triggered.connect(lambda _c=False, c=code: self.set_language(c))
        menu.addSeparator()
        menu.addAction(_icon('/mActionHelpContents.svg'), tr('Documentation')).triggered.connect(
            lambda: QDesktopServices.openUrl(QUrl(HELP_URL)))
        btn.setMenu(menu)
        btn.setStyleSheet('QToolButton::menu-indicator { image: none; width: 0; }')
        return btn

    def _line_card(self):
        card = Card(tr('Dam line'),
                    tr('The water level (above mean sea level) is the ground height at the '
                       'lower end of the line, unless you set a lower limit.'), step=1)
        self.line_mode = Segmented([tr('Draw on map'), tr('From layer')],
                                   [_icon('/mActionCaptureLine.svg'), _icon('/mIconLineLayer.svg')])
        self.line_mode.changed.connect(self._line_mode_changed)
        card.body.addWidget(self.line_mode)

        self.draw_page = QWidget()
        dl = QVBoxLayout(self.draw_page)
        dl.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self.draw_btn = pill_button(tr('Draw line'), _icon('/mActionCaptureLine.svg'))
        self.draw_btn.setCheckable(True)
        self.draw_btn.toggled.connect(self._draw_toggled)
        clear = pill_button(tr('Clear'), _icon('/mActionDeleteSelected.svg'))
        clear.clicked.connect(self.clear)
        row.addWidget(self.draw_btn, 1)
        row.addWidget(clear)
        dl.addLayout(row)
        dl.addWidget(hint(tr('Click from one side of the valley to the other, right-click to '
                             'finish. Backspace removes the last point, Esc cancels.')))
        card.body.addWidget(self.draw_page)

        self.layer_page = QWidget()
        ll = QVBoxLayout(self.layer_page)
        ll.setContentsMargins(0, 0, 0, 0)
        self.line_combo = QgsMapLayerComboBox()
        self.line_combo.setFilters(_layer_filter('LineLayer'))
        self.line_combo.setAllowEmptyLayer(True)
        self.line_combo.layerChanged.connect(lambda *_: self._line_changed())
        self.selected_only = QCheckBox(tr('Use the selected feature'))
        self.selected_only.toggled.connect(lambda *_: self._line_changed())
        ll.addWidget(self.line_combo)
        ll.addWidget(self.selected_only)
        card.body.addWidget(self.layer_page)

        self.line_info = hint(tr('No line yet.'))
        card.body.addWidget(self.line_info)

        # optional design limit: a maximum water level or a maximum depth
        self.use_max_level = QCheckBox(tr('Limit the water level'))
        self.use_max_level.setToolTip(
            tr('Optional. Use it when the design maximum is lower than the crest (freeboard).\n'
               'The water level is then the lower of your limit and the ground at the lower\n'
               'end of the line. A limit above that is reported and the line is used.'))
        card.body.addWidget(self.use_max_level)
        row = QHBoxLayout()
        self.limit_kind = QComboBox()
        self.limit_kind.addItem(tr('Maximum water level'))
        self.limit_kind.addItem(tr('Maximum depth'))
        self.limit_kind.setItemData(LIMIT_LEVEL, tr('Water level above mean sea level'),
                                    Qt.ItemDataRole.ToolTipRole)
        self.limit_kind.setItemData(LIMIT_DEPTH, tr('Depth above the riverbed at the line'),
                                    Qt.ItemDataRole.ToolTipRole)
        self.max_level = QDoubleSpinBox()
        self.max_level.setDecimals(2)
        self.max_level.setSingleStep(1.0)
        row.addWidget(self.limit_kind, 1)
        row.addWidget(self.max_level, 1)
        card.body.addLayout(row)
        self._limit_kind_changed(LIMIT_LEVEL)
        self._limit_enabled(False)
        self.use_max_level.toggled.connect(self._limit_enabled)
        self.use_max_level.toggled.connect(self._inputs_changed)
        self.limit_kind.currentIndexChanged.connect(self._limit_kind_changed)
        self.limit_kind.currentIndexChanged.connect(self._inputs_changed)
        self.max_level.valueChanged.connect(self._inputs_changed)
        return card

    def _dem_card(self):
        card = Card(tr('Elevation data (DEM)'), step=2)
        self.dem_mode = Segmented([tr('Project layer'), tr('Download')],
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
            self.source_combo.addItem(tr(src.name), src.key)
        self.source_combo.currentIndexChanged.connect(self._source_changed)
        l2.addWidget(self.source_combo)
        self.source_hint = hint('')
        l2.addWidget(self.source_hint)
        self.add_dem = QCheckBox(tr('Add the downloaded DEM to the project'))
        l2.addWidget(self.add_dem)
        card.body.addWidget(self.dl_page)
        self.fast_mode = QCheckBox(tr('Fast mode (reduce the resolution for large areas)'))
        self.fast_mode.toggled.connect(self._inputs_changed)
        self.dem_combo.layerChanged.connect(self._inputs_changed)
        self.source_combo.currentIndexChanged.connect(self._inputs_changed)
        self.fast_mode.setToolTip(
            tr('Off: the DEM is used at its own resolution.\n'
               'On: areas above {:,.0f} million cells are coarsened for speed; the results are '
               'then less precise.').format(terrain.FAST_MODE_CELLS / 1e6))
        card.body.addWidget(self.fast_mode)
        self._source_changed()
        return card

    def _results_card(self):
        card = Card(tr('Reservoir'), step=3)
        t = theme.tokens(self.root)
        self.hero = ResultHero({'level': t['accent'], 'area': t['area'], 'depth': t['depth']})
        card.body.addWidget(self.hero)
        self.banner_box = QVBoxLayout()
        self.banner_box.setSpacing(5)
        card.body.addLayout(self.banner_box)

        self.chart_tabs = QTabWidget()      # pages only; switched by the pill control
        self.chart_tabs.setObjectName('rcViews')
        self.chart_tabs.tabBar().setVisible(False)
        self.chart_tabs.setDocumentMode(True)
        views = [tr('E-A-V curve'), tr('Profile'), tr('Table')]
        if HAS_MPL:
            self.curve_chart = CurveChart(min_height=400)
            self.profile_chart = ProfileChart(min_height=280)
            self.chart_tabs.addTab(self.curve_chart, views[0])
            self.chart_tabs.addTab(self.profile_chart, views[1])
        else:
            self.curve_chart = self.profile_chart = None
            views = [tr('Charts'), tr('Table')]
            self.chart_tabs.addTab(hint(tr('Install matplotlib to see the charts.')), views[0])
        self.table = QTableWidget(0, 3)
        self.table.setObjectName('rcTable')
        self.table.setHorizontalHeaderLabels([tr('Elevation (m a.s.l.)'), tr('Area (km²)'),
                                              tr('Volume (hm³)')])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setHighlightSections(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(26)
        self.table.setShowGrid(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setMinimumHeight(300)
        self.chart_tabs.addTab(self.table, views[-1])
        self.view_switch = Segmented(views)
        self.view_switch.buttons[0].setToolTip(tr('Elevation - area - volume curves'))
        self.view_switch.changed.connect(self.chart_tabs.setCurrentIndex)
        self.chart_tabs.currentChanged.connect(
            lambda i: self.view_switch.buttons[i].setChecked(True))
        card.body.addSpacing(4)
        card.body.addWidget(self.view_switch)
        card.body.addWidget(self.chart_tabs)

        act = QHBoxLayout()
        add = pill_button(tr('Add to map'), _icon('/mActionAddLayer.svg'))
        add.setToolTip(tr('Add the reservoir outline, the line and the water depth as layers'))
        add.clicked.connect(self.add_to_map)
        export = pill_button(tr('Export'), _icon('/mActionFileSave.svg'), tool=True)
        export.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(export)
        for text, slot in ((tr('GeoPackage (outline, line, table)…'), self.export_gpkg),
                           (tr('Water depth (GeoTIFF)…'), self.export_depth),
                           (tr('Table (CSV)…'), self.export_csv),
                           (tr('Copy table'), self.copy_table),
                           (tr('Chart image (PNG)…'), self.export_chart)):
            menu.addAction(text).triggered.connect(slot)
        export.setMenu(menu)
        flip = icon_button(_icon('/mActionReverseLine.svg'),
                           tr('Upstream side guessed wrong? The plugin decides by itself which '
                              'side of the line is\nupstream (where water is held back). If the '
                              'blue reservoir is on the downstream side,\nclick here to compute '
                              'it on the other side of the line.'))
        flip.clicked.connect(self.flip_side)
        zoom = icon_button(_icon('/mActionZoomToLayer.svg'), tr('Zoom to the reservoir'))
        zoom.clicked.connect(self.zoom_to_reservoir)
        act.addWidget(add, 1)
        act.addWidget(export)
        act.addWidget(flip)
        act.addWidget(zoom)
        card.body.addLayout(act)
        return card

    # -------------------------------------------------- theme and language
    # Both are chosen from the ⚙ menu, which lives inside the panel being
    # rebuilt: rebuilding (and deleting the old widgets) while that menu's event
    # loop is still running deletes the menu under its own feet.  The rebuild
    # therefore waits until the menu has closed and control is back in QGIS.
    def set_theme(self, mode):
        if mode == self.theme_mode:
            return
        self.theme_mode = mode
        QgsSettings().setValue(SETTINGS + 'theme', mode)
        QTimer.singleShot(0, self._rebuild)

    def set_language(self, code):
        if code == language():
            return
        set_language(code)
        QgsSettings().setValue(SETTINGS + 'language', code)
        QTimer.singleShot(0, self._rebuild)

    def _rebuild(self):
        """Recreate the panel's widgets (new theme / language), keeping the work."""
        result, status = self.result, self.status_lbl.text()
        limit = (self.use_max_level.isChecked(), self.limit_kind.currentIndex(),
                 self.max_level.value())
        drawing = self.draw_btn.isChecked()
        page = self.page_switch.index()
        self._save_settings()
        self._build()
        self.page_switch.set_index(page)
        self._placement_changed(self.isFloating(), remember=False)
        self._load_settings()
        self.use_max_level.setChecked(limit[0])
        self.limit_kind.setCurrentIndex(limit[1])
        self.max_level.setValue(limit[2])
        self.result = result
        self._show_line()
        if result is not None:
            self._show_result()
        else:
            self._status(tr('Draw a line across a valley to begin.') if self.drawn_geom is None
                         else status)
        if drawing:
            self.draw_btn.setChecked(True)
        self._set_running(self.task is not None)

    # ----------------------------------------------------------- placement
    def place(self):
        """Open as a separate window (default) or docked, as the user left it."""
        s = QgsSettings()
        if not s.value(SETTINGS + 'floating', True, type=bool):
            return
        self.setFloating(True)
        geom = s.value(SETTINGS + 'window_geometry', None)
        if geom is None or not self.restoreGeometry(geom):
            main = self.iface.mainWindow().frameGeometry()
            w, h = 460, min(900, max(600, main.height() - 120))
            self.setGeometry(main.right() - w - 40, main.top() + 90, w, h)

    def toggle_docked(self):
        self.setFloating(not self.isFloating())

    def _placement_changed(self, floating, remember=True):
        self.dock_btn.setText(tr('Dock') if floating else tr('Undock'))
        self.dock_btn.setToolTip(tr('Attach this window to the QGIS window') if floating else
                                 tr('Show this panel as a separate window'))
        if remember:
            QgsSettings().setValue(SETTINGS + 'floating', bool(floating))

    def save_placement(self):
        if self.isFloating():
            QgsSettings().setValue(SETTINGS + 'window_geometry', self.saveGeometry())

    # ------------------------------------------------------------ settings
    def _load_settings(self):
        s = QgsSettings()
        self.line_mode.set_index(s.value(SETTINGS + 'line_mode', 0, type=int))
        self.dem_mode.set_index(s.value(SETTINGS + 'dem_mode', 0, type=int))
        i = self.source_combo.findData(s.value(SETTINGS + 'source', 'gedtm30', type=str))
        self.source_combo.setCurrentIndex(max(0, i))
        self.add_dem.setChecked(s.value(SETTINGS + 'add_dem', False, type=bool))
        self.fast_mode.setChecked(s.value(SETTINGS + 'fast_mode', False, type=bool))

    def _save_settings(self):
        s = QgsSettings()
        s.setValue(SETTINGS + 'line_mode', self.line_mode.index())
        s.setValue(SETTINGS + 'dem_mode', self.dem_mode.index())
        s.setValue(SETTINGS + 'source', self.source_combo.currentData())
        s.setValue(SETTINGS + 'add_dem', self.add_dem.isChecked())
        s.setValue(SETTINGS + 'fast_mode', self.fast_mode.isChecked())

    # --------------------------------------------------------------- limit
    def _limit_enabled(self, on):
        self.limit_kind.setEnabled(on)
        self.max_level.setEnabled(on)

    def _limit_kind_changed(self, kind):
        self.max_level.blockSignals(True)
        if kind == LIMIT_DEPTH:
            self.max_level.setRange(0.1, 3000.0)
            self.max_level.setSuffix(' m')
            self.max_level.setToolTip(tr('Maximum depth above the riverbed at the line'))
        else:
            self.max_level.setRange(-500.0, 9000.0)
            self.max_level.setSuffix(' ' + tr('m a.s.l.'))
            self.max_level.setToolTip(tr('Maximum water level above mean sea level'))
        if kind in self._suggested:
            self.max_level.setValue(self._suggested[kind])
        self.max_level.blockSignals(False)

    def _limit(self):
        """(max_level, max_depth) for the analysis."""
        if not self.use_max_level.isChecked():
            return None, None
        if self.limit_kind.currentIndex() == LIMIT_DEPTH:
            return None, self.max_level.value()
        return self.max_level.value(), None

    # ---------------------------------------------------------------- line
    def _line_mode_changed(self, i):
        self.draw_page.setVisible(i == 0)
        self.layer_page.setVisible(i == 1)
        if i == 1:
            self.draw_btn.setChecked(False)
        self._line_changed()

    def _draw_toggled(self, on):
        if on:
            if self.canvas.mapTool() is not self.tool:
                self.canvas.setMapTool(self.tool)
            self._status(tr('Click across the valley; right-click to finish.'))
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
        self._line_changed()

    def _line_changed(self):
        """A new line makes the old reservoir stale; the user starts the next run."""
        self._drop_result()
        self._show_line()
        if self._current_line()[0] is None:
            return
        if self._dem_ready():
            self._status(tr('Line ready. Press "Create reservoir" to compute.'))
        else:
            self._status(tr('Line ready. Now choose the elevation data (step 2).'))

    def clear(self):
        self.drawn_geom = None
        self.drawn_crs = None
        self._drop_result()
        self._show_line()

    def _drop_result(self):
        self._clear_overlays()
        self.results.setVisible(False)
        self.result = None

    def reset(self):
        """Start over: stop any run, forget the line and the results."""
        self.run_id += 1                # a run still stopping is ignored when it ends
        if self.task is not None:
            self.task.cancel()
        self.line_combo.setLayer(None)
        self.selected_only.setChecked(False)
        self.use_max_level.setChecked(False)
        self._suggested = {}
        self.clear()
        while self.banner_box.count():
            w = self.banner_box.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        self.table.setRowCount(0)
        if HAS_MPL:
            for chart in (self.curve_chart, self.profile_chart):
                chart.show_empty(tr('Draw a line across a valley to see this chart.'))
        self.chart_tabs.setCurrentIndex(0)
        self.page_switch.set_index(0)
        self.scroll.verticalScrollBar().setValue(0)
        self.activate_drawing()
        self._status(tr('Draw a line across a valley to begin.'))

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
            self.line_info.setText(tr('No line yet.'))
            return
        geom = QgsGeometry.fromPolylineXY([QgsPointXY(x, y) for x, y in pts])
        self.line_band = QgsRubberBand(self.canvas, Qgis.GeometryType.Line)
        self.line_band.setColor(QColor(theme.LIGHT['dam']))
        self.line_band.setWidth(4)
        self.line_band.setToGeometry(geom, crs)
        d = QgsDistanceArea()
        d.setSourceCrs(crs, QgsProject.instance().transformContext())
        d.setEllipsoid(QgsProject.instance().ellipsoid() or 'WGS84')
        self.line_info.setText(tr('✔ Line: {:,.0f} m long').format(d.measureLength(geom)))

    # ----------------------------------------------------------------- DEM
    def _dem_mode_changed(self, i):
        self.dem_page.setVisible(i == 0)
        self.dl_page.setVisible(i == 1)
        self._inputs_changed()

    def _inputs_changed(self, *_):
        if getattr(self, 'result', None) is not None:
            self._status(tr('Settings changed. Press "Create reservoir" to update the results.'))

    def _source_changed(self, *_):
        src = dem_sources.SOURCES_BY_KEY[self.source_combo.currentData()]
        self.source_hint.setText(tr('{} Only the area around the line is downloaded; you can '
                                    'cancel at any time.').format(tr(src.description)))
        self.source_hint.setToolTip(src.citation)

    def _dem_ready(self):
        return self.dem_mode.index() == 1 or self.dem_combo.currentLayer() is not None

    # ----------------------------------------------------------------- run
    def run(self, side='auto'):
        if self.task is not None:
            self._status(tr('Still stopping the previous run - try again in a moment.'))
            return
        pts, crs = self._current_line()
        if not pts:
            self._message(tr('Draw a line across the valley first (step 1).'),
                          Qgis.MessageLevel.Warning)
            return
        download = None
        dem_path = ''
        if self.dem_mode.index() == 0:
            lyr = self.dem_combo.currentLayer()
            if lyr is None:
                self._message(tr('Choose a DEM layer, or switch to "Download" (step 2).'),
                              Qgis.MessageLevel.Warning)
                return
            if lyr.providerType() != 'gdal':
                self._message(tr('The DEM must be a file-based raster layer.'),
                              Qgis.MessageLevel.Warning)
                return
            dem_path = lyr.source()
        else:
            download = self.source_combo.currentData()
        self._save_settings()
        max_level, max_depth = self._limit()
        params = analysis.Params(dem_path, pts, crs.toWkt(), side=side,
                                 fast=self.fast_mode.isChecked(), max_level=max_level,
                                 max_depth=max_depth)
        self.task = ReservoirTask(params, download)
        self.task.run_id = self.run_id
        task = self.task
        self.task.progressChanged.connect(lambda p: self.progress.setValue(int(p)))
        # a run stopped by "Start over" may still report while it winds down
        self.task.message.connect(
            lambda text: self._status(text) if task.run_id == self.run_id else None)
        self.task.taskCompleted.connect(self._task_done)
        self.task.taskTerminated.connect(self._task_done)
        self._set_running(True)
        QgsApplication.taskManager().addTask(self.task)

    def cancel(self):
        if self.task is not None:
            self.task.cancel()
            self._status(tr('Cancelling…'))

    def _set_running(self, running):
        self.run_btn.setEnabled(not running)
        self.cancel_btn.setVisible(running)
        self.progress.setVisible(running)
        self.progress.setValue(0)

    def _task_done(self):
        task, self.task = self.task, None
        self._set_running(False)
        if task is None or task.run_id != self.run_id:   # started before "Start over"
            return
        if task.result is None:
            if task.error == 'Cancelled.':
                self._status(tr('Cancelled.'))
            else:
                self._message(task.error or tr('Something went wrong.'),
                              Qgis.MessageLevel.Critical)
            return
        res = task.result
        if task.download_source:
            src = dem_sources.SOURCES_BY_KEY[task.download_source]
            res.notes[:0] = [Note(Note.INFO, n) for n in task.download_notes]
            res.notes.append(Note(Note.INFO, Msg('Elevation data: {} ({}).', src.short,
                                                 src.license)))
            if task.downloaded_path and self.add_dem.isChecked():
                lyr = QgsRasterLayer(task.downloaded_path,
                                     tr('{} (download)').format(src.short))
                if lyr.isValid():
                    QgsProject.instance().addMapLayer(lyr)
        self.result = res
        self._show_result()
        if res.cap_ignored:     # the user's limit could not be honoured: say so clearly
            note = next((n for n in res.notes if n.kind == 'cap'), None)
            if note is not None:
                self.iface.messageBar().pushMessage('Reservoir Creator', note.text,
                                                    level=Qgis.MessageLevel.Warning,
                                                    duration=10)

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
        chip = None
        for n in r.notes:
            if n.kind == 'resolution':
                chip = tr('Full resolution · {:.1f} m').format(r.grid.cell_size)
                continue
            if n.kind == 'fast':
                chip = tr('Fast mode · {:.0f} m').format(r.grid.cell_size)
            self.banner_box.addWidget(Banner(n.level, n.text))
        if r.limited_by == 'saddle':
            source, label = tr('a low point in the rim'), tr('low point in the rim')
        elif r.level_source == 'max':
            source, label = tr('your maximum water level'), tr('maximum level')
        elif r.level_source == 'depth':
            source, label = tr('your maximum depth'), tr('maximum depth')
        else:
            source, label = tr('the lower end of the line'), tr('lower end of the line')
        self.hero.set(theme.fmt_sig(r.volume_m3 / 1e6, 4), theme.fmt(r.water_level, 1),
                      theme.fmt_sig(r.area_m2 / 1e6, 3), theme.fmt(r.max_depth, 1),
                      tr('million m³ behind the line, water level {:.1f} m above mean sea '
                         'level, set by {}').format(r.water_level, source), chip)

        lv, a, v = r.curve()
        self.table.setRowCount(len(lv))
        for i, row in enumerate(zip(lv, a, v)):
            texts = ('{:.2f}'.format(row[0]), theme.fmt_sig(row[1] / 1e6, 4),
                     theme.fmt_sig(row[2] / 1e6, 5))
            for j, text in enumerate(texts):
                it = QTableWidgetItem(text)
                it.setTextAlignment(RIGHT_ALIGN)
                self.table.setItem(i, j, it)
        # starting values for the limit: the level just computed, and its depth
        self._suggested = {LIMIT_LEVEL: round(r.water_level, 2),
                           LIMIT_DEPTH: round(r.water_level - r.line_bed, 2)}
        if not self.use_max_level.isChecked():
            self._limit_kind_changed(self.limit_kind.currentIndex())
        if HAS_MPL:
            self.curve_chart.set_data(lv, a, v, r.water_level, label)
            self.profile_chart.set_data(r.stations, r.ground, r.water_level, label)

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
            xf = QgsCoordinateTransform(crs, self.canvas.mapSettings().destinationCrs(),
                                        QgsProject.instance())
            mk = QgsVertexMarker(self.canvas)
            mk.setCenter(xf.transform(QgsPointXY(*r.pour_point)))
            mk.setIconType(QgsVertexMarker.IconType.ICON_X)
            mk.setColor(QColor(theme.LIGHT['critical']))
            mk.setIconSize(14)
            mk.setPenWidth(3)
            self.escape_marker = mk
        self.results.setVisible(True)
        self.scroll_timer.start()
        self._status(tr('Reservoir at {:.1f} m a.s.l.: {} million m³, {} km².').format(
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
            self._message(tr('Reservoir added to the project.'), Qgis.MessageLevel.Success)

    def zoom_to_reservoir(self):
        r = self.result
        if r is None or not r.polygon_wkt:
            return
        xf = QgsCoordinateTransform(outputs.result_crs(r),
                                    self.canvas.mapSettings().destinationCrs(),
                                    QgsProject.instance())
        rect = xf.transformBoundingBox(QgsGeometry.fromWkt(r.polygon_wkt).boundingBox())
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
        path = self._ask_path(tr('Export table'), 'CSV (*.csv)', 'reservoir_table.csv')
        if path:
            outputs.write_csv(self.result, path)
            self._message(tr('Saved {}').format(path), Qgis.MessageLevel.Success)

    def export_gpkg(self):
        if self.result is None:
            return
        path = self._ask_path(tr('Export to GeoPackage'), 'GeoPackage (*.gpkg)', 'reservoir.gpkg')
        if path:
            try:
                outputs.write_geopackage(self.result, path)
                self._message(tr('Saved {}').format(path), Qgis.MessageLevel.Success)
            except IOError as e:
                self._message(str(e), Qgis.MessageLevel.Critical)

    def export_depth(self):
        if self.result is None:
            return
        path = self._ask_path(tr('Export water depth'), 'GeoTIFF (*.tif)', 'water_depth.tif')
        if path:
            QgsProject.instance().addMapLayer(outputs.depth_raster(self.result, path))
            self._message(tr('Saved {}').format(path), Qgis.MessageLevel.Success)

    def export_chart(self):
        if not HAS_MPL or self.result is None:
            return
        chart = self.profile_chart if self.chart_tabs.currentIndex() == 1 else self.curve_chart
        name = 'line_profile.png' if chart is self.profile_chart else 'elevation_area_volume.png'
        path = self._ask_path(tr('Save chart'), tr('PNG image (*.png)'), name)
        if path:
            chart.save_png(path)

    def copy_table(self):
        if self.result is not None:
            QGuiApplication.clipboard().setText(outputs.table_text(self.result))
            self._status(tr('Table copied to the clipboard.'))

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
