# -*- coding: utf-8 -*-
"""
/***************************************************************************
 ReservoirCreator
                                 A QGIS plugin
 This plugin creates the inundation area of a dam (a line) that is placed on a water course.
 Generated by Plugin Builder: http://g-sherman.github.io/Qgis-Plugin-Builder/
                              -------------------
        begin                : 2021-05-09
        git sha              : $Format:%H$
        copyright            : (C) 2021 by Faruk Gurbuz
        email                : gurbuz2561@gmail.com
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

import os
import numpy as np
import string
import random
import matplotlib 
import processing
import time
import tempfile
import re 

from processing.core.Processing import Processing
from qgis.PyQt.QtWidgets import QFileDialog, QTableWidget,QTableWidgetItem
from qgis.PyQt.QtGui import QGuiApplication, QClipboard

from qgis.core import (
    Qgis,
    QgsApplication, 
    QgsRasterLayer,
    QgsProject,
    QgsPointXY, 
    QgsVectorLayer,
    QgsDistanceArea,
    QgsGeometry,
    QgsFeature,
    QgsVectorFileWriter,
    QgsRasterFileWriter,
    QgsCoordinateTransformContext, 
    edit,
    QgsMessageLog,
    QgsMapLayerType,
    QgsWkbTypes,
    QgsProcessingFeedback,
    QgsProcessing,
    QgsRasterPipe
)

from .utils import (
    filter_contour, 
    filter_intersecting_points, 
    create_reservoir_polygon, 
    calculate_area_volume,
    increment_filename)

from .plottingtool import PlottingTool


RASTER_PROVIDERS = ['gdal', 'memory']
VECTOR_PROVIDERS = ['ogr', 'memory']


class ReservoirCreatorCore:

    def __init__(self, iface, dialog=None):
        self.iface = iface
        self.dlg = dialog

    def status(self, percentage_completed):
        #TODO: Find better way of reporting progress
        self.dlg.progressBar.setValue(percentage_completed)
    
    def select_output_directory(self):
        folder = QFileDialog.getExistingDirectory(
            self.dlg, "Select output directory."
        )
        self.dlg.lineEdit_1.setText(folder)

    def list_map_layers(self):

        vector_layers = []
        raster_layers = []

        for layer in QgsProject.instance().mapLayers().values():
            layerName = layer.name()
            layerType = layer.type()
            layerProvider = layer.providerType()
            
            if layerType == QgsMapLayerType.VectorLayer:    
                if layerProvider in VECTOR_PROVIDERS:
                    vector_layers.append(layerName)
                else:
                    pass
                    # QgsMessageLog.logMessage(f"Vector layer {layerName} 
                                                # has an unsupported type.", 
                                                # level=Qgis.info)

            elif layerType == QgsMapLayerType.RasterLayer:    
                if layerProvider in RASTER_PROVIDERS:
                    raster_layers.append(layerName)
                else:
                    pass
                    # QgsMessageLog.logMessage(f"Raster layer {layerName} 
                                                # has an unsupported type.", 
                                                # level=Qgis.Info)
        
        return ['']+vector_layers, ['']+raster_layers

    def initialize_widgets(self):
        self.dlg.lineEdit_1.setText(str(os.getcwd()))
        self.dlg.pushButton_1.clicked.connect(self.select_output_directory)
        self.dlg.pushButton_2.clicked.connect(self.create_reservoir)
        self.dlg.copyButton.clicked.connect(self.copy_data_to_clipboard)
        self.dlg.progressBar.setRange(0, 100)
        self.dlg.progressBar.setValue(0)
        self.initialize_table_Widget()
    
    def comboBox_Load(self):
        self.status(0)
        self.dlg.Point_ComboBox.clear()
        self.dlg.Contour_ComboBox.clear()  
        self.dlg.Line_ComboBox.clear()  
        self.dlg.DEM_ComboBox.clear() 

        vector_layers, raster_layers = self.list_map_layers()
        self.dlg.Point_ComboBox.addItems(vector_layers)
        self.dlg.Contour_ComboBox.addItems(vector_layers)
        self.dlg.Line_ComboBox.addItems(vector_layers)
        self.dlg.DEM_ComboBox.addItems(raster_layers)
    
    def load_layers(self):
        damline_layerName = self.dlg.Line_ComboBox.currentText()
        DEM_layerName = self.dlg.DEM_ComboBox.currentText()
        contour_layerName = self.dlg.Contour_ComboBox.currentText()
        point_layerName = self.dlg.Point_ComboBox.currentText()

        damline_vector = None
        DEM_raster = None
        contours_vector = None
        point_vector = None

        ####
        if damline_layerName == '':
            self.iface.messageBar().pushMessage(
                "Error", "Provide a line vector!", 
                level=Qgis.Critical, 
                duration=3
            )

        else:
            damline_vector = QgsProject.instance().mapLayersByName(damline_layerName)[0]

            if QgsWkbTypes.displayString(damline_vector.wkbType()) not in ['LineString', 'MultiLineString']:
                self.iface.messageBar().pushMessage(
                    "Error", "Dam line is not valid!", 
                    level=Qgis.Critical, 
                    duration=3 
                )

            else:
                pass

        ####
        if contour_layerName == '':
            self.iface.messageBar().pushMessage(
                "Error", "Provide a contour vector!", 
                level=Qgis.Critical, duration=3 
            )

        else:
            contours_vector = QgsProject.instance().mapLayersByName(contour_layerName)[0]
            
            if QgsWkbTypes.displayString(contours_vector.wkbType()) not in ['LineString', 'MultiLineString']:
                self.iface.messageBar().pushMessage(
                    "Error", "Contour Layer is not valid!", 
                    level=Qgis.Critical, 
                    duration=3 
                )

            else:
                pass
        ####                
        if DEM_layerName == '':
            self.iface.messageBar().pushMessage(
                "Info", "Provide a DEM for volume-elevation calculation!", 
                level=Qgis.Info, 
                duration=3 
            )

        else:
            DEM_raster = QgsProject.instance().mapLayersByName(DEM_layerName)[0]
        
        ####
        if point_layerName == '':

            for feature in damline_vector.getFeatures():
                geom = feature.geometry()
                length = geom.length()
                point = geom.interpolate(length/2)
                # Create a point vector in the middle of the dam line
            ftr = QgsFeature()
            ftr.setGeometry(point)
            CRS = damline_vector.crs()
            point_vector = QgsVectorLayer(
                            f'Point?crs=epsg{CRS.authid()[5:]}',
                            'ref_point',
                            "memory"
                        )
            point_vector.setCrs(CRS)
            point_vector.startEditing()
            point_vector.addFeature(ftr)
            point_vector.commitChanges()

        else:
            point_vector = QgsProject.instance().mapLayersByName(point_layerName)[0]

            if QgsWkbTypes.displayString(point_vector.wkbType()) not in ['Point']:
                self.iface.messageBar().pushMessage(
                    "Error", "Reference point is not valid!", 
                    level=Qgis.Critical, duration=3 
                )

            else:
                pass
        
        return damline_vector, contours_vector, DEM_raster, point_vector
    
    def initialize_plot_Widget(self):
        layout = self.dlg.verticalLayout

        for i in reversed(range(layout.count())): 
            layout.itemAt(i).widget().setParent(None)

        self.plot = PlottingTool(self.dlg)
        self.plot.initialize_plot()
        self.plot.draw_empty_figure()
    
    def initialize_table_Widget(self):
        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(['Elevation', 'Area', 'Storage'])
        self.dlg.scrollArea.setWidget(self.table)
        # self.table.horizontalHeader().setStretchLastSection(True)        

    def saving_options(self):

        save_path = self.dlg.lineEdit_1.text() + '/'
        save_ClippedDEM = self.dlg.checkBox_1.isChecked()
        save_InundationArea = self.dlg.checkBox_1.isChecked()

        return save_path, save_ClippedDEM, save_InundationArea

    def add_data2_Table(self, elevation, area, volume):

        rowCount = len(elevation)
        self.table.setRowCount(rowCount)
        self.table.setColumnCount(3)

        for row in range(rowCount): 
            item1 = str(round(elevation[row], 2))
            item2 = str(round(area[row],1))
            item3 = str(round(volume[row],1))                   
            self.table.setItem(row, 0, QTableWidgetItem(item1))
            self.table.setItem(row, 1, QTableWidgetItem(item2))
            self.table.setItem(row, 2, QTableWidgetItem(item3))
          
    def copy_data_to_clipboard(self):
        
        n_column = self.table.columnCount()
        n_row = self.table.rowCount()
        text = 'Elevation\tArea\tStorage\n'

        for i in range(n_row):
            for j in range(n_column):
                text += self.table.item(i, j).text() + '\t'
            text += '\n'

        QGuiApplication.clipboard().clear()
        QGuiApplication.clipboard().setText(text.strip(), QClipboard.Clipboard)


    def create_reservoir(self):
 
        QgsMessageLog.logMessage("Process started.", level=Qgis.Info)

        save_path, save_ClippedDEM, save_InundationArea = self.saving_options()

        damline_vector, contours_vector, DEM_raster, point_vector = self.load_layers()
        
        CRS = damline_vector.crs()

        self.status(5)
        QgsMessageLog.logMessage("Layers loaded.", level=Qgis.Info)

        try:

            out = processing.run("native:lineintersections", 
                                {'INPUT':contours_vector, 
                                'INTERSECT':damline_vector, 
                                'OUTPUT': 'memory:temp'},
                                feedback=QgsProcessingFeedback()
                                )
            for feature in point_vector.getFeatures():
                xy = feature.geometry().asPoint()
                ref_coor = [xy[0], xy[1]]

            self.status(50) 

            #Filter the contour to be used for calculation of inundated area by the dam
            contourID, points_dam_contour = filter_contour(
                                                out['OUTPUT'], 
                                                ref_coor
                                            )

            #Save the selected contour as a Vector and get its geometry
            selected = []
            for _, feature in enumerate(contours_vector.getFeatures()):
                if feature["ID"]==contourID:
                    selected.append(feature.id())
                    GEOM = feature.geometry()
                    crest_altitude = feature.attributes()[feature.fieldNameIndex('ELEV')]
            # contours_vector.select(selected)

            self.status(60)
            #Get the coordinates of the two points -among ones where the damline intersects 
            # with the contours- to be used for polygon creation
            try:
                (x1, y1, x2, y2), dam_length = filter_intersecting_points(
                                                    out['OUTPUT'], 
                                                    points_dam_contour, 
                                                    ref_coor, CRS=CRS
                                                )
            except IndexError:  # To manage  any index error in here, we simply set contourID 
                                # None to be catched by UnboundLocalError
                contourID = None #TODO: Find a better way for handling this error
           
            self.status(70)
            point1 = QgsPointXY(x1,y1)
            point2 = QgsPointXY(x2,y2)

            layer, area = create_reservoir_polygon(
                            GEOM, 
                            [point1, point2], 
                            CRS
                        )
            
            self.status(80)

            options = QgsVectorFileWriter.SaveVectorOptions()
            options.driverName = "ESRI Shapefile"

            poly_name = layer.name() + '_' + self.dlg.Line_ComboBox.currentText()

            poly_path = increment_filename(
                            os.path.join(save_path,  poly_name + '.shp'), 
                            extension='shp'
                        )
            l_name = re.findall(r"[\w']+", poly_path)[-2]
            layer.setName(l_name) 
            QgsProject.instance().addMapLayer(layer) # add the polygon to the qgis legend

            if save_InundationArea:
                s_name = ''.join(random.choices(string.ascii_uppercase + string.digits, k=5))

                writer = QgsVectorFileWriter.writeAsVectorFormatV2(
                            layer, poly_path,
                            QgsCoordinateTransformContext(), 
                            options
                        )
                del writer

            QgsMessageLog.logMessage(
                f"Crest_length:{round(dam_length, 2)} m, \
                Inundation Area:{round(area, 2)} m2", level=Qgis.Info
            )
            
            parameters = {'INPUT': DEM_raster,
                            'MASK': layer,
                            'NODATA': -100,
                            'ALPHA_BAND': False,
                            'CROP_TO_CUTLINE': True,
                            'KEEP_RESOLUTION': True,
                            'OPTIONS': 'COMPRESS=LZW',
                            'DATA_TYPE': 0,
                            'SET_RESOLUTION' : False
                        }
            temp_name =  'ReservoirDEM_' + self.dlg.Line_ComboBox.currentText()
            

            if save_ClippedDEM:
                full_path = increment_filename(
                                os.path.join(save_path,  temp_name + '.tif'), 
                                extension='tif'
                            )
                parameters['OUTPUT'] = full_path
            else:
                tf = tempfile.TemporaryDirectory()
                full_path = increment_filename(
                                os.path.join(tf.name, temp_name + '.tif'), 
                                extension='tif'
                            )
                parameters['OUTPUT'] = full_path
            
            self.status(85)
            out_dem = processing.runAndLoadResults(
                        'gdal:cliprasterbymasklayer', 
                        parameters, 
                        feedback=QgsProcessingFeedback()
                    )

            clipped_DEM  = QgsRasterLayer(out_dem['OUTPUT'], temp_name)

            altitude, area, volume = calculate_area_volume(
                                        clipped_DEM, 
                                        crest_altitude=crest_altitude, 
                                        nodata=-100
                                    )
           
            self.status(90)
            self.plot.plot_Storage(altitude, volume)
            self.add_data2_Table(altitude, area, volume)

            del layer, area, altitude, volume, damline_vector, \
            contours_vector, DEM_raster, point_vector, clipped_DEM
            
            self.iface.messageBar().pushMessage(
                "Success", f"Outputs are written in {save_path}", 
                level=Qgis.Success, duration=10
            )

        except UnboundLocalError or IndexError:

            self.iface.messageBar().pushMessage(
                "Error", "reservoir_creator failed!", 
                level=Qgis.Critical, duration=10
            )

        self.status(100)
        

    

