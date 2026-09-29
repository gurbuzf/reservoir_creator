# -*- coding: utf-8 -*-
"""Make the plugin importable as a package whatever its folder is called."""
import importlib
import os
import sys

import pytest

PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(PLUGIN_DIR))
PKG = os.path.basename(PLUGIN_DIR)

try:
    from osgeo import gdal
    gdal.UseExceptions()
except ImportError:  # pragma: no cover
    gdal = None


def core(name):
    return importlib.import_module('{}.core.{}'.format(PKG, name))


@pytest.fixture
def sample_dem():
    return os.path.join(PLUGIN_DIR, 'data', 'dem_utm37.tif')


SAMPLE_AXIS = [(747142.0795318595, 4517298.227017025), (747466.5565311552, 4517032.133422447)]
