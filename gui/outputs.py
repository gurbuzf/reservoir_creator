# -*- coding: utf-8 -*-
"""Turning a ReservoirModel into QGIS layers and files."""

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

POLY_FIELDS = [('level_m', 'double'), ('area_km2', 'double'), ('volume_hm3', 'double'),
               ('mean_dep_m', 'double'), ('max_dep_m', 'double'), ('length_km', 'double'),
               ('shore_km', 'double')]
AXIS_FIELDS = [('nwl_m', 'double'), ('crest_m', 'double'), ('height_m', 'double'),
               ('crest_len', 'double'), ('fill_hm3', 'double'), ('ratio', 'double')]
EAC_FIELDS = [('level_m', 'double'), ('area_m2', 'double'), ('area_km2', 'double'),
              ('volume_m3', 'double'), ('volume_hm3', 'double')]


def model_crs(model):
    crs = QgsCoordinateReferenceSystem.fromWkt(model.srs_wkt)
    return crs


def _memory_layer(geom_type, name, crs, fields):
    uri = geom_type
    if crs is not None and crs.authid():
        uri += '?crs=' + crs.authid()
    else:
        uri += '?'
    uri += ''.join('&field={}:{}'.format(n, t) for n, t in fields)
    layer = QgsVectorLayer(uri, name, 'memory')
    if crs is not None and not crs.authid():
        layer.setCrs(crs)
    return layer


def _r(v, d=3):
    return None if v is None or v != v else round(float(v), d)


def reservoir_layer(model, stats, name=None):
    crs = model_crs(model)
    lyr = _memory_layer('MultiPolygon', name or 'Reservoir {:.1f} m'.format(stats['level']),
                        crs, POLY_FIELDS)
    if stats.get('polygon_wkt'):
        f = QgsFeature(lyr.fields())
        f.setGeometry(QgsGeometry.fromWkt(stats['polygon_wkt']))
        f.setAttributes([_r(stats['level'], 2), _r(stats['area_m2'] / 1e6, 4),
                         _r(stats['volume_m3'] / 1e6, 4), _r(stats['mean_depth'], 2),
                         _r(stats['max_depth'], 2), _r(stats['length_m'] / 1e3, 3),
                         _r(stats.get('shoreline_m', float('nan')) / 1e3, 3)])
        lyr.dataProvider().addFeatures([f])
        lyr.updateExtents()
    t = theme.LIGHT
    sym = QgsFillSymbol.createSimple({
        'color': '42,120,214,90', 'outline_color': t['storage'], 'outline_width': '0.4'})
    lyr.renderer().setSymbol(sym)
    return lyr


def axis_layer(model, stats, name='Dam axis'):
    crs = model_crs(model)
    lyr = _memory_layer('LineString', name, crs, AXIS_FIELDS)
    f = QgsFeature(lyr.fields())
    f.setGeometry(QgsGeometry.fromPolylineXY([QgsPointXY(x, y) for x, y in model.dam_coords]))
    f.setAttributes([_r(stats['level'], 2), _r(stats['crest_level'], 2), _r(stats['dam_height'], 2),
                     _r(stats['crest_length'], 1), _r(stats['fill_m3'] / 1e6, 4),
                     _r(stats['storage_fill_ratio'], 2)])
    lyr.dataProvider().addFeatures([f])
    lyr.updateExtents()
    sym = QgsLineSymbol.createSimple({'line_color': theme.LIGHT['dam'], 'line_width': '0.9',
                                      'capstyle': 'round'})
    lyr.renderer().setSymbol(sym)
    return lyr


def eac_layer(model, name='Elevation-area-capacity'):
    lyr = _memory_layer('None', name, None, EAC_FIELDS)
    lv, a, v = model.curve()
    feats = []
    for h, aa, vv in zip(lv, a, v):
        f = QgsFeature(lyr.fields())
        f.setAttributes([_r(h, 3), _r(aa, 1), _r(aa / 1e6, 5), _r(vv, 1), _r(vv / 1e6, 5)])
        feats.append(f)
    lyr.dataProvider().addFeatures(feats)
    return lyr


def depth_raster(model, level, path=None):
    """Write the water depth grid at ``level`` and return a styled layer."""
    if path is None:
        fd, path = tempfile.mkstemp(prefix='reservoir_depth_', suffix='.tif')
        os.close(fd)
    depth = model.depth_array(level)
    terrain.write_geotiff(path, model.grid, depth)
    lyr = QgsRasterLayer(path, 'Water depth {:.1f} m'.format(level))
    style_depth(lyr, float(level - model.bed_level))
    return lyr


def style_depth(layer, max_depth):
    ramp = QgsStyle.defaultStyle().colorRamp('Blues')
    shader_fn = QgsColorRampShader(0.0, max(max_depth, 0.1), ramp,
                                   QgsColorRampShader.Type.Interpolated)
    shader_fn.classifyColorRamp(5, -1)
    shader = QgsRasterShader()
    shader.setRasterShaderFunction(shader_fn)
    renderer = QgsSingleBandPseudoColorRenderer(layer.dataProvider(), 1, shader)
    renderer.setClassificationMin(0.0)
    renderer.setClassificationMax(max(max_depth, 0.1))
    layer.setRenderer(renderer)
    layer.renderer().setOpacity(0.85)


def add_to_project(model, stats, include_depth=True):
    """Add reservoir, dam axis and depth layers in a new layer-tree group."""
    project = QgsProject.instance()
    root = project.layerTreeRoot()
    group = root.insertGroup(0, 'Reservoir · NWL {:.1f} m'.format(stats['level']))
    layers = [axis_layer(model, stats), reservoir_layer(model, stats)]
    if include_depth:
        layers.append(depth_raster(model, stats['level']))
    for lyr in layers:
        project.addMapLayer(lyr, False)
        group.addLayer(lyr)
    return layers


def write_csv(model, path):
    lv, a, v = model.curve()
    with open(path, 'w', newline='', encoding='utf-8') as fh:
        w = csv.writer(fh)
        w.writerow(['level_m', 'area_m2', 'area_km2', 'volume_m3', 'volume_hm3'])
        for h, aa, vv in zip(lv, a, v):
            w.writerow(['{:.3f}'.format(h), '{:.1f}'.format(aa), '{:.5f}'.format(aa / 1e6),
                        '{:.1f}'.format(vv), '{:.5f}'.format(vv / 1e6)])
    return path


def write_geopackage(model, stats, path):
    """Reservoir polygon, dam axis and EAC table in one GeoPackage."""
    ctx = QgsCoordinateTransformContext()
    first = True
    for lyr, name in ((reservoir_layer(model, stats), 'reservoir'),
                      (axis_layer(model, stats), 'dam_axis'),
                      (eac_layer(model), 'eac_table')):
        opts = QgsVectorFileWriter.SaveVectorOptions()
        opts.driverName = 'GPKG'
        opts.layerName = name
        opts.actionOnExistingFile = (QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteFile
                                     if first else
                                     QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteLayer)
        res = QgsVectorFileWriter.writeAsVectorFormatV3(lyr, path, ctx, opts)
        if res[0] != QgsVectorFileWriter.WriterError.NoError:
            raise IOError(res[1] if len(res) > 1 else 'Could not write {}'.format(path))
        first = False
    return path


def table_text(model):
    lv, a, v = model.curve()
    rows = ['Water level (m)\tArea (km²)\tStorage (hm³)']
    for h, aa, vv in zip(lv, a, v):
        rows.append('{:.2f}\t{:.4f}\t{:.4f}'.format(h, aa / 1e6, vv / 1e6))
    return '\n'.join(rows)
