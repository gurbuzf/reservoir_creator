# -*- coding: utf-8 -*-
"""Turning a reservoir Result into QGIS layers and files."""

import csv
import os
import tempfile

from qgis.core import (QgsColorRampShader, QgsCoordinateReferenceSystem,
                       QgsCoordinateTransformContext, QgsFeature, QgsFillSymbol,
                       QgsGeometry, QgsLineSymbol, QgsPointXY, QgsProject,
                       QgsRasterLayer, QgsRasterShader, QgsSingleBandPseudoColorRenderer,
                       QgsStyle, QgsVectorFileWriter, QgsVectorLayer)

from ..core import terrain
from . import theme

RES_FIELDS = [('level_m', 'double'), ('area_km2', 'double'), ('volume_mm3', 'double'),
              ('max_dep_m', 'double')]
LINE_FIELDS = [('start_m', 'double'), ('end_m', 'double'), ('length_m', 'double')]
TABLE_FIELDS = [('level_m', 'double'), ('area_m2', 'double'), ('area_km2', 'double'),
                ('volume_m3', 'double'), ('volume_mm3', 'double')]


def result_crs(res):
    return QgsCoordinateReferenceSystem.fromWkt(res.srs_wkt)


def _memory_layer(geom_type, name, crs, fields):
    uri = geom_type + ('?crs=' + crs.authid() if crs is not None and crs.authid() else '?')
    uri += ''.join('&field={}:{}'.format(n, t) for n, t in fields)
    layer = QgsVectorLayer(uri, name, 'memory')
    if crs is not None and not crs.authid():
        layer.setCrs(crs)
    return layer


def _r(v, d=3):
    return None if v is None or v != v else round(float(v), d)


def reservoir_layer(res, name=None):
    lyr = _memory_layer('MultiPolygon', name or 'Reservoir {:.1f} m'.format(res.water_level),
                        result_crs(res), RES_FIELDS)
    if res.polygon_wkt:
        f = QgsFeature(lyr.fields())
        f.setGeometry(QgsGeometry.fromWkt(res.polygon_wkt))
        f.setAttributes([_r(res.water_level, 2), _r(res.area_m2 / 1e6, 4),
                         _r(res.volume_m3 / 1e6, 4), _r(res.max_depth, 2)])
        lyr.dataProvider().addFeatures([f])
        lyr.updateExtents()
    lyr.renderer().setSymbol(QgsFillSymbol.createSimple({
        'color': '42,120,214,90', 'outline_color': theme.LIGHT['storage'],
        'outline_width': '0.4'}))
    return lyr


def line_layer(res, name='Dam line'):
    lyr = _memory_layer('LineString', name, result_crs(res), LINE_FIELDS)
    f = QgsFeature(lyr.fields())
    f.setGeometry(QgsGeometry.fromPolylineXY([QgsPointXY(x, y) for x, y in res.line_coords]))
    f.setAttributes([_r(res.end_levels[0], 2), _r(res.end_levels[1], 2),
                     _r(res.stations[-1], 1)])
    lyr.dataProvider().addFeatures([f])
    lyr.updateExtents()
    lyr.renderer().setSymbol(QgsLineSymbol.createSimple({
        'line_color': theme.LIGHT['dam'], 'line_width': '0.9', 'capstyle': 'round'}))
    return lyr


def table_layer(res, name='Elevation-area-volume'):
    lyr = _memory_layer('None', name, None, TABLE_FIELDS)
    lv, a, v = res.curve()
    feats = []
    for h, aa, vv in zip(lv, a, v):
        f = QgsFeature(lyr.fields())
        f.setAttributes([_r(h, 3), _r(aa, 1), _r(aa / 1e6, 5), _r(vv, 1), _r(vv / 1e6, 5)])
        feats.append(f)
    lyr.dataProvider().addFeatures(feats)
    return lyr


def depth_raster(res, path=None):
    """Write the water-depth grid and return a styled raster layer."""
    if path is None:
        fd, path = tempfile.mkstemp(prefix='reservoir_depth_', suffix='.tif')
        os.close(fd)
    terrain.write_geotiff(path, res.grid, res.depth_array())
    lyr = QgsRasterLayer(path, 'Water depth')
    ramp = QgsStyle.defaultStyle().colorRamp('Blues')
    top = max(res.max_depth, 0.1)
    fn = QgsColorRampShader(0.0, top, ramp, QgsColorRampShader.Type.Interpolated)
    fn.classifyColorRamp(5, -1)
    shader = QgsRasterShader()
    shader.setRasterShaderFunction(fn)
    renderer = QgsSingleBandPseudoColorRenderer(lyr.dataProvider(), 1, shader)
    renderer.setClassificationMin(0.0)
    renderer.setClassificationMax(top)
    renderer.setOpacity(0.85)
    lyr.setRenderer(renderer)
    return lyr


def add_to_project(res):
    """Add the reservoir outline, the line and the depth grid in a new group."""
    project = QgsProject.instance()
    group = project.layerTreeRoot().insertGroup(
        0, 'Reservoir {:.1f} m'.format(res.water_level))
    layers = [line_layer(res), reservoir_layer(res), depth_raster(res)]
    for lyr in layers:
        project.addMapLayer(lyr, False)
        group.addLayer(lyr)
    return layers


def write_csv(res, path):
    lv, a, v = res.curve()
    with open(path, 'w', newline='', encoding='utf-8') as fh:
        w = csv.writer(fh)
        w.writerow(['level_m', 'area_m2', 'area_km2', 'volume_m3', 'volume_million_m3'])
        for h, aa, vv in zip(lv, a, v):
            w.writerow(['{:.3f}'.format(h), '{:.1f}'.format(aa), '{:.5f}'.format(aa / 1e6),
                        '{:.1f}'.format(vv), '{:.5f}'.format(vv / 1e6)])
    return path


def write_geopackage(res, path):
    """Reservoir outline, line and elevation-area-volume table in one file."""
    ctx = QgsCoordinateTransformContext()
    first = True
    for lyr, name in ((reservoir_layer(res), 'reservoir'), (line_layer(res), 'dam_line'),
                      (table_layer(res), 'elevation_area_volume')):
        opts = QgsVectorFileWriter.SaveVectorOptions()
        opts.driverName = 'GPKG'
        opts.layerName = name
        opts.actionOnExistingFile = (
            QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteFile if first
            else QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteLayer)
        out = QgsVectorFileWriter.writeAsVectorFormatV3(lyr, path, ctx, opts)
        if out[0] != QgsVectorFileWriter.WriterError.NoError:
            raise IOError(out[1] if len(out) > 1 else 'Could not write {}'.format(path))
        first = False
    return path


def table_text(res):
    lv, a, v = res.curve()
    rows = ['Water level (m)\tArea (km²)\tVolume (million m³)']
    for h, aa, vv in zip(lv, a, v):
        rows.append('{:.2f}\t{:.4f}\t{:.4f}'.format(h, aa / 1e6, vv / 1e6))
    return '\n'.join(rows)
