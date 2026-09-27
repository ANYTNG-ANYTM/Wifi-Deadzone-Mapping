# Step 5: interactive campus connectivity map

Open `outputs/maps/deadzone_map.html` in a browser. The prediction data and raster
images and display libraries are embedded in the HTML. Internet is needed only
for the OpenStreetMap street basemap. Without it, the signal layers, markers,
popups, and controls still work over a neutral background.

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
- Click a sidebar zone to open its popup and zoom to it. On a narrow screen, use
  the Map guide & zones button to open the guide.

## Signal and uncertainty

Heatmap colours directly encode each network's predicted dBm on its own scale.
These are georeferenced 5 m rasters, not density heatmaps that accumulate values
where sample counts are higher. The renderer uses Folium's
[ImageOverlay with Mercator projection](https://python-visualization.github.io/folium/v0.16.0/user_guide/raster_layers/image_overlay.html).

Uncertain cells have no signal colour. Instead, a separate grey/hatched image
shows them. Turning uncertainty off exposes the basemap, not an unsupported
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

Browser verification requires `requirements-dev.txt` and an installed Chrome or
Edge. It launches a fresh headless browser without accessing a personal profile.
It blocks all external requests before they reach the network and checks layer
defaults/switching, uncertainty masks, all popup values, fragment styling, cell
inspection, sidebar navigation, mobile controls, and browser errors. Live basemap
tile loading is not verified: automatic approval review rejected that test because
tile requests disclose the map's geographic extent to external services.

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
- NOT TESTED: live street basemap tile loading; this verification deliberately blocks external requests.

The verifier prints results without rewriting submission artifacts or preview PNGs.
