# -*- coding: utf-8 -*-
"""
Interactive matplotlib charts for the reservoir panel.

* :class:`CurveChart`   - elevation-area-volume curves (engineering layout:
  volume on the bottom axis, area on a reversed top axis).
* :class:`ProfileChart` - ground along the drawn line, its two ends and the
  water level.

Modern, quiet styling: hairline dashed grid, no heavy frame, gradient fills
under the curves, rounded value badges and a card-like hover tooltip.  Colours
follow the QGIS light/dark theme; exported PNGs are always on white.  The
font is applied only while drawing, so matplotlib's global rcParams are never
touched.
"""

import numpy as np
from qgis.PyQt.QtWidgets import QSizePolicy, QVBoxLayout, QWidget

try:  # matplotlib >= 3.5 picks the Qt binding already loaded (Qt5 or Qt6)
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
except ImportError:  # pragma: no cover - old matplotlib, Qt5 only
    from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib import rc_context
from matplotlib.colors import to_rgb
from matplotlib.figure import Figure
from matplotlib.patches import PathPatch
from matplotlib.ticker import FuncFormatter, MaxNLocator
from matplotlib.transforms import blended_transform_factory

from ..core.i18n import tr
from . import theme

FONT = 8.5
TITLE_FONT = 10.0
_RC = {
    'font.family': 'sans-serif',
    'font.sans-serif': ['Segoe UI', 'Inter', 'Helvetica Neue', 'Helvetica', 'Arial',
                        'DejaVu Sans'],
    'axes.unicode_minus': False,
}
_DASH = (0, (3, 3))


def _num(x, _pos=None):
    if abs(x) >= 100:
        return '{:,.0f}'.format(x)
    if abs(x) >= 10:
        return '{:,.1f}'.format(x).rstrip('0').rstrip('.')
    return '{:,.2f}'.format(x).rstrip('0').rstrip('.')


class _Canvas(FigureCanvas):
    """Figure canvas drawing with the plugin font (no global rcParams change)."""

    def draw(self):
        with rc_context(_RC):
            super().draw()

    def print_figure(self, *args, **kwargs):
        with rc_context(_RC):
            return super().print_figure(*args, **kwargs)


def _gradient_fill(ax, paths, color, alpha_top, alpha_bottom, zorder=2):
    """Fill ``paths`` (data coordinates) with a vertical transparency gradient."""
    rgb = to_rgb(color)
    for path in paths:
        v = path.vertices
        if len(v) < 3:
            continue
        x0, x1 = float(np.nanmin(v[:, 0])), float(np.nanmax(v[:, 0]))
        y0, y1 = float(np.nanmin(v[:, 1])), float(np.nanmax(v[:, 1]))
        if not (x1 > x0 and y1 > y0):
            continue
        img = np.zeros((128, 1, 4))
        img[..., :3] = rgb
        img[:, 0, 3] = np.linspace(alpha_bottom, alpha_top, 128)
        im = ax.imshow(img, aspect='auto', extent=[x0, x1, y0, y1], origin='lower',
                       zorder=zorder, interpolation='bilinear')
        clip = PathPatch(path, facecolor='none', edgecolor='none', transform=ax.transData)
        ax.add_patch(clip)
        im.set_clip_path(clip)


class BaseChart(QWidget):

    def __init__(self, parent=None, min_height=300):
        super().__init__(parent)
        try:
            self.figure = Figure(figsize=(4.0, 3.2), layout='constrained')
        except TypeError:  # matplotlib < 3.6
            self.figure = Figure(figsize=(4.0, 3.2), constrained_layout=True)
        self.canvas = _Canvas(self.figure)
        self.canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.canvas.setMinimumHeight(min_height)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.canvas)
        self.t = theme.tokens(self)
        self._print = False      # True while rendering a report-style (white) PNG
        self._last = None        # last set_data() arguments, to re-render for export
        self.tip = None
        self.has_data = False
        self._hover = []         # animated hover artists, drawn by blitting only
        self._bg = None          # rendered chart without them (see _on_draw)
        self.canvas.mpl_connect('draw_event', self._on_draw)
        self.canvas.mpl_connect('motion_notify_event', self._on_move)
        self.canvas.mpl_connect('figure_leave_event', self._on_leave)
        self.canvas.mpl_connect('axes_leave_event', self._on_leave)
        self.show_empty(tr('Draw a line across a valley to see this chart.'))

    # ---------------------------------------------------------------- style
    def _reset(self):
        if self._print:
            self.t = dict(theme.LIGHT, surface='#ffffff', window='#ffffff')
        else:
            self.t = theme.tokens(self)
        t = self.t
        self.figure.clear()
        self.figure.set_facecolor(t['surface'])
        try:
            self.figure.get_layout_engine().set(w_pad=0.06, h_pad=0.06)
        except AttributeError:  # matplotlib < 3.6
            pass
        self._bg = None
        self.tip = self.figure.text(
            0, 0, '', fontsize=FONT, color=t['ink'], zorder=30, visible=False,
            va='bottom', ha='left', linespacing=1.65, animated=True,
            bbox=dict(boxstyle='round,pad=0.75,rounding_size=0.7', fc=t['surface'],
                      ec=t['border'], lw=0.9))

    def style(self, ax, xlabel=None, ylabel=None, grid_x=True):
        t = self.t
        ax.set_facecolor('none')
        for side in ('top', 'right', 'left'):
            ax.spines[side].set_visible(False)
        ax.spines['bottom'].set_color(t['axis'])
        ax.spines['bottom'].set_linewidth(0.8)
        ax.tick_params(length=0, pad=6, labelcolor=t['muted'], labelsize=FONT - 0.5)
        ax.grid(True, axis='y', color=t['grid'], linewidth=0.8, linestyle=_DASH)
        if grid_x:
            ax.grid(True, axis='x', color=t['grid'], linewidth=0.8, linestyle=_DASH)
        ax.set_axisbelow(True)
        ax.xaxis.set_major_locator(MaxNLocator(5))
        ax.yaxis.set_major_locator(MaxNLocator(6))
        ax.xaxis.set_major_formatter(FuncFormatter(_num))
        ax.yaxis.set_major_formatter(FuncFormatter(_num))
        if xlabel:
            ax.set_xlabel(xlabel, fontsize=FONT, color=t['ink2'], labelpad=6)
        if ylabel:
            ax.set_ylabel(ylabel, fontsize=FONT, color=t['ink2'], labelpad=6)

    def title(self, ax, text):
        ax.set_title(text, loc='left', fontsize=TITLE_FONT, color=self.t['ink'],
                     fontweight='bold', pad=8)

    def badge(self, ax, x, y, text, color, ha='left', va='bottom', dx=0, dy=0,
              transform=None, filled=True, zorder=16, text_color='white'):
        """Rounded value pill; ``filled`` = coloured with ``text_color`` text."""
        t = self.t
        kw = dict(xytext=(dx, dy), textcoords='offset points', ha=ha, va=va,
                  fontsize=FONT - 0.3, fontweight='semibold', zorder=zorder,
                  color=text_color if filled else color,
                  bbox=dict(boxstyle='round,pad=0.38,rounding_size=0.75',
                            fc=color if filled else t['surface'],
                            ec='none' if filled else color, lw=0.9))
        if transform is not None:
            kw['xycoords'] = transform
        return ax.annotate(text, (x, y), **kw)

    def point(self, ax, x, y, color, zorder=14):
        """Marker with a soft halo."""
        ax.plot([x], [y], 'o', ms=13, mfc=color, mec='none', alpha=0.18, zorder=zorder,
                clip_on=False)
        ax.plot([x], [y], 'o', ms=6.5, mfc=color, mec=self.t['surface'], mew=1.6,
                zorder=zorder + 1, clip_on=False)

    def hover_dot(self, ax, color):
        halo, = ax.plot([], [], 'o', ms=15, mfc=color, mec='none', alpha=0.2, zorder=18,
                        visible=False, animated=True)
        dot, = ax.plot([], [], 'o', ms=7, mfc=color, mec=self.t['surface'], mew=1.8,
                       zorder=19, visible=False, animated=True)
        self._hover += [halo, dot]
        return [halo, dot]

    @staticmethod
    def set_dot(dot, x, y):
        for d in dot:
            d.set_data([x], [y])
            d.set_visible(True)

    def legend(self, ax, handles, **kw):
        t = self.t
        leg = ax.legend(handles=handles, fontsize=FONT - 0.3, frameon=True, fancybox=True,
                        borderpad=0.6, handlelength=2.2, handletextpad=0.6, columnspacing=1.2,
                        **kw)
        frame = leg.get_frame()
        frame.set_facecolor(t['surface'])
        frame.set_edgecolor(t['border'])
        frame.set_linewidth(0.8)
        frame.set_boxstyle('round,pad=0.2,rounding_size=0.8')
        for text in leg.get_texts():
            text.set_color(t['ink2'])
        leg.set_zorder(17)
        return leg

    # ---------------------------------------------------------------- state
    def show_empty(self, text):
        self._reset()
        self._last = None
        self._hover = []
        self.has_data = False
        self.figure.text(0.5, 0.5, text, ha='center', va='center', fontsize=FONT + 0.5,
                         color=self.t['muted'])
        self.canvas.draw_idle()

    def show_tip(self, event, text):
        w, h = self.figure.bbox.width, self.figure.bbox.height
        right = event.x > 0.55 * w
        x = (event.x - 18) / w if right else (event.x + 18) / w
        y = min(max(event.y / h + 0.03, 0.08), 0.70)
        self.tip.set_text(text)
        self.tip.set_position((x, y))
        self.tip.set_ha('right' if right else 'left')
        self.tip.set_visible(True)

    def hide_hover(self):
        pass

    # Hovering redraws only the crosshair, dots and tooltip over a saved image
    # of the chart (blitting): a full redraw takes ~60-120 ms, which made the
    # hover stutter; a blit takes a few ms.
    def _on_draw(self, _event):
        # Only remember the background here.  draw_event can fire inside Qt's
        # paintEvent (a pending draw is flushed there); blitting at that point
        # repaints from inside a paint, which Qt does not allow (painter errors,
        # crashes in QGIS 3.40).  Hover updates blit from mouse events only.
        self._bg = self.canvas.copy_from_bbox(self.figure.bbox)

    def _blit(self):
        if self._bg is None:
            self.canvas.draw_idle()
            return
        with rc_context(_RC):
            self.canvas.restore_region(self._bg)
            for a in self._hover + [self.tip]:
                if a is not None and a.get_visible():
                    (a.axes or self.figure).draw_artist(a)
            self.canvas.blit(self.figure.bbox)

    def _on_leave(self, _event):
        if not self.has_data:
            return
        self.tip.set_visible(False)
        self.hide_hover()
        self._blit()

    def _on_move(self, event):
        pass

    def refresh(self):
        """Redraw with the current theme and language."""
        if self._last is not None:
            self.set_data(*self._last)
        else:
            self.show_empty(tr('Draw a line across a valley to see this chart.'))

    def save_png(self, path):
        """Save a report-ready image: white background whatever the QGIS theme."""
        if self._last is None:
            self.figure.savefig(path, dpi=200, facecolor=self.t['surface'])
            return
        self._print = True
        try:
            self.set_data(*self._last)
            self.figure.savefig(path, dpi=200, facecolor='#ffffff')
        finally:
            self._print = False
            self.set_data(*self._last)


class CurveChart(BaseChart):
    """Elevation-area-volume curves in the usual dam-engineering layout.

    One elevation axis (left) shared by two curves: volume on the bottom axis
    (increasing to the right) and surface area on the top axis (increasing to
    the *left*), so the two curves cross - the classic reservoir
    elevation-area-capacity chart.  The water level and the riverbed are
    drawn as reference levels.
    """

    def set_data(self, levels, area_m2, volume_m3, water_level, level_label=None):
        level_label = level_label or tr('lower end of the line')
        self._last = (levels, area_m2, volume_m3, water_level, level_label)
        self._reset()
        t = self.t
        self.levels = np.asarray(levels, dtype=float)
        self.A = np.asarray(area_m2, dtype=float) / 1e6
        self.V = np.asarray(volume_m3, dtype=float) / 1e6
        self.bed = float(self.levels[0])
        ax_v = self.figure.subplots()
        ax_a = ax_v.twiny()                       # shares the elevation axis
        self.ax_v, self.ax_a = ax_v, ax_a
        self.style(ax_v, xlabel=tr('Volume (hm³)'), ylabel=tr('Elevation (m a.s.l.)'))
        self._style_top(ax_a)
        self.title(ax_v, tr('Elevation – area – volume'))

        lv = self.levels
        # soft gradient under each curve (towards its own zero axis)
        for ax, x, col in ((ax_v, self.V, t['storage']), (ax_a, self.A, t['area'])):
            poly = ax.fill_betweenx(lv, 0, x, facecolor='none', edgecolor='none')
            _gradient_fill(ax, poly.get_paths(), col, 0.15, 0.0, zorder=2)
        v_line, = ax_v.plot(self.V, lv, color=t['storage'], lw=2.4, solid_capstyle='round',
                            solid_joinstyle='round', label=tr('Volume'), zorder=6)
        a_line, = ax_a.plot(self.A, lv, color=t['area'], lw=2.4, solid_capstyle='round',
                            solid_joinstyle='round', label=tr('Surface area'), zorder=6)
        vmax, amax = max(self.V.max(), 1e-6), max(self.A.max(), 1e-6)
        ax_v.set_xlim(0, vmax * 1.12)
        ax_a.set_xlim(amax * 1.12, 0)             # area grows to the left
        span = max(1.0, water_level - self.bed)
        ax_v.set_ylim(self.bed - 0.03 * span, water_level + 0.12 * span)

        # reference levels
        trans = blended_transform_factory(ax_v.transAxes, ax_v.transData)
        ax_v.axhline(water_level, color=t['ink2'], lw=1.0, ls=(0, (5, 3)), zorder=5)
        self.badge(ax_v, 0.5, water_level,
                   tr('{:.1f} m a.s.l. · {}').format(water_level, level_label), t['ink'],
                   ha='center',
                   va='bottom', dy=5, transform=trans, text_color=t['surface'])
        ax_v.axhline(self.bed, color=t['muted'], lw=0.9, ls=(0, (1, 2.5)), zorder=5)
        ax_v.annotate(tr('Riverbed {:.1f} m a.s.l.').format(self.bed), (0.5, self.bed),
                      xycoords=trans,
                      xytext=(0, 3), textcoords='offset points', ha='center', va='bottom',
                      fontsize=FONT - 0.8, color=t['muted'], zorder=12)

        # values at the water level
        self.point(ax_v, self.V[-1], water_level, t['storage'])
        self.point(ax_a, self.A[-1], water_level, t['area'])
        self.badge(ax_v, self.V[-1], water_level, '{} hm³'.format(theme.fmt_sig(self.V[-1], 4)),
                   t['storage'], ha='right', va='top', dx=-6, dy=-7)
        self.badge(ax_a, self.A[-1], water_level, '{} km²'.format(theme.fmt_sig(self.A[-1], 3)),
                   t['area'], ha='left', va='top', dx=6, dy=-7)

        self.legend(ax_v, [v_line, a_line], loc='lower center', ncol=2,
                    bbox_to_anchor=(0.5, 0.07))

        self._hover = []
        self.hl = ax_v.axhline(self.bed, color=t['muted'], lw=0.8, ls=_DASH, visible=False,
                               zorder=5, animated=True)
        self._hover.append(self.hl)
        self.hdots = [self.hover_dot(ax_a, t['area']), self.hover_dot(ax_v, t['storage'])]
        self.has_data = True
        self.canvas.draw_idle()

    def _style_top(self, ax):
        t = self.t
        ax.set_facecolor('none')
        for side in ('left', 'right', 'bottom'):
            ax.spines[side].set_visible(False)
        ax.spines['top'].set_color(t['axis'])
        ax.spines['top'].set_linewidth(0.8)
        ax.tick_params(length=0, pad=5, labelcolor=t['muted'], labelsize=FONT - 0.5)
        ax.xaxis.set_major_locator(MaxNLocator(5))
        ax.xaxis.set_major_formatter(FuncFormatter(_num))
        ax.set_xlabel(tr('Surface area (km²)'), fontsize=FONT, color=t['ink2'], labelpad=6)
        ax.grid(False)

    def hide_hover(self):
        self.hl.set_visible(False)
        for dot in self.hdots:
            for d in dot:
                d.set_visible(False)

    def _on_move(self, event):
        if not self.has_data or event.inaxes not in (self.ax_a, self.ax_v):
            return
        # both axes share the elevation, but only the main one maps y reliably
        _x, y = self.ax_v.transData.inverted().transform((event.x, event.y))
        y = float(np.clip(y, self.levels[0], self.levels[-1]))
        a = float(np.interp(y, self.levels, self.A))
        v = float(np.interp(y, self.levels, self.V))
        self.hl.set_ydata([y, y])
        self.hl.set_visible(True)
        self.set_dot(self.hdots[0], a, y)
        self.set_dot(self.hdots[1], v, y)
        self.show_tip(event, tr('Elevation   {:.2f} m a.s.l.\nDepth   {:.1f} m\n'
                                'Volume   {} hm³\nSurface area   {} km²').format(y, y - self.bed,
                                                            theme.fmt_sig(v, 4),
                                                            theme.fmt_sig(a, 3)))
        self._blit()


class ProfileChart(BaseChart):
    """Ground along the drawn line; the water level and the two ends."""

    def set_data(self, stations, ground, water_level, level_label=None):
        level_label = level_label or tr('lower end of the line')
        self._last = (stations, ground, water_level, level_label)
        self._reset()
        t = self.t
        self.st = np.asarray(stations, dtype=float)
        self.g = np.asarray(ground, dtype=float)
        self.level = water_level
        ax = self.figure.subplots()
        self.ax = ax
        self.style(ax, xlabel=tr('Distance along the line (m)'),
                   ylabel=tr('Elevation (m a.s.l.)'), grid_x=False)
        self.title(ax, tr('Ground profile along the line'))
        gmin, gmax = np.nanmin(self.g), np.nanmax(self.g)
        pad = 0.10 * max(1.0, gmax - gmin)
        base = gmin - pad

        # the ground below the line is earth: soil colour with a light hatch texture
        ground_poly = ax.fill_between(self.st, base, self.g, facecolor='none', edgecolor='none')
        _gradient_fill(ax, ground_poly.get_paths(), t['earth'], 0.95, 0.55, zorder=2)
        ax.fill_between(self.st, base, self.g, facecolor='none', edgecolor=t['earth_line'],
                        hatch='////', linewidth=0, alpha=0.18, zorder=2.5)
        wet = self.g < water_level
        water_poly = ax.fill_between(self.st, self.g, water_level, where=wet, interpolate=True,
                                     facecolor='none', edgecolor='none')
        _gradient_fill(ax, water_poly.get_paths(), t['storage'], 0.45, 0.12, zorder=3)
        ax.plot(self.st, self.g, color=t['earth_line'], lw=2.2, solid_joinstyle='round',
                zorder=6)
        ax.axhline(water_level, color=t['storage'], lw=1.3, ls=(0, (5, 3)), zorder=7)
        trans = blended_transform_factory(ax.transAxes, ax.transData)
        self.badge(ax, 0.5, water_level,
                   tr('{:.1f} m a.s.l. · {}').format(water_level, level_label),
                   t['storage'], ha='center', va='bottom', dy=5, transform=trans)

        # the two ends of the line
        ends = ((self.st[0], self.g[0], 'left'), (self.st[-1], self.g[-1], 'right'))
        low = min(ends, key=lambda e: e[1])
        for s, z, side in ends:
            is_low = (s, z) == (low[0], low[1])
            self.point(ax, s, z, t['storage'] if is_low else t['earth_line'], zorder=12)
            self.badge(ax, s, z, tr('End {:.1f} m').format(z),
                       t['storage'] if is_low else t['muted'], filled=is_low,
                       ha=side, va='bottom', dx=4 if side == 'left' else -4, dy=9)
        ax.set_xlim(self.st[0], self.st[-1])
        ax.set_ylim(base, gmax + 1.6 * pad)
        self._hover = []
        self.vl = ax.axvline(0, color=t['muted'], lw=0.8, ls=_DASH, visible=False, zorder=8,
                             animated=True)
        self._hover.append(self.vl)
        self.gdot = self.hover_dot(ax, t['earth_line'])
        self.has_data = True
        self.canvas.draw_idle()

    def hide_hover(self):
        self.vl.set_visible(False)
        for d in self.gdot:
            d.set_visible(False)

    def _on_move(self, event):
        if not self.has_data or event.inaxes is not self.ax or event.xdata is None:
            return
        s = float(np.clip(event.xdata, self.st[0], self.st[-1]))
        g = float(np.interp(s, self.st, self.g))
        self.vl.set_xdata([s, s])
        self.vl.set_visible(True)
        self.set_dot(self.gdot, s, g)
        text = tr('Distance   {:,.0f} m\nGround   {:.1f} m a.s.l.').format(s, g)
        if g < self.level:
            text += tr('\nWater depth   {:.1f} m').format(self.level - g)
        self.show_tip(event, text)
        self._blit()
