# -*- coding: utf-8 -*-
"""Small presentational widgets: cards, stat tiles, banners, segmented buttons."""

from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QFont
from qgis.PyQt.QtWidgets import (QButtonGroup, QFrame, QGridLayout, QHBoxLayout,
                                 QLabel, QPushButton, QSizePolicy, QToolButton,
                                 QVBoxLayout, QWidget)

from . import theme


def stylesheet(widget):
    """Plugin-wide style sheet, derived from the current palette."""
    t = theme.tokens(widget)
    return """
    QFrame#rcCard {{
        background: palette(base);
        border: 1px solid {border};
        border-radius: 8px;
    }}
    QLabel#rcCardTitle {{ font-weight: 600; }}
    QLabel#rcHint {{ color: {muted}; }}
    QLabel#rcTileLabel {{ color: {muted}; }}
    QFrame#rcTile {{
        background: palette(base);
        border: 1px solid {border};
        border-radius: 6px;
    }}
    QPushButton#rcPrimary {{
        background: {accent}; color: white; border: none; border-radius: 5px;
        padding: 7px 14px; font-weight: 600;
    }}
    QPushButton#rcPrimary:hover {{ background: {accent_hover}; }}
    QPushButton#rcPrimary:disabled {{ background: {axis}; color: {muted}; }}
    QToolButton#rcSegment {{
        border: 1px solid {border}; padding: 5px 10px; background: palette(base);
    }}
    QToolButton#rcSegment:checked {{
        background: {accent}; color: white; border-color: {accent};
    }}
    QToolButton#rcSegmentLeft {{
        border: 1px solid {border}; padding: 5px 10px; background: palette(base);
        border-top-left-radius: 5px; border-bottom-left-radius: 5px;
    }}
    QToolButton#rcSegmentLeft:checked {{
        background: {accent}; color: white; border-color: {accent};
    }}
    QToolButton#rcSegmentRight {{
        border: 1px solid {border}; padding: 5px 10px; background: palette(base);
        border-top-right-radius: 5px; border-bottom-right-radius: 5px;
    }}
    QToolButton#rcSegmentRight:checked {{
        background: {accent}; color: white; border-color: {accent};
    }}
    QFrame#rcBanner_info {{
        background: palette(base); border: 1px solid {border};
        border-left: 4px solid {accent}; border-radius: 4px;
    }}
    QFrame#rcBanner_warning {{
        background: palette(base); border: 1px solid {border};
        border-left: 4px solid {warning}; border-radius: 4px;
    }}
    QFrame#rcBanner_critical {{
        background: palette(base); border: 1px solid {border};
        border-left: 4px solid {critical}; border-radius: 4px;
    }}
    """.format(**t)


def scaled_font(widget, factor=1.0, weight=None):
    f = QFont(widget.font())
    size = f.pointSizeF()
    if size > 0:
        f.setPointSizeF(size * factor)
    if weight is not None:
        f.setWeight(weight)
    return f


class Card(QFrame):
    """Rounded container with a title and an optional hint line."""

    def __init__(self, title, hint=None, parent=None):
        super().__init__(parent)
        self.setObjectName('rcCard')
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 12)
        lay.setSpacing(8)
        head = QLabel(title)
        head.setObjectName('rcCardTitle')
        head.setFont(scaled_font(self, 1.08, QFont.Weight.DemiBold))
        lay.addWidget(head)
        if hint:
            h = QLabel(hint)
            h.setObjectName('rcHint')
            h.setWordWrap(True)
            lay.addWidget(h)
        self.body = lay


class StatTile(QFrame):
    """Label / value / unit tile (value in semibold, label muted)."""

    def __init__(self, label, unit='', tooltip=None, parent=None):
        super().__init__(parent)
        self.setObjectName('rcTile')
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 7, 10, 8)
        lay.setSpacing(1)
        self.label = QLabel(label)
        self.label.setObjectName('rcTileLabel')
        self.label.setFont(scaled_font(self, 0.9))
        row = QHBoxLayout()
        row.setSpacing(4)
        self.value = QLabel('–')
        self.value.setFont(scaled_font(self, 1.3, QFont.Weight.DemiBold))
        self.value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.unit = QLabel(unit)
        self.unit.setObjectName('rcTileLabel')
        self.unit.setFont(scaled_font(self, 0.9))
        row.addWidget(self.value)
        row.addWidget(self.unit, 0, Qt.AlignmentFlag.AlignBottom)
        row.addStretch(1)
        lay.addWidget(self.label)
        lay.addLayout(row)
        if tooltip:
            self.setToolTip(tooltip)

    def set(self, text, unit=None):
        self.value.setText(text)
        if unit is not None:
            self.unit.setText(unit)


class TileGrid(QWidget):
    """Responsive-ish grid of :class:`StatTile` (fixed column count)."""

    def __init__(self, columns=3, parent=None):
        super().__init__(parent)
        self.columns = columns
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(6)
        self.tiles = {}
        self._n = 0

    def add(self, key, label, unit='', tooltip=None):
        tile = StatTile(label, unit, tooltip)
        self.grid.addWidget(tile, self._n // self.columns, self._n % self.columns)
        self._n += 1
        self.tiles[key] = tile
        return tile

    def set(self, key, text, unit=None):
        self.tiles[key].set(text, unit)

    def set_visible(self, key, visible):
        self.tiles[key].setVisible(visible)


class Banner(QFrame):
    """Inline message (info / warning / critical) with a coloured edge."""

    def __init__(self, level, text, parent=None):
        super().__init__(parent)
        self.setObjectName('rcBanner_' + level)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 6)
        icon = {'info': 'ℹ', 'warning': '⚠', 'critical': '⛔'}.get(level, 'ℹ')
        ic = QLabel(icon)
        ic.setFont(scaled_font(self, 1.1))
        lab = QLabel(text)
        lab.setWordWrap(True)
        lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(ic, 0, Qt.AlignmentFlag.AlignTop)
        lay.addWidget(lab, 1)


class Segmented(QWidget):
    """Exclusive row of toggle buttons (like a segmented control)."""

    changed = pyqtSignal(int)

    def __init__(self, labels, icons=None, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons = []
        for i, text in enumerate(labels):
            b = QToolButton()
            b.setText(text)
            b.setCheckable(True)
            b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            if icons and icons[i] is not None:
                b.setIcon(icons[i])
            if i == 0:
                b.setObjectName('rcSegmentLeft')
            elif i == len(labels) - 1:
                b.setObjectName('rcSegmentRight')
            else:
                b.setObjectName('rcSegment')
            self.group.addButton(b, i)
            lay.addWidget(b)
            self.buttons.append(b)
        self.buttons[0].setChecked(True)
        self.group.buttonClicked.connect(lambda b: self.changed.emit(self.buttons.index(b)))

    def index(self):
        for i, b in enumerate(self.buttons):
            if b.isChecked():
                return i
        return 0

    def set_index(self, i):
        self.buttons[i].setChecked(True)
        self.changed.emit(i)


def primary_button(text):
    b = QPushButton(text)
    b.setObjectName('rcPrimary')
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b


def hint(text):
    lab = QLabel(text)
    lab.setObjectName('rcHint')
    lab.setWordWrap(True)
    return lab
