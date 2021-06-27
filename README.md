QGIS3 reservoir_creator plugin
=================================

A QGIS3 plugin that eases the calculation of elevation-area-storage curves for dams.

This tool takes advantage of existing processing algorithms that come with QGIS to obtain and visualize elevation-area-storage relationship of a hypothetical dam/embankment on a water-course. It also automatically creates a polygon for the inundated area by the dam and extracts corresponding Digital Elevation Model (DEM). 

Usage
------
* Download the zip file. Open QGIS. From the menu item, go to Plugins > Manage and Install Items. Select "Install from ZIP" tab on the left panel.

* Open reservoir_creator plugin. Provide the needed layers and select the layers that you want to save. After specifing the saving directory, click run. Depending on the density of the contours lines and the size of the area of interest, calculations may take up to 1-2 minutes. 

![Main Dialog](/data/dialog.png "Reservoir Creator Dialog")

* Sample data (DEM and line vector) is included in data folder. One first need to create a contour layer from the DEM using GDAL/Contour tool (not Contour Polygons) in Processing Toolbox. Attribute name should remain as 'ELEV'. Interval between contour lines should be small enough to capture the variations in topography. For this example, set the interval as 1.0 or 2.0.      

![Plot](/data/result.png "Resulting Figure")



![Example](/data/ex.png "Inundated Area")

** Since the sample DEM was created before the dam was built, we are able to estimate the inundated area by the dam and other characteristics such as elevation-storage relationship. The above experiment is a good experiment to validate the output of the reservoir_creator plugin.   

License
--------
### QGIS3 reservoir_creator
Copyright (C) 2021 Faruk Gurbuz

This program is free software; you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation; either version 3 of the License, or (at your option) any later version.   

This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with this program.  If not, see <http://www.gnu.org/licenses/>.

Credits
--------
This plugin was created with [QGIS Plugin Builder](http://g-sherman.github.io/Qgis-Plugin-Builder/) and Qt Designer.