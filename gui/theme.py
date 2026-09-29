# -*- coding: utf-8 -*-
"""Colour tokens and number formatting shared by the dock and the charts.

Light and dark steps are chosen separately (not an automatic inversion); the
active set follows the QGIS UI theme.
"""

from qgis.PyQt.QtGui import QPalette
from qgis.PyQt.QtWidgets import QApplication

LIGHT = {
    'ink': '#111827',
    'ink2': '#4b5563',
    'muted': '#8a919c',
    'grid': '#e8eaee',
    'axis': '#d5d9df',
    'border': '#e4e7eb',
    'track': '#eef0f3',         # segmented-control track, chip background
    'storage': '#2563eb',       # volume (blue)
    'area': '#0fa39a',          # surface area (teal)
    'depth': '#7c5cff',         # depth (violet)
    'dam': '#eb6834',           # the drawn line (orange)
    'ground': '#8b8378',
    'ground_fill': '#e3ddd3',
    'earth': '#b58b63',         # soil under the ground line (profile)
    'earth_line': '#7a5536',
    'water_fill': '#7fb2f5',
    'accent': '#2563eb',
    'accent2': '#0fa3b1',       # end of the primary-button gradient
    'accent_hover': '#1d4fd8',
    'action': '#3a84f7',        # the call to action: azure ...
    'action2': '#2f4de6',       # ... to royal blue (gradient), also the logo's colours
    'action_hover': '#2a6fe6',
    'action2_hover': '#243cc9',
    'select': '#1f2937',        # selected option in switches: neutral, not blue
    'select_text': '#ffffff',
    'check_icon': 'check.svg',
    'critical': '#dc3b3b',
    'warning': '#e8a100',
    'good': '#16a34a',
}

DARK = {
    'ink': '#f3f4f6',
    'ink2': '#c2c7cf',
    'muted': '#8b93a0',
    'grid': '#2f343b',
    'axis': '#3b414a',
    'border': '#353a42',
    'track': '#2a2f36',
    'storage': '#4f8df7',
    'area': '#22b8ad',
    'depth': '#9b87ff',
    'dam': '#f07a45',
    'ground': '#9a9186',
    'ground_fill': '#4a453f',
    'earth': '#a67c55',
    'earth_line': '#d2a679',
    'water_fill': '#2f6fd0',
    'accent': '#4f8df7',
    'accent2': '#22b8c9',
    'accent_hover': '#6aa0f8',
    'action': '#4a8ff8',
    'action2': '#4059ee',
    'action_hover': '#62a0fa',
    'action2_hover': '#5a70f2',
    'select': '#e5e7eb',
    'select_text': '#111827',
    'check_icon': 'check-dark.svg',
    'critical': '#ef5350',
    'warning': '#f5b82e',
    'good': '#34c759',
}


# Panel theme: 'auto' follows QGIS, 'light' / 'dark' give the panel its own colours.
MODES = ('auto', 'light', 'dark')

_PALETTES = {
    'light': {'Window': '#f3f4f6', 'WindowText': '#111827', 'Base': '#ffffff',
              'AlternateBase': '#f5f6f8', 'Text': '#111827', 'Button': '#ffffff',
              'ButtonText': '#111827', 'Highlight': '#2563eb', 'HighlightedText': '#ffffff',
              'ToolTipBase': '#111827', 'ToolTipText': '#ffffff', 'PlaceholderText': '#9ca3af',
              'Link': '#2563eb', 'Mid': '#d1d5db', 'Midlight': '#e5e7eb', 'Dark': '#9ca3af',
              'Light': '#ffffff', 'Shadow': '#6b7280', 'disabled': '#9ca3af'},
    'dark': {'Window': '#16191e', 'WindowText': '#e8eaed', 'Base': '#1f232a',
             'AlternateBase': '#262b33', 'Text': '#e8eaed', 'Button': '#262b33',
             'ButtonText': '#e8eaed', 'Highlight': '#4f8df7', 'HighlightedText': '#ffffff',
             'ToolTipBase': '#262b33', 'ToolTipText': '#e8eaed', 'PlaceholderText': '#6b7280',
             'Link': '#6aa0f8', 'Mid': '#3b414a', 'Midlight': '#2f343b', 'Dark': '#0f1114',
             'Light': '#353a42', 'Shadow': '#000000', 'disabled': '#6b7280'},
}


_mode = 'auto'


def set_mode(mode):
    """'auto' (follow QGIS), 'light' or 'dark' for the whole panel and its charts."""
    global _mode
    _mode = mode if mode in MODES else 'auto'


def mode():
    return _mode


def is_dark(widget=None):
    if _mode != 'auto':
        return _mode == 'dark'
    src = widget if widget is not None else QApplication.instance()
    return src.palette().color(QPalette.ColorRole.Window).lightness() < 128


def tokens(widget=None):
    """Colour tokens for the current theme, plus surface / window / text colours."""
    if _mode != 'auto':
        spec = _PALETTES[_mode]
        t = dict(DARK if _mode == 'dark' else LIGHT)
        t.update(surface=spec['Base'], window=spec['Window'], text=spec['Text'])
        return t
    src = widget if widget is not None else QApplication.instance()
    pal = src.palette()
    t = dict(DARK if is_dark(widget) else LIGHT)
    t['surface'] = pal.color(QPalette.ColorRole.Base).name()
    t['window'] = pal.color(QPalette.ColorRole.Window).name()
    t['text'] = pal.color(QPalette.ColorRole.Text).name()
    return t


# ---------------------------------------------------------------------------
# Units & formatting
# ---------------------------------------------------------------------------

def rgba(hex_color, alpha):
    """'#rrggbb' + alpha (0-1) -> 'rgba(r, g, b, a)' for Qt style sheets."""
    h = hex_color.lstrip('#')
    return 'rgba({}, {}, {}, {})'.format(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16),
                                         int(round(alpha * 255)))


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
