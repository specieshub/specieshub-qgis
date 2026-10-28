# Uses QGIS's own Python so tests see the same qgis and PyQt the plugin runs on.
QGIS_APP ?= $(firstword $(wildcard /Applications/QGIS*.app))
PY = "$(QGIS_APP)/Contents/MacOS/python"
PLUGIN = specieshub
PROFILES = "$(HOME)/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins" \
           "$(HOME)/Library/Application Support/QGIS/QGIS4/profiles/default/python/plugins"

.PHONY: test deploy zip clean

test:
	QT_QPA_PLATFORM=offscreen $(PY) -m unittest discover -s tests -v

deploy:
	@for p in $(PROFILES); do \
	  if [ -d "$$p" ]; then rm -rf "$$p/$(PLUGIN)"; cp -R $(PLUGIN) "$$p/$(PLUGIN)"; echo "deployed to $$p"; fi; \
	done

zip: clean
	zip -r $(PLUGIN).zip $(PLUGIN) -x '*/__pycache__/*' '*.pyc'

clean:
	find $(PLUGIN) tests -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null; rm -f $(PLUGIN).zip
