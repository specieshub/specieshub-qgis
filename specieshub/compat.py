"""Qt 5 / Qt 6 differences in one place.

PyQt6 only accepts scoped enums (QNetworkRequest.Attribute.HttpStatusCodeAttribute);
PyQt5 accepts both. The plugin always asks through enum_value so one source runs
on QGIS 3.44 (Qt 5) and QGIS 4 (Qt 6).
"""


def enum_value(owner, scope, name):
    holder = getattr(owner, scope, None)
    if holder is not None and hasattr(holder, name):
        return getattr(holder, name)
    return getattr(owner, name)
