# SpeciesHub QGIS plugin. GPL-2.0-or-later, see LICENSE.


def classFactory(iface):
    from .plugin import SpeciesHubPlugin
    return SpeciesHubPlugin(iface)
