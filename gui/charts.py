# -*- coding: utf-8 -*-
"""
Interactive matplotlib charts for the reservoir panel.

* :class:`CurveChart`   - surface area and volume against water level
  (two panels sharing the elevation axis).
* :class:`ProfileChart` - ground along the drawn line, its two ends and the
  resulting water level (= the lower end).

Both charts show a hover crosshair with a tooltip.  Styling follows the QGIS
light/dark theme and never touches matplotlib's global rcParams.
"""

import numpy as np
from qgis.PyQt.QtWidgets import QSizePolicy, QVBoxLayout, QWidget

try:  # matplotlib >= 3.5 picks the Qt binding already loaded (Qt5 or Qt6)
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
except ImportError:  # pragma: no cover - old matplotlib, Qt5 only
    from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter, MaxNLocator
from matplotlib.transforms import blended_transform_factory

from . import theme

FONT = 8.5
TITLE_FONT = 9.0


def _num(x, _pos=None):
    if abs(x) >= 100:
        return '{:,.0f}'.format(x)
    if abs(x) >= 10:
        return '{:,.1f}'.format(x).rstrip('0').rstrip('.')
    return '{:,.2f}'.format(x).rstrip('0').rstrip('.')


class BaseChart(QWidget):

    def __init__(self, parent=None, min_height=300):
        super().__init__(parent)
        try:
            self.figure = Figure(figsize=(4.0, 3.2), layout='constrained')
        except TypeError:  # matplotlib < 3.6
            self.figure = Figure(figsize=(4.0, 3.2), constrained_layout=True)
        self.canvas = FigureCanvas(self.figure)
        self.canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.canvas.setMinimumHeight(min_height)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.canvas)
        self.t = theme.tokens(self)
        self.tip = None
        self.has_data = False
        self.canvas.mpl_connect('motion_notify_event', self._on_move)
        self.canvas.mpl_connect('figure_leave_event', self._on_leave)
        self.canvas.mpl_connect('axes_leave_event', self._on_leave)
        self.show_empty('Draw a line across a valley to see this chart.')

    def _reset(self):
        self.t = theme.tokens(self)
        self.figure.clear()
        self.figure.set_facecolor(self.t['surface'])
        self.tip = self.figure.text(
            0, 0, '', fontsize=FONT, color=self.t['ink'], zorder=20, visible=False,
            va='bottom', ha='left', linespacing=1.5,
            bbox=dict(boxstyle='round,pad=0.55', fc=self.t['surface'],
                      ec=self.t['axis'], lw=0.8))

    def style(self, ax, title=None, xlabel=None, ylabel=None):
        t = self.t
        ax.set_facecolor(t['surface'])
        for side in ('top', 'right'):
            ax.spines[side].set_visible(False)
        for side in ('left', 'bottom'):
            ax.spines[side].set_color(t['axis'])
            ax.spines[side].set_linewidth(0.8)
        ax.tick_params(colors=t['axis'], labelcolor=t['ink2'], labelsize=FONT - 0.5,
                       length=3, width=0.8)
        ax.grid(True, color=t['grid'], linewidth=0.8, linestyle='-')
        ax.set_axisbelow(True)
        ax.xaxis.set_major_locator(MaxNLocator(5))
        ax.yaxis.set_major_locator(MaxNLocator(6))
        ax.xaxis.set_major_formatter(FuncFormatter(_num))
        ax.yaxis.set_major_formatter(FuncFormatter(_num))
        if title:
            ax.set_title(title, loc='left', fontsize=TITLE_FONT, color=t['ink'],
                         fontweight='semibold', pad=6)
        if xlabel:
            ax.set_xlabel(xlabel, fontsize=FONT, color=t['ink2'])
        if ylabel:
            ax.set_ylabel(ylabel, fontsize=FONT, color=t['ink2'])

    def dot(self, ax, color):
        (d,) = ax.plot([], [], 'o', ms=8, mfc=color, mec=self.t['surface'], mew=2,
                       zorder=15, visible=False)
        return d

    def label(self, ax, x, y, text, ha='left', va='bottom', strong=False, dx=0, dy=0):
        return ax.annotate(text, (x, y), xytext=(dx, dy), textcoords='offset points',
                           ha=ha, va=va, fontsize=FONT - 0.5, zorder=12,
                           color=self.t['ink'] if strong else self.t['ink2'],
                           fontweight='semibold' if strong else 'normal',
                           bbox=dict(boxstyle='square,pad=0.15', fc=self.t['surface'],
                                     ec='none', alpha=0.85))

    def show_empty(self, text):
        self._reset()
        self.has_data = False
        self.figure.text(0.5, 0.5, text, ha='center', va='center', fontsize=FONT + 0.5,
                         color=self.t['muted'])
        self.canvas.draw_idle()

    def show_tip(self, event, text):
        w, h = self.figure.bbox.width, self.figure.bbox.height
        right = event.x > 0.55 * w
        x = (event.x - 14) / w if right else (event.x + 14) / w
        y = min(max(event.y / h, 0.05), 0.72)
        self.tip.set_text(text)
        self.tip.set_position((x, y))
        self.tip.set_ha('right' if right else 'left')
        self.tip.set_visible(True)

    def hide_hover(self):
        pass

    def _on_leave(self, _event):
        if not self.has_data:
            return
        self.tip.set_visible(False)
        self.hide_hover()
        self.canvas.draw_idle()

    def _on_move(self, event):
        pass

    def save_png(self, path):
        self.figure.savefig(path, dpi=200, facecolor=self.t['surface'])


class CurveChart(BaseChart):
    """Surface area and volume against water level."""

    def set_data(self, levels, area_m2, volume_m3, water_level):
        self._reset()
        t = self.t
        self.levels = np.asarray(levels, dtype=float)
        self.A = np.asarray(area_m2, dtype=float) / 1e6
        self.V = np.asarray(volume_m3, dtype=float) / 1e6
        ax_a, ax_v = self.figure.subplots(1, 2, sharey=True,
                                          gridspec_kw={'width_ratios': [1.0, 1.2]})
        self.ax_a, self.ax_v = ax_a, ax_v
        self.style(ax_a, 'Surface area · km²', ylabel='Water level (m)')
        self.style(ax_v, 'Volume · million m³')
        ax_v.tick_params(labelleft=False)
        span = max(1.0, self.levels[-1] - self.levels[0])
        for ax, x, col in ((ax_a, self.A, t['area']), (ax_v, self.V, t['storage'])):
            ax.fill_betweenx(self.levels, 0, x, color=col, alpha=0.10, lw=0)
            ax.plot(x, self.levels, color=col, lw=2, solid_capstyle='round')
            ax.set_xlim(0, max(x.max() * 1.08, 1e-6))
            ax.set_ylim(self.levels[0] - 0.01 * span, self.levels[-1] + 0.06 * span)
            ax.axhline(water_level, color=t['ink'], lw=1.2)
        self.label(ax_a, 0, water_level, 'Water level {:.1f} m'.format(water_level),
                   strong=True, dx=4, dy=2)
        for ax, x, col in ((ax_a, self.A, t['area']), (ax_v, self.V, t['storage'])):
            ax.plot([x[-1]], [water_level], 'o', ms=8, mfc=col, mec=t['surface'], mew=2,
                    zorder=14)
        self.hl = [ax.axhline(self.levels[0], color=t['ink2'], lw=0.8, visible=False)
                   for ax in (ax_a, ax_v)]
        self.hdots = [self.dot(ax_a, t['area']), self.dot(ax_v, t['storage'])]
        self.has_data = True
        self.canvas.draw_idle()

    def hide_hover(self):
        for a in self.hl + self.hdots:
            a.set_visible(False)

    def _on_move(self, event):
        if not self.has_data or event.inaxes not in (self.ax_a, self.ax_v) or event.ydata is None:
            return
        y = float(np.clip(event.ydata, self.levels[0], self.levels[-1]))
        a = float(np.interp(y, self.levels, self.A))
        v = float(np.interp(y, self.levels, self.V))
        for ln in self.hl:
            ln.set_ydata([y, y])
            ln.set_visible(True)
        self.hdots[0].set_data([a], [y])
        self.hdots[1].set_data([v], [y])
        for d in self.hdots:
            d.set_visible(True)
        self.show_tip(event, 'Water level  {:.2f} m\nSurface area  {} km²\n'
                             'Volume  {} million m³'.format(
                                 y, theme.fmt_sig(a, 3), theme.fmt_sig(v, 4)))
        self.canvas.draw_idle()


class ProfileChart(BaseChart):
    """Ground along the drawn line; the lower end sets the water level."""

    def set_data(self, stations, ground, water_level):
        self._reset()
        t = self.t
        self.st = np.asarray(stations, dtype=float)
        self.g = np.asarray(ground, dtype=float)
        self.level = water_level
        ax = self.figure.subplots()
        self.ax = ax
        self.style(ax, xlabel='Distance along the line (m)', ylabel='Elevation (m)')
        gmin, gmax = np.nanmin(self.g), np.nanmax(self.g)
        pad = 0.08 * max(1.0, gmax - gmin)
        base = gmin - pad
        wet = self.g < water_level
        ax.fill_between(self.st, self.g, water_level, where=wet, interpolate=True,
                        color=t['water_fill'], alpha=0.55, lw=0, zorder=3)
        ax.fill_between(self.st, base, self.g, color=t['ground_fill'], lw=0, zorder=2)
        ax.plot(self.st, self.g, color=t['ground'], lw=1.6, zorder=6)
        ax.axhline(water_level, color=t['storage'], lw=1.4, zorder=7)
        # the two ends of the line
        ends = ((self.st[0], self.g[0], 'left'), (self.st[-1], self.g[-1], 'right'))
        low = min(ends, key=lambda e: e[1])
        for s, z, ha in ends:
            is_low = (s, z) == (low[0], low[1])
            ax.plot([s], [z], 'o', ms=9, mfc=t['storage'] if is_low else t['ground'],
                    mec=t['surface'], mew=2, zorder=12, clip_on=False)
            self.label(ax, s, z, 'End {:.1f} m{}'.format(z, ' (lower)' if is_low else ''),
                       ha=ha, va='bottom', strong=is_low, dx=6 if ha == 'left' else -6, dy=6)
        tr = blended_transform_factory(ax.transAxes, ax.transData)
        ax.text(0.5, water_level, 'Water level {:.1f} m = lower end of the line'
                .format(water_level), transform=tr, ha='center', va='top', fontsize=FONT - 0.5,
                color=t['ink'], zorder=12,
                bbox=dict(boxstyle='square,pad=0.2', fc=t['surface'], ec='none', alpha=0.85))
        ax.set_xlim(self.st[0], self.st[-1])
        ax.set_ylim(base, gmax + pad)
        self.vl = ax.axvline(0, color=t['ink2'], lw=0.8, visible=False)
        self.gdot = self.dot(ax, t['ground'])
        self.has_data = True
        self.canvas.draw_idle()

    def hide_hover(self):
        self.vl.set_visible(False)
        self.gdot.set_visible(False)

    def _on_move(self, event):
        if not self.has_data or event.inaxes is not self.ax or event.xdata is None:
            return
        s = float(np.clip(event.xdata, self.st[0], self.st[-1]))
        g = float(np.interp(s, self.st, self.g))
        self.vl.set_xdata([s, s])
        self.vl.set_visible(True)
        self.gdot.set_data([s], [g])
        self.gdot.set_visible(True)
        text = 'Distance  {:,.0f} m\nGround  {:.1f} m'.format(s, g)
        if g < self.level:
            text += '\nWater depth  {:.1f} m'.format(self.level - g)
        self.show_tip(event, text)
        self.canvas.draw_idle()
