# SpeciesHub QGIS plugin

Loads your SpeciesHub observations into QGIS as a point layer.

- Sign in once (browser, or a pasted token).
- Add data: pick a data container, an observation type, taxon names and an
  area; load into a GeoPackage. One row per observation on its site's point,
  laid out like the app's download: types, author, date, notes, tags and the
  recorded field values, one column per field that has a value somewhere in
  the load (a field nobody filled gets no column).
- Refresh a layer later with the same request.

Needs a SpeciesHub account (https://specieshub.io).

## Development

Requires QGIS 3.34 or later (tested on QGIS 4.2). The plugin is pure Python
and uses only what QGIS ships.

```
make test      # unit tests with QGIS's bundled Python
make deploy    # copy into the local QGIS profiles (QGIS3 and QGIS4)
make zip       # build specieshub.zip for the plugin repository
```

After `make deploy`, enable "SpeciesHub" in QGIS > Plugins > Manage and
Install Plugins. Use the Plugin Reloader plugin while developing.

### Signing in

Connect > "Sign in in browser" opens the SpeciesHub web app, where you confirm;
QGIS signs in by itself once you do (SpeciesHub 1.0.33 or later on the
server). Or make a token under Settings > Connected apps and paste it.
Either way QGIS holds a read-only token of its own; Disconnect in QGIS or
Settings > Connected apps in the app ends it.

The first stored token makes QGIS ask for an authentication master password
(standard QGIS behaviour for its encrypted authentication database; on macOS
and Windows it can be kept in the system keychain).

### End-to-end check without QGIS's window

`tests/` covers the model, the dialogs offscreen and the GeoPackage writer.
The HTTP path was verified by hand against a local backend on port 3080 with
a minted token (2026-10-27): profile, groups, categories, species search,
paged site query, GeoPackage load, 401 handling, and the pairing endpoint's
404 answered as "not supported yet". A headless QgsApplication has no master
password, so such a script must call `authManager().setMasterPassword(...)`
before storing a token or it waits forever on a dialog.

## Licence

GPL-2.0-or-later, as the official QGIS plugin repository requires.
