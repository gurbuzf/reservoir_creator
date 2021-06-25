# -*- coding: utf-8 -*-
"""
/***************************************************************************
        copyright            : (C) 2021 by Faruk Gurbuz
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""

import numpy as np 
# import qgis
from qgis.PyQt.QtWidgets import  QSizePolicy
# import qgis.PyQt.QtCore as Qt
from matplotlib.backends.qt_compat import QtCore 
import matplotlib
from matplotlib.figure import Figure

# if int(qgis.PyQt.QtCore.QT_VERSION_STR[0]) == 4 :
#     from matplotlib.backends.backend_qt4agg import FigureCanvasQTAgg

# elif int(qgis.PyQt.QtCore.QT_VERSION_STR[0]) == 5 :
#TODO: Make the code QGIS.2.x compatible 

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT 

from matplotlib import rcParams



rcParams.update({'font.family':'arial', 'font.size':12, 'font.weight':'normal', 'lines.linewidth':2.5})

class PlottingTool():

    def __init__(self, dialog):
        # self.iface = iface
        self.dlg = dialog

    def SET_PLOT_FEATURES(self, ax):
        ax.set(xlabel='Elevation', ylabel='Storage')
        ax.grid()
        # ax.tight_layout()

    def initialize_plot(self):
        self.figure = Figure( (1.0, 1.0), constrained_layout=True,linewidth=0.0, dpi=80,subplotpars = matplotlib.figure.SubplotParams(left=0.15, bottom=0.2, right=0.99, top=0.95))
        self.canvas = FigureCanvasQTAgg(self.figure)
  
        self.dlg.verticalLayout.addWidget(self.canvas)
        self.canvas.draw()
        self.dlg.toolbar = NavigationToolbar2QT(self.canvas, 
                self.dlg, coordinates=True)
        self.dlg.verticalLayout.addWidget(self.dlg.toolbar,)


    def draw_empty_figure(self):
        self.figure.clf()
        ax = self.figure.add_subplot(111)
        self.SET_PLOT_FEATURES(ax)

    def plot_Storage(self, elevation, storage): 
        self.figure.clf()    
        ax = self.figure.add_subplot(111)
        ax.plot(elevation, storage, c='k')
        
        self.SET_PLOT_FEATURES(ax)
        self.canvas.draw()

