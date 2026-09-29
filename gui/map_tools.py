# -*- coding: utf-8 -*-
"""Map tool for drawing the dam line on the canvas (Profile Tool style).

* left click      - add a vertex (snaps to the project's snapping settings)
* right click / double click - finish the line (needs >= 2 points)
* Backspace       - remove the last vertex
* Esc             - cancel
"""

from qgis.core import (Qgis, QgsDistanceArea, QgsGeometry, QgsPointLocator, QgsPointXY,
                       QgsProject)
from qgis.gui import QgsMapTool, QgsRubberBand, QgsSnapIndicator
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor, QCursor


class DamAxisTool(QgsMapTool):
    axisCompleted = pyqtSignal(QgsGeometry)
    status = pyqtSignal(str)
    cancelled = pyqtSignal()

    def __init__(self, canvas, color='#eb6834'):
        super().__init__(canvas)
        self.canvas_ = canvas
        self.color = QColor(color)
        self.points = []
        self.band = None
        self.snap = QgsSnapIndicator(canvas)
        self.setCursor(QCursor(Qt.CursorShape.CrossCursor))

    # -- rubber band ------------------------------------------------------------
    def _ensure_band(self):
        if self.band is None:
            self.band = QgsRubberBand(self.canvas_, Qgis.GeometryType.Line)
            self.band.setColor(self.color)
            self.band.setWidth(3)
            self.band.setLineStyle(Qt.PenStyle.DashLine)

    def _clear_band(self):
        if self.band is not None:
            self.canvas_.scene().removeItem(self.band)
            self.band = None

    def _redraw(self, moving=None):
        self._ensure_band()
        pts = list(self.points) + ([moving] if moving is not None else [])
        self.band.setToGeometry(QgsGeometry.fromPolylineXY(pts), None)

    def _snapped(self, event):
        match = self.canvas_.snappingUtils().snapToMap(event.pos())
        if self.snap is not None:
            self.snap.setMatch(match)
        if match.isValid():
            return QgsPointXY(match.point())
        return QgsPointXY(event.mapPoint())

    def _length(self, pts):
        if len(pts) < 2:
            return 0.0
        d = QgsDistanceArea()
        d.setSourceCrs(self.canvas_.mapSettings().destinationCrs(),
                       QgsProject.instance().transformContext())
        d.setEllipsoid(QgsProject.instance().ellipsoid() or 'WGS84')
        return d.measureLength(QgsGeometry.fromPolylineXY(pts))

    # -- events -----------------------------------------------------------------
    def canvasMoveEvent(self, event):
        p = self._snapped(event)
        if self.points:
            self._redraw(p)
            self.status.emit('Line: {:,.0f} m · {} points - right-click to finish, '
                             'Backspace to undo, Esc to cancel'
                             .format(self._length(self.points + [p]), len(self.points) + 1))

    def canvasReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            self._finish()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self.points.append(self._snapped(event))
            self._redraw()

    def canvasDoubleClickEvent(self, event):
        # the release event already added the vertex
        self._finish()

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.reset()
            self.cancelled.emit()
            self.status.emit('Drawing cancelled.')
        elif key in (Qt.Key.Key_Backspace, Qt.Key.Key_Delete) and self.points:
            self.points.pop()
            self._redraw()
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._finish()

    def _finish(self):
        pts = []
        for p in self.points:           # drop duplicate clicks
            if not pts or p.distance(pts[-1]) > 0:
                pts.append(p)
        if len(pts) < 2:
            self.status.emit('Click at least two points across the valley.')
            return
        geom = QgsGeometry.fromPolylineXY(pts)
        self.reset()
        self.axisCompleted.emit(geom)

    def reset(self):
        self.points = []
        self._clear_band()
        if self.snap is not None:
            self.snap.setMatch(QgsPointLocator.Match())

    def release(self):
        """Drop canvas items (rubber band, snap indicator) before unloading."""
        self.reset()
        self.snap = None

    def deactivate(self):
        self.reset()
        super().deactivate()
