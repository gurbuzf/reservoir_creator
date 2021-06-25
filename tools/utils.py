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

import pandas as pd 
import numpy as np
import os

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
    QgsCoordinateTransformContext, 
    edit,
    QgsMessageLog,
    QgsWkbTypes
)


def filter_contour(intersection_vector, ref_coor):
    '''
    Returns the id of the contour which defines the inundation area of the reservoir created by the dam.

    Parameters:
        intersection_vector:QgsVectorLayer, the vector layer including the points where the dam line intersects with the contour lines. 

        ref_coor:list, [x, y] coordinate of the dam dam centroid.
    
    Returns:
        (contourID, temp)

        contourID:int, the ID of the contour line

        points_dam_contour:pd.DataFrame, the points where the contour intersects the damline
    '''

    # intersection_vector = QgsVectorLayer(path, 'temp', 'ogr')
    fields = [field.name() for field in intersection_vector.fields()]+['x', 'y']

    attrs = []
    index = []

    for feature in intersection_vector.getFeatures():
        attrs.append(feature.attributes()+[feature.geometry().asPoint().x(),feature.geometry().asPoint().y()])
        index.append(feature.id())
    data = pd.DataFrame(attrs, columns=fields, index=index)

    contourID = None
    counts = data['ID'].value_counts()
    index = counts[counts >= 2].index
    points = data[data['ID'].isin(index)]

    #Check validity of a contour starting from one with the highest elevation
    sortedElev = np.sort(points['ELEV'].unique())[::-1]
    try:

        for elev in sortedElev:
            points_dam_contour_ = points[points['ELEV']==elev]
            for f_id in points_dam_contour_["ID"].unique():
                points_dam_contour = points_dam_contour_[points_dam_contour_["ID"]==f_id]
                X = []
                Y = []
            
                for p in [feature.geometry().asPoint() \
                    for feature in intersection_vector.getFeatures(points_dam_contour.index.tolist())]:
                    X.append(p.x() - ref_coor[0])
                    Y.append(p.y() - ref_coor[1])
                X = np.array(X)
                Y = np.array(Y)
                is_vertical = Y - Y[0]
                
                #Check if all points stay on the on side of the dam point[ref_coor]
                if all(X>0):
                    pass
                elif all(X<0):
                    pass
                
                elif all(is_vertical==0):
                    #This is for the case that the line is vertical and all X coordinates are identical
                    if all(Y>0):
                        pass
                    elif all(Y<0):
                        pass
                    else:
                        ## print(f'y1:{y1} y2:{y2} ref:{ref_coor[1]} ')
                        contourID = points_dam_contour['ID'].values[0] 
                        raise StopIteration
                else:
                    ## print(f'x1:{x1} x2:{x2} ref:{ref_coor[0]} ')
                    contourID = points_dam_contour['ID'].values[0] 
                    raise StopIteration
    
    except StopIteration:
        pass

    return contourID, points_dam_contour
    
def filter_intersecting_points(intersection_vector, points_dam_contour, ref_coor, CRS=None):
    '''
    Returns the location of the TWO points where the contour line intersects with the dam line to create\
    a polygon representing the inundated area by the dam.
    
    Parameters:
        intersection_vector:QgsVectorLayer, the vector layer including the points where the dam line intersects with the contour lines. 

        points_dam_contour:pd.DataFrame, the points where the contour intersects the damline 

        ref_coor:list, [x, y] coordinate of the dam dam centroid. 

        CRS (optional):<QgsCoordinateReferenceSystem: EPSG:crs>, 
    
    Returns:

        (x1, y1, x2, y2):tuple, lat and long coordinates of the points.

        dam_length:float, the length of the dam in meters
    '''
    
    distance = QgsDistanceArea()
    if CRS != None:
        distance.setEllipsoid(f"WGS84:{CRS.authid()[5:]}")
        
    ref_coor_Qgs = QgsPointXY(ref_coor[0],ref_coor[1]) 
    X = []
    Y = []
    dist = []
    for x, y in points_dam_contour[["x", "y"]].apply(list, axis=1):
        p_Qgs = QgsPointXY(x,y)
        d = distance.measureLine(p_Qgs, ref_coor_Qgs)
        dist.append(d)
        X.append(p_Qgs.x()- ref_coor[0])
        Y.append(p_Qgs.y()- ref_coor[1])
    sort_index = np.argsort(dist)

    X = np.array(X)
    Y = np.array(Y)
    is_vertical = Y-Y[0] #TODO: add this case 


    #Get the two point on the dam line intersecting with the contour to create a polygon  
    X_bool = (X>0)
    i=1
    check_again = True 
    while check_again:
        if X_bool[sort_index[0]] != X_bool[sort_index[i]]: 
            check_again = False
        else:
            i += 1
    P2 = intersection_vector.getFeature(points_dam_contour.iloc[sort_index[i]].name).geometry().asPoint()
    P1 = intersection_vector.getFeature(points_dam_contour.iloc[sort_index[0]].name).geometry().asPoint()
    x1, y1 = P1.x(), P1.y()
    x2, y2 = P2.x(), P2.y()

    dam_length = distance.measureLine(P1, P2)



    return (x1, y1, x2, y2), dam_length

def create_reservoir_polygon(contour_geometry, points, CRS):
    '''
    Creates a polygon defining the reservoir area.

    Parameters:

        contour_geometry:QgsGeometry, the geometry of the feasible contour

        points:list, [QgsPoint, QgsPoint] the two points where dam line intersects with the contour.

        CRS:QgsCoordinateReferenceSystem,

    Returns:
    
        layer:QgsVectorLayer, the vector of the polygon.

        area:float, surface area of the polygon
    '''
    if QgsWkbTypes.isSingleType(contour_geometry.wkbType()):
         # single
        points_list = contour_geometry.asPolyline()
    else:
        # multipart
        points_list = contour_geometry.asMultiPolyline()[0]
    
    point1, point2 = points[0], points[1]

    distance = QgsDistanceArea()
    distance.setEllipsoid(f"WGS84:{CRS.authid()[5:]}")
    # m = distance.measureLine(point1, point2)
    dist_1 = []
    dist_2 = []

    for point in points_list:
        d1 = distance.measureLine(point1, point)
        d2 = distance.measureLine(point2, point)
        dist_1.append(d1)
        dist_2.append(d2)

    ind1 = dist_1.index(min(dist_1))
    ind2 = dist_2.index(min(dist_2))
  
    if ind1<ind2:
        points_cont = points_list[ind1:ind2+1]
    else:
        points_cont = points_list[ind2:ind1+1]
   
    ply_01 = QgsGeometry.fromPolygonXY([points_cont])
    area = ply_01.area()
    ftr = QgsFeature()
    ftr.setGeometry(ply_01)

    # Create a layer for the feature and add to the project
    layer = QgsVectorLayer(f'Polygon?crs=epsg{CRS.authid()[5:]}',
                            'Reservoir_Polygon',"memory")
    layer.setCrs(CRS)
    layer.startEditing()
    layer.addFeature(ftr)
    layer.commitChanges()

    return layer, area

def convertRasterToNumpyArray(lyr, Band=1): #Input: QgsRasterLayer
    '''Converts a raster layer into a 2D numpy array
    
    Parameters:

        lyr:<QgsRasterLayer>, raster data.

        Band:int, the band to be used.

    Returns:

        im:np.array, 2 dimensional np array including pixel values.

    '''
    provider= lyr.dataProvider()
    block = provider.block(Band,lyr.extent(),lyr.width(),lyr.height())
    im = np.zeros((lyr.height(),lyr.width()))
    for i in range(lyr.height()):
        for j in range(lyr.width()):
            im[i, j] = block.value(i,j)
    
    return im

def calculate_area_volume(dem_raster, nodata=None, crest_altitude=None, nstep=50):
    '''Returns elevation vs volume pairs of a reservoir using DEM of the inundated area.

    Parameters:

        dem_raster:<QgsRasterLayer>, Digital Elevation Model of the inundated area. 

        nodata:None/int/str/float, the value for raster pixels with no data. 

        crest_altitude:float[optional], the elevation of the dam's crest. 

        nstep:int, number of steps-between min and max elevation- for which a volume is calculated.
    
    Returns:

        altitude:list, a list of elevations for which a volume is calculated.

        area:list, a list of areas inundated at certain water levels.

        volume:list, a list of volumes corresponding elevations.
    '''    

    
    pixelSizeX = dem_raster.rasterUnitsPerPixelX()
    pixelSizeY = dem_raster.rasterUnitsPerPixelY()
    pixelArea = pixelSizeX*pixelSizeY
    dem_array = convertRasterToNumpyArray(dem_raster)
    valid_pixel_values = dem_array[dem_array != nodata]
    relative_depth = valid_pixel_values - min(valid_pixel_values)
    
    rel_min_depth = relative_depth.min()
    if crest_altitude is not None:
        rel_max_depth = crest_altitude - min(valid_pixel_values)
    else:
        rel_max_depth = relative_depth.max()
    
    water_depth = np.linspace(rel_min_depth, rel_max_depth, num=nstep)
    
    volume = []
    area = []
    for depth in water_depth:
        temp = relative_depth - depth
        npixels_under_water = sum(temp<0)
        _area = npixels_under_water * pixelArea
        area.append(_area)
        depth_under_water = abs(sum(temp[temp<0]))
        _volume = depth_under_water * pixelArea
        volume.append(_volume)
    altitude = water_depth + valid_pixel_values.min()

    return altitude, area, volume

def increment_filename(full_path, extension):
    if os.path.isfile(full_path):
        expand = 1
        while True:
            expand += 1
            new_full_path = full_path.split('.'+extension)[0]  + '_' + str(expand) + '.' + extension 
            if os.path.isfile(new_full_path):
                continue
            else:
                full_path = new_full_path
                break

    return full_path