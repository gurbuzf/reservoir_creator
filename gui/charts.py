# -*- coding: utf-8 -*-
"""
Interactive matplotlib charts for the reservoir dock.

* :class:`CapacityChart` - elevation-area-capacity curves as two panels
  sharing the elevation axis (area | storage), with reference levels
  (normal water level, minimum operating level, maximum impoundable level).
* :class:`SectionChart`  - ground profile along the dam axis with the dam
  body, crest, water level and dam height.
* :class:`SizingChart`   - embankment fill and storage-to-fill ratio against
  the normal water level, to help choose the dam height.

Every chart has a hover crosshair with a tooltip; a click emits
``levelPicked`` so the user can set the water level straight from the plot.
Styling follows the QGIS light/dark theme and never touches matplotlib's
global rcParams.
"""

import numpy as np
from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtWidgets import QSizePolicy, QVBoxLayout, QWidget

try:  # matplotlib >= 3.5 selects the Qt binding already loaded (Qt5 or Qt6)
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
except ImportError:  # pragma: no cover - old matplotlib, Qt5 only
    from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from matplotlib.ticker import FuncFormatter, MaxNLocator
from matplotlib.transforms import blended_transform_factory

from . import theme

FONT = 8.5
TITLE_FONT = 9.0


def _thousands(x, _pos=None):
    if abs(x) >= 100:
        return '{:,.0f}'.format(x)
    if abs(x) >= 10:
        return '{:,.1f}'.format(x).rstrip('0').rstrip('.')
    return '{:,.2f}'.format(x).rstrip('0').rstrip('.')


class BaseChart(QWidget):
    levelPicked = pyqtSignal(float)

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
        self.canvas.mpl_connect('button_press_event', self._on_click)
        self.show_empty('Run an analysis to see this chart.')

    # -- helpers ---------------------------------------------------------------
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
        ax.xaxis.set_major_formatter(FuncFormatter(_thousands))
        ax.yaxis.set_major_formatter(FuncFormatter(_thousands))
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
        if self.tip is not None:
            self.tip.set_visible(False)
        self.hide_hover()
        self.canvas.draw_idle()

    def _on_move(self, event):
        pass

    def _on_click(self, event):
        pass

    def save_png(self, path):
        self.figure.savefig(path, dpi=200, facecolor=self.t['surface'])


# ---------------------------------------------------------------------------
# Elevation - area - capacity
# ---------------------------------------------------------------------------

class CapacityChart(BaseChart):
    """Area and storage against water level, as two panels (shared y)."""

    def set_data(self, levels, area_m2, volume_m3, nwl, max_level, bed_level, mol=None):
        self._reset()
        t = self.t
        self.levels = np.asarray(levels, dtype=float)
        self.A = np.asarray(area_m2, dtype=float) / 1e6
        self.V = np.asarray(volume_m3, dtype=float) / 1e6
        ax_a, ax_v = self.figure.subplots(1, 2, sharey=True,
                                          gridspec_kw={'width_ratios': [1.0, 1.2]})
        self.ax_a, self.ax_v = ax_a, ax_v
        self.style(ax_a, 'Surface area · km²', ylabel='Water level (m)')
        self.style(ax_v, 'Storage · hm³')
        ax_v.tick_params(labelleft=False)

        pad = 0.04 * max(1.0, max_level - bed_level)
        for ax, x, col in ((ax_a, self.A, t['area']), (ax_v, self.V, t['storage'])):
            ax.fill_betweenx(self.levels, 0, x, color=col, alpha=0.10, lw=0)
            ax.plot(x, self.levels, color=col, lw=2, solid_capstyle='round',
                    solid_joinstyle='round')
            ax.set_xlim(0, max(x.max() * 1.06, 1e-6))
            ax.set_ylim(bed_level - pad * 0.3, max_level + pad)

        # dead storage zone
        if mol is not None and bed_level < mol < max_level:
            for ax in (ax_a, ax_v):
                ax.axhspan(bed_level - pad, mol, color=t['muted'], alpha=0.10, lw=0)
            self._ref_label(ax_a, mol, 'MOL {:.1f} m · dead storage below'.format(mol),
                            below=True)
            for ax in (ax_a, ax_v):
                ax.axhline(mol, color=t['muted'], lw=1, ls=':')

        # maximum impoundable level
        for ax in (ax_a, ax_v):
            ax.axhline(max_level, color=t['muted'], lw=1, ls='--')
        self._ref_label(ax_v, max_level, 'Max. impoundable {:.1f} m'.format(max_level))

        # normal water level (movable)
        self.nwl_lines = [ax.axhline(nwl, color=t['ink'], lw=1.3) for ax in (ax_a, ax_v)]
        self.nwl_label = self._ref_label(ax_a, nwl, '', below=True, strong=True)
        self.nwl_dots = [self.dot(ax_a, t['area']), self.dot(ax_v, t['storage'])]
        for d, x in zip(self.nwl_dots, (self.A, self.V)):
            d.set_visible(True)
        self.set_nwl(nwl, draw=False)

        # hover artists
        self.hl = [ax.axhline(bed_level, color=t['ink2'], lw=0.8, visible=False)
                   for ax in (ax_a, ax_v)]
        self.hdots = [self.dot(ax_a, t['area']), self.dot(ax_v, t['storage'])]
        self.has_data = True
        self.canvas.draw_idle()

    def _ref_label(self, ax, y, text, below=False, strong=False):
        tr = blended_transform_factory(ax.transAxes, ax.transData)
        return ax.text(0.02, y, text, transform=tr, ha='left',
                       va='top' if below else 'bottom', fontsize=FONT - 0.5,
                       color=self.t['ink'] if strong else self.t['ink2'],
                       fontweight='semibold' if strong else 'normal', zorder=12,
                       bbox=dict(boxstyle='square,pad=0.15', fc=self.t['surface'],
                                 ec='none', alpha=0.85))

    def set_nwl(self, nwl, draw=True):
        if not self.has_data and draw:
            return
        a = float(np.interp(nwl, self.levels, self.A))
        v = float(np.interp(nwl, self.levels, self.V))
        for ln in self.nwl_lines:
            ln.set_ydata([nwl, nwl])
        self.nwl_label.set_y(nwl)
        self.nwl_label.set_text('NWL {:.1f} m'.format(nwl))
        self.nwl_dots[0].set_data([a], [nwl])
        self.nwl_dots[1].set_data([v], [nwl])
        if draw:
            self.canvas.draw_idle()

    def hide_hover(self):
        for a in self.hl + self.hdots:
            a.set_visible(False)

    def _level_at(self, event):
        if not self.has_data or event.inaxes not in (self.ax_a, self.ax_v) or event.ydata is None:
            return None
        return float(np.clip(event.ydata, self.levels[0], self.levels[-1]))

    def _on_move(self, event):
        y = self._level_at(event)
        if y is None:
            return
        a = float(np.interp(y, self.levels, self.A))
        v = float(np.interp(y, self.levels, self.V))
        for ln in self.hl:
            ln.set_ydata([y, y])
            ln.set_visible(True)
        self.hdots[0].set_data([a], [y])
        self.hdots[1].set_data([v], [y])
        for d in self.hdots:
            d.set_visible(True)
        depth = v / a * 1.0 if a > 0 else 0.0
        self.show_tip(event, 'Water level  {:.2f} m\nSurface area  {} km²\nStorage  {} hm³\n'
                             'Mean depth  {:.1f} m\n(click to set NWL)'.format(
                                 y, theme.fmt_sig(a, 3), theme.fmt_sig(v, 4), depth))
        self.canvas.draw_idle()

    def _on_click(self, event):
        y = self._level_at(event)
        if y is not None and event.button == 1:
            self.levelPicked.emit(y)


# ---------------------------------------------------------------------------
# Dam axis section
# ---------------------------------------------------------------------------

class SectionChart(BaseChart):
    """Ground along the dam axis, dam body, crest and water level."""

    def set_data(self, stations, ground, nwl, crest, info):
        self._reset()
        t = self.t
        self.st = np.asarray(stations, dtype=float)
        self.g = np.asarray(ground, dtype=float)
        self.nwl, self.crest = nwl, crest
        ax = self.figure.subplots()
        self.ax = ax
        self.style(ax, xlabel='Distance along dam axis (m)', ylabel='Elevation (m)')
        gmin = np.nanmin(self.g)
        top = max(np.nanmax(self.g), crest)
        pad = 0.06 * max(1.0, top - gmin)
        base = gmin - pad

        ax.fill_between(self.st, base, self.g, color=t['ground_fill'], lw=0, zorder=2)
        ax.plot(self.st, self.g, color=t['ground'], lw=1.6, zorder=6)
        below_crest = self.g < crest
        ax.fill_between(self.st, self.g, crest, where=below_crest, interpolate=True,
                        color=t['dam'], alpha=0.22, lw=0, zorder=3)
        ax.plot(self.st, np.where(below_crest, crest, np.nan), color=t['dam'], lw=2, zorder=7,
                solid_capstyle='round')
        wet = self.g < nwl
        ax.plot(self.st, np.where(wet, nwl, np.nan), color=t['storage'], lw=1.6, zorder=8,
                solid_capstyle='round')

        # dam height dimension at the thalweg
        k = int(np.nanargmin(self.g))
        ts, tz = self.st[k], self.g[k]
        ax.annotate('', xy=(ts, crest), xytext=(ts, tz), zorder=9,
                    arrowprops=dict(arrowstyle='<->', color=t['ink2'], lw=0.9,
                                    shrinkA=0, shrinkB=0))
        ax.text(ts, tz + 0.4 * (crest - tz), '  H = {:.0f} m'.format(crest - tz), ha='left',
                va='center', fontsize=FONT, color=t['ink'], fontweight='semibold', zorder=10,
                bbox=dict(boxstyle='square,pad=0.15', fc=t['surface'], ec='none', alpha=0.8))

        wet_st = self.st[wet] if wet.any() else self.st
        mid = 0.5 * (wet_st[0] + wet_st[-1])
        box = dict(boxstyle='square,pad=0.15', fc=t['surface'], ec='none', alpha=0.85)
        ax.annotate('Crest {:.1f} m · {:,.0f} m long'.format(crest, info['crest_length']),
                    (mid, crest), xytext=(0, 4), textcoords='offset points', ha='center',
                    va='bottom', fontsize=FONT - 0.5, color=t['ink'], zorder=10, bbox=box)
        ax.annotate('NWL {:.1f} m'.format(nwl), (mid, nwl), xytext=(0, -4),
                    textcoords='offset points', ha='center', va='top', fontsize=FONT - 0.5,
                    color=t['ink2'], zorder=10, bbox=box)
        if info.get('axis_too_short'):
            for i in (0, -1):
                if self.g[i] < crest:
                    ax.plot([self.st[i]], [self.g[i]], 'o', ms=8, mfc=t['critical'],
                            mec=t['surface'], mew=2, zorder=11)
            ax.text(0.5, 0.02, '⚠ Crest is above the ground at a dam end - extend the axis',
                    transform=ax.transAxes, ha='center', va='bottom', fontsize=FONT - 0.5,
                    color=t['ink'], zorder=10)

        ax.set_xlim(self.st[0], self.st[-1])
        ax.set_ylim(base, top + pad)
        ax.legend(handles=[Patch(color=t['ground_fill'], label='Ground'),
                           Patch(color=t['dam'], alpha=0.45, label='Dam body'),
                           Line2D([], [], color=t['dam'], lw=2, label='Crest'),
                           Line2D([], [], color=t['storage'], lw=1.6, label='NWL')],
                  loc='lower left', bbox_to_anchor=(0, 1.0), ncol=4, frameon=False,
                  fontsize=FONT - 0.5, handlelength=1.2, handleheight=0.8,
                  borderaxespad=0.2, labelcolor=t['ink2'])
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
        lines = ['Distance  {:,.0f} m'.format(s), 'Ground  {:.1f} m'.format(g)]
        if g < self.crest:
            lines.append('Dam height here  {:.1f} m'.format(self.crest - g))
        if g < self.nwl:
            lines.append('Water depth at dam  {:.1f} m'.format(self.nwl - g))
        self.show_tip(event, '\n'.join(lines))
        self.canvas.draw_idle()


# ---------------------------------------------------------------------------
# Dam sizing
# ---------------------------------------------------------------------------

class SizingChart(BaseChart):
    """Embankment fill and storage/fill ratio versus normal water level."""

    def __init__(self, parent=None):
        super().__init__(parent, min_height=340)

    def set_data(self, sizing, nwl, freeboard):
        self._reset()
        t = self.t
        self.s = sizing
        self.freeboard = freeboard
        x = sizing['nwl']
        if len(x) < 2:
            self.show_empty('Not enough levels to size the dam.')
            return
        fill = sizing['fill'] / 1e6
        # the ratio is meaningless for token dams of a few metres: hide it there
        min_h = max(5.0, 0.15 * float(np.nanmax(sizing['height'])))
        ratio = np.where(sizing['height'] >= min_h, sizing['ratio'], np.nan)
        ax1, ax2 = self.figure.subplots(2, 1, sharex=True)
        self.ax1, self.ax2 = ax1, ax2
        self.style(ax1, 'Embankment fill · hm³')
        self.style(ax2, 'Storage ÷ fill (water-to-fill ratio)',
                   xlabel='Normal water level (m)')
        ax1.tick_params(labelbottom=False)
        for ax, y, col in ((ax1, fill, t['dam']), (ax2, ratio, t['storage'])):
            yy = np.where(np.isfinite(y), y, np.nan)
            ax.fill_between(x, 0, yy, color=col, alpha=0.10, lw=0)
            ax.plot(x, yy, color=col, lw=2, solid_capstyle='round')
            ax.set_ylim(0, np.nanmax(yy) * 1.12 if np.isfinite(yy).any() else 1)
        ax1.set_xlim(x[0], x[-1])

        bad = ~sizing['axis_ok']
        if bad.any():
            x0 = x[np.argmax(bad)]
            for ax in (ax1, ax2):
                ax.axvspan(x0, x[-1], color=t['muted'], alpha=0.12, lw=0)
            ax1.text(0.5 * (x0 + x[-1]), 0.5, 'axis too short', rotation=90,
                     transform=blended_transform_factory(ax1.transData, ax1.transAxes),
                     ha='center', va='center', fontsize=FONT - 1, color=t['ink2'], zorder=11)

        ok = np.isfinite(ratio) & sizing['axis_ok']
        if ok.any():
            i = int(np.nanargmax(np.where(ok, ratio, np.nan)))
            ax2.plot([x[i]], [ratio[i]], 'o', ms=8, mfc=t['storage'], mec=t['surface'],
                     mew=2, zorder=12)
            left = x[i] > 0.5 * (x[0] + x[-1])
            ax2.annotate('best {:.0f} : 1 at {:.1f} m'.format(ratio[i], x[i]),
                         (x[i], ratio[i]), xytext=(-8 if left else 8, -14),
                         textcoords='offset points', ha='right' if left else 'left',
                         fontsize=FONT - 0.5, color=t['ink'], zorder=13,
                         bbox=dict(boxstyle='square,pad=0.15', fc=t['surface'], ec='none',
                                   alpha=0.85))
            ax2.set_ylim(0, np.nanmax(ratio) * 1.15)

        self.nwl_lines = [ax.axvline(nwl, color=t['ink'], lw=1.3) for ax in (ax1, ax2)]
        self.nwl_label = ax1.text(nwl, 0.97, '', transform=blended_transform_factory(
                                      ax1.transData, ax1.transAxes),
                                  va='top', fontsize=FONT - 0.5, color=t['ink'],
                                  fontweight='semibold', zorder=13)
        self._place_nwl_label(nwl)
        self.vl = [ax.axvline(x[0], color=t['ink2'], lw=0.8, visible=False) for ax in (ax1, ax2)]
        self.dots = [self.dot(ax1, t['dam']), self.dot(ax2, t['storage'])]
        self.has_data = True
        self.canvas.draw_idle()

    def _place_nwl_label(self, nwl):
        x = self.s['nwl']
        right_half = nwl > 0.5 * (x[0] + x[-1])
        self.nwl_label.set_x(nwl)
        self.nwl_label.set_ha('right' if right_half else 'left')
        self.nwl_label.set_text('NWL {:.1f} m '.format(nwl) if right_half
                                else ' NWL {:.1f} m'.format(nwl))

    def set_nwl(self, nwl):
        if not self.has_data:
            return
        for ln in self.nwl_lines:
            ln.set_xdata([nwl, nwl])
        self._place_nwl_label(nwl)
        self.canvas.draw_idle()

    def hide_hover(self):
        for a in self.vl + self.dots:
            a.set_visible(False)

    def _x_at(self, event):
        if not self.has_data or event.inaxes not in (self.ax1, self.ax2) or event.xdata is None:
            return None
        x = self.s['nwl']
        return float(np.clip(event.xdata, x[0], x[-1]))

    def _on_move(self, event):
        h = self._x_at(event)
        if h is None:
            return
        s = self.s
        x = s['nwl']
        f = float(np.interp(h, x, s['fill'])) / 1e6
        r = float(np.interp(h, x, np.nan_to_num(s['ratio'])))
        v = float(np.interp(h, x, s['volume'])) / 1e6
        cl = float(np.interp(h, x, s['crest_length']))
        ht = float(np.interp(h, x, s['height']))
        for ln in self.vl:
            ln.set_xdata([h, h])
            ln.set_visible(True)
        self.dots[0].set_data([h], [f])
        self.dots[1].set_data([h], [r])
        for d in self.dots:
            d.set_visible(True)
        self.show_tip(event,
                      'NWL  {:.1f} m  ·  crest {:.1f} m\nDam height  {:.1f} m\n'
                      'Crest length  {:,.0f} m\nFill  {} hm³\nStorage  {} hm³\n'
                      'Ratio  {:.1f} : 1\n(click to set NWL)'.format(
                          h, h + self.freeboard, ht, cl, theme.fmt_sig(f, 3),
                          theme.fmt_sig(v, 4), r))
        self.canvas.draw_idle()

    def _on_click(self, event):
        h = self._x_at(event)
        if h is not None and event.button == 1:
            self.levelPicked.emit(h)
