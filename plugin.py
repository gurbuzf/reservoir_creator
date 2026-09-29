# -*- coding: utf-8 -*-
"""QGIS entry point: toolbar/menu action toggling the Reservoir Creator dock."""

import os

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon

try:  # Qt6 (QGIS 4)
    from qgis.PyQt.QtGui import QAction
except ImportError:  # Qt5 (QGIS 3)
    from qgis.PyQt.QtWidgets import QAction

MENU = '&Reservoir Creator'


class ReservoirCreatorPlugin:

    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.action = None
        self.dock = None

    def initGui(self):  # noqa: N802 (QGIS API)
        icon = QIcon(os.path.join(self.plugin_dir, 'icons', 'icon.svg'))
        self.action = QAction(icon, 'Reservoir Creator', self.iface.mainWindow())
        self.action.setObjectName('ReservoirCreatorAction')
        self.action.setCheckable(True)
        self.action.setStatusTip('Draw a line across a valley and see the reservoir behind it')
        self.action.toggled.connect(self.toggle)
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToMenu(MENU, self.action)

    def _create_dock(self):
        from .gui.dock import ReservoirDock
        self.dock = ReservoirDock(self.iface, self.plugin_dir, self.iface.mainWindow())
        self.iface.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock)
        self.dock.closedStateChanged.connect(self._dock_closed)

    def toggle(self, checked):
        if checked and self.dock is None:
            self._create_dock()
        if self.dock is None:
            return
        self.dock.setUserVisible(checked)
        if checked:
            self.dock.raise_()
            self.dock.activate_drawing()

    def _dock_closed(self, closed):
        if self.action is not None:
            self.action.blockSignals(True)
            self.action.setChecked(not closed)
            self.action.blockSignals(False)

    def unload(self):
        if self.dock is not None:
            self.dock.cleanup()
            self.iface.removeDockWidget(self.dock)
            self.dock.deleteLater()
            self.dock = None
        if self.action is not None:
            self.iface.removePluginMenu(MENU, self.action)
            self.iface.removeToolBarIcon(self.action)
            self.action.deleteLater()
            self.action = None
