# Step 5: interactive campus connectivity map

Open `outputs/maps/deadzone_map.html` directly in a browser. Survey layers and a
campus basemap of roads, buildings, lakes, and place labels are embedded in the
HTML. It works without internet or a local server, including in Brave and the
VS Code browser. The saved OpenStreetMap geometry is in
`data/context/campus_basemap.geojson`, with provenance and ODbL license details.
This bounded campus snapshot is used only for display; it does not change the
signal models, classification rules, or building-context proxy.
Panning outside the saved campus area shows an empty background: no worldwide
online basemap is loaded. Download or clone the repository to open the HTML
locally; GitHub's file viewer does not run the interactive map.

## Controls

- Cellular signal starts visible. Select WiFi in the layer control to switch
  networks. The two surfaces are mutually exclusive, and their legends update.
- The grey/hatched uncertainty overlay starts visible and follows the selected
  network. Its checkbox works independently and keeps its state across switches.
- Ranked cellular zones remain available with either signal layer selected.
- Optional observed-cell layers show actual 10 m means; their marker sizes grow
  with reading count. Click them for the observed mean and count.
- Click the heatmap for a predicted value, SD, distance to the nearest observation,
  status, and observation count in the parent 10 m cell.
- Click a sidebar zone to open its popup and zoom to it. Use the Show/Hide survey
  panel button on desktop or mobile to clear or restore the map guide.

## Signal and uncertainty

Heatmap colours directly encode each network's predicted dBm on its own scale.
These are georeferenced 5 m rasters, not density heatmaps that accumulate values
where sample counts are higher. The renderer uses Folium's
[ImageOverlay with Mercator projection](https://python-visualization.github.io/folium/v0.16.0/user_guide/raster_layers/image_overlay.html).

Uncertain cells have no signal colour. Instead, a separate grey/hatched image
shows them. Turning uncertainty off exposes the embedded basemap, not an unsupported
signal prediction. The mask uses exactly the approved Step 4 status field.

The WiFi legend states that the model shows uniformly acceptable signal within
the supported observed range and no poor zones were identified. It also states
plainly that outdoor WiFi absence is expected. This describes the approved model
classification, not every individual raw RSSI reading or a connectivity guarantee.
WiFi uses a neutral sequential palette instead of red danger colours; cellular
uses a red-to-green signal scale. Both legends show their own dBm endpoints.

## Zone markers

All seven approved zones retain their IDs, priority ranks, tier, and measurements.
Display styling does not change the ranked dataset:

| Marker | Radius | Style |
|---|---:|---|
| Tier 1 | 13 px | Red |
| Tier 2, if present | 11 px | Amber |
| Tier 3 | 9 px | Blue |
| OUT-CELL-04 and OUT-CELL-03 | 5 px | Muted grey, dashed, low fill |

The two tiny fragments are explicitly labelled “minor fragment, low confidence.”
Their popups explain that this refers to the spatial extent of small boundary
fragments; their cells still meet the approved poor-signal rule. They appear in
a separate collapsible section of the sidebar rather than alongside the main
five zones at equal visual weight.

Each zone popup includes zone ID, rank/tier, context, cellular mean dBm, 5 m cell
count, average SD, modelled area, both network statuses, and true-dead-zone status.
Outdoors, the latter reads “Not applicable outdoors.”

## Build and verify

Use the project virtual environment:

```powershell
.\.venv\Scripts\python.exe scripts/05_visualization.py
.\.venv\Scripts\python.exe scripts/dev/verify_step5.py
```

Browser verification requires `requirements-dev.txt` and an installed Brave,
Chrome, or Edge on Windows. It launches a fresh headless browser without accessing a personal profile.
It blocks all external requests before they reach the network and checks layer
defaults/switching, uncertainty masks, all popup values, fragment styling, cell
inspection, sidebar navigation, desktop/mobile controls, and browser errors.
The checks also require rendered campus geometry, hostel labels, attribution,
and zero external network requests.

Leaflet and jQuery copies, licence files, public source URLs, and SHA-256 hashes
are retained under `scripts/vendor/map`. `scripts/dev/fetch_map_assets.py` fetches only these
fixed public library assets; it sends no map coordinates or tile requests.

Outputs include `outputs/maps/map_manifest.json`, cellular and WiFi preview screenshots
in `outputs/plots/`. Verification results are consolidated below. The interactive map contains all information
needed to explore the result; screenshots are only previews.

## Final offline browser verification

- PASS: cellular on / WiFi off by default, with visible uncertainty; external requests blocked.
- PASS: network selector swaps heatmap, uncertainty mask, legend, and cell inspector.
- PASS: uncertainty toggle remains consistent across network changes.
- PASS: every uncertain cell masked from signal colour and present in the grey hatch raster.
- PASS: all 7 popups match ranked CSV; both minor fragments have smaller dashed markers and labels.
- PASS: sidebar navigation and mobile guide toggle; no browser JavaScript errors.
- PASS: embedded campus geometry and hostel labels rendered with external requests blocked.

The verifier prints results without rewriting submission artifacts or preview PNGs.
