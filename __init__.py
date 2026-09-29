# -*- coding: utf-8 -*-
"""
Reservoir Creator - QGIS plugin
Elevation-area-capacity curves, inundated area and dam sizing for a dam axis
drawn on a digital elevation model.

(C) 2021-2026 Faruk Gurbuz - GNU GPL v3 or later
"""


def classFactory(iface):  # pylint: disable=invalid-name
    from .plugin import ReservoirCreatorPlugin
    return ReservoirCreatorPlugin(iface)
