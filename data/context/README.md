# Embedded campus basemap

`campus_basemap.geojson` contains OpenStreetMap road, building, water, and land
geometry for the campus survey area. Copyright OpenStreetMap contributors;
distributed under the [Open Database License 1.0](https://opendatacommons.org/licenses/odbl/1-0/).
See [OpenStreetMap attribution and copyright](https://www.openstreetmap.org/copyright).

The GeoJSON records the source request, bounds, and OSM data timestamp. It is a
limited snapshot for geographic display, not a complete worldwide street map.
It has no role in signal fitting, classification, or the building-context proxy.

`scripts/dev/fetch_campus_basemap.py` can refresh this extract explicitly.
Normal map builds embed the saved geometry in HTML and make no network requests.
