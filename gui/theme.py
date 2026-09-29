# -*- coding: utf-8 -*-
"""Colour tokens and number formatting shared by the dock and the charts.

Light and dark steps are chosen separately (not an automatic inversion); the
active set follows the QGIS UI theme.
"""

from qgis.PyQt.QtGui import QPalette
from qgis.PyQt.QtWidgets import QApplication

LIGHT = {
    'ink': '#0b0b0b',
    'ink2': '#52514e',
    'muted': '#898781',
    'grid': '#e1e0d9',
    'axis': '#c3c2b7',
    'border': '#d9d8d2',
    'storage': '#2a78d6',       # categorical slot 1 (blue)
    'area': '#1baf7a',          # slot 3 (aqua)
    'dam': '#eb6834',           # slot 2 (orange)
    'ground': '#8f8a80',
    'ground_fill': '#d7d3c8',
    'water_fill': '#86b6ef',
    'accent': '#2a78d6',
    'accent_hover': '#256abf',
    'critical': '#d03b3b',
    'warning': '#fab219',
    'good': '#0ca30c',
}

DARK = {
    'ink': '#ffffff',
    'ink2': '#c3c2b7',
    'muted': '#898781',
    'grid': '#2c2c2a',
    'axis': '#383835',
    'border': '#3a3a37',
    'storage': '#3987e5',
    'area': '#199e70',
    'dam': '#d95926',
    'ground': '#8f8a80',
    'ground_fill': '#4a4843',
    'water_fill': '#1c5cab',
    'accent': '#3987e5',
    'accent_hover': '#5598e7',
    'critical': '#d03b3b',
    'warning': '#fab219',
    'good': '#0ca30c',
}


def is_dark(widget=None):
    src = widget if widget is not None else QApplication.instance()
    return src.palette().color(QPalette.ColorRole.Window).lightness() < 128


def tokens(widget=None):
    """Colour tokens for the current theme, plus the widget's surface colour."""
    src = widget if widget is not None else QApplication.instance()
    t = dict(DARK if is_dark(widget) else LIGHT)
    t['surface'] = src.palette().color(QPalette.ColorRole.Base).name()
    t['window'] = src.palette().color(QPalette.ColorRole.Window).name()
    return t


# ---------------------------------------------------------------------------
# Units & formatting
# ---------------------------------------------------------------------------

def fmt(value, decimals=1):
    if value is None or value != value:     # NaN
        return '–'
    return '{:,.{}f}'.format(value, decimals)


def fmt_sig(value, sig=3):
    """Format with about ``sig`` significant digits, thousands separated."""
    if value is None or value != value:
        return '–'
    a = abs(value)
    if a >= 10 ** (sig - 1) or a == 0:
        return '{:,.0f}'.format(value)
    import math
    decimals = max(0, sig - 1 - int(math.floor(math.log10(a))))
    return '{:,.{}f}'.format(value, min(decimals, 4))


def hm3(m3):
    return m3 / 1.0e6


def km2(m2):
    return m2 / 1.0e6
