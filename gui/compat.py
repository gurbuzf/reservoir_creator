# -*- coding: utf-8 -*-
"""Small shims for QGIS API differences between 3.28 and 4.x."""

from qgis.core import Qgis, QgsWkbTypes


def geometry_type(name):
    """'Line' / 'Polygon' geometry type (e.g. for rubber bands): Qgis.GeometryType
    since QGIS 3.30, QgsWkbTypes.LineGeometry / PolygonGeometry before."""
    enum = getattr(Qgis, 'GeometryType', None)
    if enum is not None:
        return getattr(enum, name)
    return getattr(QgsWkbTypes, name + 'Geometry')
