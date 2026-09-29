# -*- coding: utf-8 -*-
"""Small presentational widgets: cards, pill switches, chips, banners and the
result summary.  Everything is styled by :func:`stylesheet` from the theme
tokens, so light and dark QGIS themes both work."""

import os

from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QFont
from qgis.PyQt.QtWidgets import (QButtonGroup, QFrame, QGridLayout, QHBoxLayout,
                                 QLabel, QPushButton, QSizePolicy, QToolButton,
                                 QVBoxLayout, QWidget)

from ..core.i18n import tr
from . import theme

_UI_ICONS = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'icons', 'ui').replace('\\', '/')


def stylesheet(widget):
    """Plugin-wide style sheet, derived from the current palette."""
    t = theme.tokens(widget)
    t.update(
        # Colour roles: blue/teal = water and data only; neutral ink = interface
        # (selection, badges, chips); azure-to-royal-blue gradient = the action.
        warning_tint=theme.rgba(t['warning'], 0.14),
        critical_tint=theme.rgba(t['critical'], 0.12),
        hover=theme.rgba(t['ink'], 0.05),
        ink_tint=theme.rgba(t['ink'], 0.07),
        ink_soft=theme.rgba(t['ink'], 0.28),
        action_tint=theme.rgba(t['action'], 0.12),
        action_text=t['action_hover'],     # darker in light theme, lighter in dark
        icons=_UI_ICONS,
    )
    return """
    QWidget#rcRoot {{ background: {window}; }}
    QScrollArea#rcScroll, QWidget#rcPage {{ background: transparent; }}
    QLabel {{ color: {text}; }}
    QFrame#rcCard {{
        background: {surface};
        border: 1px solid {border};
        border-radius: 14px;
    }}
    QLabel#rcCardTitle {{ color: {ink}; }}
    QLabel#rcHint {{ color: {muted}; }}
    QLabel#rcStep {{
        background: {track}; color: {ink2}; border-radius: 11px; font-weight: 700;
    }}
    QLabel#rcOverline {{ color: {muted}; }}
    QLabel#rcHeroValue {{ color: {ink}; }}
    QLabel#rcUnit {{ color: {muted}; }}
    QLabel#rcMiniValue {{ color: {ink}; }}

    QFrame#rcMini {{
        background: {track}; border: none; border-radius: 10px;
    }}
    QLabel#rcChip {{
        background: {track}; color: {ink2}; border-radius: 9px; padding: 2px 8px;
    }}
    QLabel#rcChipAccent {{
        background: {track}; color: {ink}; border-radius: 9px; padding: 2px 8px;
        font-weight: 600;
    }}

    QPushButton#rcPrimary {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                    stop:0 {action}, stop:1 {action2});
        color: white; border: none; border-radius: 10px;
        padding: 9px 18px; font-weight: 700; min-height: 16px;
    }}
    QPushButton#rcPrimary:hover {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                    stop:0 {action_hover}, stop:1 {action2_hover});
    }}
    QPushButton#rcPrimary:pressed {{ padding-top: 10px; padding-bottom: 8px; }}
    QPushButton#rcPrimary:disabled {{ background: {track}; color: {muted}; }}

    QPushButton#rcPill, QToolButton#rcPill {{
        background: {surface}; color: {ink}; border: 1px solid {border};
        border-radius: 12px; padding: 4px 12px; min-height: 16px;
    }}
    QPushButton#rcPill:hover, QToolButton#rcPill:hover {{ background: {hover}; }}
    QPushButton#rcPill:checked {{
        background: {action_tint}; color: {action_text}; border-color: {action};
        font-weight: 600;
    }}
    QToolButton#rcPill {{ padding-right: 20px; }}
    QToolButton#rcPill::menu-indicator {{ subcontrol-position: right center; right: 7px; }}

    QToolButton#rcIcon {{
        background: {surface}; border: 1px solid {border}; border-radius: 13px;
        min-width: 28px; max-width: 28px; min-height: 28px; max-height: 28px;
    }}
    QToolButton#rcIcon:hover {{ background: {hover}; }}

    QTabWidget#rcViews::pane {{ border: none; }}
    QFrame#rcSegTrack {{ background: {track}; border-radius: 12px; }}
    QToolButton#rcSeg {{
        background: transparent; color: {ink2}; border: none; border-radius: 9px;
        padding: 5px 10px;
    }}
    QToolButton#rcSeg:hover {{ color: {ink}; }}
    QToolButton#rcSeg:checked {{
        background: {select}; color: {select_text}; font-weight: 600; border: none;
    }}

    QFrame#rcBanner_info {{ background: {track}; border: none; border-radius: 10px; }}
    QFrame#rcBanner_warning {{ background: {warning_tint}; border: none; border-radius: 10px; }}
    QFrame#rcBanner_critical {{ background: {critical_tint}; border: none; border-radius: 10px; }}
    QLabel#rcBannerIcon_info {{ color: {ink2}; font-weight: 700; }}
    QLabel#rcBannerIcon_warning {{ color: {warning}; font-weight: 700; }}
    QLabel#rcBannerIcon_critical {{ color: {critical}; font-weight: 700; }}

    QProgressBar#rcProgress {{
        background: {track}; border: none; border-radius: 2px;
    }}
    QProgressBar#rcProgress::chunk {{
        border-radius: 2px;
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {action}, stop:1 {action2});
    }}

    QComboBox, QDoubleSpinBox {{
        background: {surface}; color: {text}; border: 1px solid {border};
        border-radius: 8px; padding: 4px 8px; min-height: 20px;
        selection-background-color: {ink_tint}; selection-color: {text};
    }}
    QComboBox:hover, QDoubleSpinBox:hover {{ border-color: {ink_soft}; }}
    QComboBox:focus, QDoubleSpinBox:focus {{ border-color: {ink2}; }}
    QComboBox:disabled, QDoubleSpinBox:disabled {{ background: {track}; color: {muted}; }}
    QComboBox::drop-down {{
        subcontrol-origin: padding; subcontrol-position: right center;
        width: 22px; border: none;
    }}
    QComboBox::down-arrow {{ image: url({icons}/chevron-down.svg); width: 12px; height: 12px; }}
    QComboBox QAbstractItemView {{
        background: {surface}; color: {text}; border: 1px solid {border};
        border-radius: 8px; padding: 4px; outline: 0;
        selection-background-color: {ink_tint}; selection-color: {text};
    }}
    QDoubleSpinBox {{ padding-right: 22px; }}
    QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
        subcontrol-origin: border; width: 20px; border: none; background: transparent;
    }}
    QDoubleSpinBox::up-button {{ subcontrol-position: top right; margin-top: 2px; }}
    QDoubleSpinBox::down-button {{ subcontrol-position: bottom right; margin-bottom: 2px; }}
    QDoubleSpinBox::up-arrow {{ image: url({icons}/chevron-up.svg); width: 10px; height: 10px; }}
    QDoubleSpinBox::down-arrow {{ image: url({icons}/chevron-down.svg); width: 10px; height: 10px; }}

    QCheckBox {{ color: {text}; spacing: 8px; }}
    QCheckBox:disabled {{ color: {muted}; }}
    QCheckBox::indicator {{
        width: 16px; height: 16px; border-radius: 5px;
        border: 1px solid {axis}; background: {surface};
    }}
    QCheckBox::indicator:hover {{ border-color: {ink2}; }}
    QCheckBox::indicator:checked {{
        background: {select}; border-color: {select}; image: url({icons}/{check_icon});
    }}

    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px 1px; }}
    QScrollBar::handle:vertical {{ background: {axis}; border-radius: 4px; min-height: 32px; }}
    QScrollBar::handle:vertical:hover {{ background: {muted}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}

    QMenu {{
        background: {surface}; color: {text}; border: 1px solid {border};
        border-radius: 10px; padding: 5px;
    }}
    QMenu::item {{ padding: 6px 22px 6px 26px; border-radius: 6px; }}
    QMenu::item:selected {{ background: {ink_tint}; }}
    QMenu::separator {{ height: 1px; background: {border}; margin: 4px 8px; }}
    QMenu::section {{ color: {muted}; padding: 6px 10px 2px 10px; font-weight: 600; }}

    QTableWidget#rcTable {{
        background: {surface}; color: {text}; border: none; gridline-color: transparent;
        alternate-background-color: {track}; selection-background-color: {ink_tint};
        selection-color: {ink};
    }}
    QTableWidget#rcTable QHeaderView::section {{
        background: {surface}; color: {muted}; border: none;
        border-bottom: 1px solid {border}; padding: 6px 6px; font-weight: 600;
    }}
    """.format(**t)


def overline_font(widget, factor=0.8):
    """Small caps-style label font: semibold, slightly tracked."""
    f = scaled_font(widget, factor, QFont.Weight.DemiBold)
    f.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 108)
    return f


def scaled_font(widget, factor=1.0, weight=None):
    f = QFont(widget.font())
    size = f.pointSizeF()
    if size > 0:
        f.setPointSizeF(size * factor)
    if weight is not None:
        f.setWeight(weight)
    return f


class Card(QFrame):
    """Rounded container with a title, an optional step number and hint line."""

    def __init__(self, title, hint=None, step=None, parent=None):
        super().__init__(parent)
        self.setObjectName('rcCard')
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 14)
        lay.setSpacing(9)
        head = QHBoxLayout()
        head.setSpacing(8)
        if step is not None:
            badge = QLabel(str(step))
            badge.setObjectName('rcStep')
            badge.setFixedSize(22, 22)
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            head.addWidget(badge)
        self.title = QLabel(title)
        self.title.setObjectName('rcCardTitle')
        self.title.setFont(scaled_font(self, 1.12, QFont.Weight.DemiBold))
        head.addWidget(self.title, 1)
        self.head = head
        lay.addLayout(head)
        if hint:
            lay.addWidget(_muted_label(hint))
        self.body = lay


class Chip(QLabel):
    """Small rounded tag (``accent`` for a highlighted one)."""

    def __init__(self, text='', accent=False, parent=None):
        super().__init__(text, parent)
        self.setObjectName('rcChipAccent' if accent else 'rcChip')
        self.setFont(scaled_font(self, 0.88))
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)


def _dot(color, size=8):
    d = QLabel()
    d.setFixedSize(size, size)
    d.setStyleSheet('background: {}; border-radius: {}px;'.format(color, size // 2))
    return d


class MiniStat(QFrame):
    """Secondary figure of the result: coloured dot, overline label, value + unit."""

    def __init__(self, label, unit, color, tooltip=None, parent=None):
        super().__init__(parent)
        self.setObjectName('rcMini')
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 9)
        lay.setSpacing(2)
        top = QHBoxLayout()
        top.setSpacing(6)
        self.dot = _dot(color)
        top.addWidget(self.dot, 0, Qt.AlignmentFlag.AlignVCenter)
        lab = QLabel(label.upper())
        lab.setObjectName('rcOverline')
        lab.setFont(overline_font(self, 0.78))
        top.addWidget(lab, 1)
        row = QHBoxLayout()
        row.setSpacing(3)
        self.value = QLabel('–')
        self.value.setObjectName('rcMiniValue')
        self.value.setFont(scaled_font(self, 1.32, QFont.Weight.DemiBold))
        self.value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.unit = QLabel(unit)
        self.unit.setObjectName('rcUnit')
        self.unit.setFont(scaled_font(self, 0.86))
        row.addWidget(self.value)
        row.addWidget(self.unit, 0, Qt.AlignmentFlag.AlignBottom)
        row.addStretch(1)
        lay.addLayout(top)
        lay.addLayout(row)
        if tooltip:
            self.setToolTip(tooltip)

    def set(self, text):
        self.value.setText(text)


class ResultHero(QWidget):
    """The headline of a result: stored volume large, three figures beneath."""

    def __init__(self, colors, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        top = QHBoxLayout()
        top.setSpacing(6)
        over = QLabel(tr('Stored volume').upper())
        over.setObjectName('rcOverline')
        over.setFont(overline_font(self, 0.8))
        top.addWidget(over)
        top.addStretch(1)
        self.chip = Chip('', accent=True)
        self.chip.setVisible(False)
        top.addWidget(self.chip)
        lay.addLayout(top)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.value = QLabel('–')
        self.value.setObjectName('rcHeroValue')
        self.value.setFont(scaled_font(self, 2.6, QFont.Weight.DemiBold))
        self.value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.unit = QLabel('hm³')
        self.unit.setObjectName('rcUnit')
        self.unit.setFont(scaled_font(self, 1.25, QFont.Weight.Medium))
        row.addWidget(self.value, 0, Qt.AlignmentFlag.AlignBottom)
        row.addWidget(self.unit, 0, Qt.AlignmentFlag.AlignBottom)
        row.addStretch(1)
        lay.addLayout(row)
        self.caption = QLabel('')
        self.caption.setObjectName('rcHint')
        self.caption.setWordWrap(True)
        lay.addWidget(self.caption)
        lay.addSpacing(6)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(6)
        self.stats = {
            'level': MiniStat(tr('Water level'), tr('m a.s.l.'), colors['level'],
                              tr('Water level above mean sea level: the ground at the lower '
                                 'end of the line, or your maximum if that is lower')),
            'area': MiniStat(tr('Surface area'), 'km²', colors['area'],
                             tr('Area of the water surface')),
            'depth': MiniStat(tr('Max. depth'), 'm', colors['depth'],
                              tr('Water level − lowest point of the reservoir')),
        }
        for i, w in enumerate(self.stats.values()):
            grid.addWidget(w, 0, i)
        lay.addLayout(grid)

    def set(self, volume, level, area, depth, caption, chip=None):
        self.value.setText(volume)
        self.stats['level'].set(level)
        self.stats['area'].set(area)
        self.stats['depth'].set(depth)
        self.caption.setText(caption)
        self.chip.setText(chip or '')
        self.chip.setVisible(bool(chip))


class Banner(QFrame):
    """Inline message (info / warning / critical) on a softly tinted background."""

    def __init__(self, level, text, parent=None):
        super().__init__(parent)
        self.setObjectName('rcBanner_' + level)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 7, 10, 7)
        lay.setSpacing(8)
        icon = {'info': 'i', 'warning': '!', 'critical': '×'}.get(level, 'i')
        ic = QLabel(icon)
        ic.setObjectName('rcBannerIcon_' + level)
        ic.setFixedWidth(10)
        ic.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        ic.setFont(scaled_font(self, 1.05, QFont.Weight.Bold))
        lab = QLabel(text)
        lab.setWordWrap(True)
        lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(ic, 0, Qt.AlignmentFlag.AlignTop)
        lay.addWidget(lab, 1)


class Segmented(QFrame):
    """Exclusive pill switch: a rounded track with a raised selected segment."""

    changed = pyqtSignal(int)

    def __init__(self, labels, icons=None, parent=None):
        super().__init__(parent)
        self.setObjectName('rcSegTrack')
        lay = QHBoxLayout(self)
        lay.setContentsMargins(3, 3, 3, 3)
        lay.setSpacing(2)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons = []
        for i, text in enumerate(labels):
            b = QToolButton()
            b.setObjectName('rcSeg')
            b.setText(text)
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            if icons and icons[i] is not None:
                b.setIcon(icons[i])
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


def pill_button(text, icon=None, tool=False):
    b = QToolButton() if tool else QPushButton()
    b.setObjectName('rcPill')
    b.setText(text)
    if icon is not None:
        b.setIcon(icon)
    if tool:
        b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b


def icon_button(icon, tooltip):
    b = QToolButton()
    b.setObjectName('rcIcon')
    b.setIcon(icon)
    b.setToolTip(tooltip)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b


def _muted_label(text):
    lab = QLabel(text)
    lab.setObjectName('rcHint')
    lab.setWordWrap(True)
    return lab


hint = _muted_label
