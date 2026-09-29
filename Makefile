# Reservoir Creator - developer tasks
#   make test      unit tests of the hydrology engine (numpy + GDAL)
#   make smoke     headless run of the whole plugin inside QGIS
#   make zip       plugin package for "Install from ZIP" / plugins.qgis.org

PYTHON ?= python3
PLUGIN  = reservoir_creator
VERSION = $(shell sed -n 's/^version=//p' metadata.txt)

.PHONY: test smoke zip clean

test:
	$(PYTHON) -m pytest -q tests

smoke:
	QT_QPA_PLATFORM=offscreen $(PYTHON) tests/qgis_harness.py build/smoke

zip: clean
	mkdir -p build/$(PLUGIN)
	cp -r __init__.py plugin.py metadata.txt LICENSE README.md core gui icons build/$(PLUGIN)/
	find build/$(PLUGIN) -name '__pycache__' -prune -exec rm -rf {} +
	cd build && zip -qr $(PLUGIN)-$(VERSION).zip $(PLUGIN)
	@echo "build/$(PLUGIN)-$(VERSION).zip"

clean:
	rm -rf build
