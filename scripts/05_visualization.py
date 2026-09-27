"""Step 5: Folium map with signal rasters, uncertainty, and contextual priorities.

Run: .venv/Scripts/python.exe scripts/05_visualization.py
Raster colours encode predicted dBm directly; they are not a point-density
heatmap, which would confound reading counts with signal strength.
"""

import html
import json
from pathlib import Path
from importlib import import_module

import folium
from branca.element import Element, MacroElement, Template
from matplotlib import colormaps
from matplotlib.colors import Normalize
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
MINOR_FRAGMENTS = {"OUT-CELL-04", "OUT-CELL-03"}
TIER_STYLE = {1: {"colour": "#cf4938", "radius": 13},
              2: {"colour": "#bd790f", "radius": 11},
              3: {"colour": "#316eb0", "radius": 9}}
CONTEXT_LABELS = {"outdoor": "Outdoor", "academic_cluster": "Academic cluster", "hostel_cluster": "Hostel cluster"}


def raster_images(part, shape, vmin, vmax):
    """Keep uncertain means transparent and draw a separate grey hatch mask."""
    uncertainty = part.status.eq("uncertain").to_numpy().reshape(shape)
    values = part.predicted_mean_dbm.to_numpy().reshape(shape)
    # WiFi has no poor zones under the approved rule; use a neutral sequential
    # palette so lower supported WiFi values do not look like red danger zones.
    palette = "viridis" if part.network_type.iloc[0] == "wifi" else "RdYlGn"
    rgba = colormaps[palette](Normalize(vmin=vmin, vmax=vmax)(values))
    rgba[:, :, 3] = np.where(uncertainty, 0.0, 0.72)
    # Upscale only the uncertainty mask so diagonal hatch lines remain legible.
    expanded = np.repeat(np.repeat(uncertainty, 4, axis=0), 4, axis=1)
    y, x = np.indices(expanded.shape)
    stripe = (x + y) % 12 < 2
    hatch = np.zeros((*expanded.shape, 4), dtype=np.uint8)
    hatch[:, :, :3] = np.where(stripe[:, :, None], 100, 155)
    hatch[:, :, 3] = np.where(expanded, np.where(stripe, 150, 82), 0)
    return (rgba * 255).astype(np.uint8), hatch


def zone_popup(row, minor):
    context = CONTEXT_LABELS[row.area_context]
    significance = '<div class="fragment-note">Minor fragment, low confidence<br><small>Small boundary fragment; low confidence in spatial extent. It still meets the approved poor-signal rule.</small></div>' if minor else ""
    true_status = "Not applicable outdoors" if not row.true_dead_zone_applicable else ("Yes" if row.true_dead_zone else "No")
    wifi_context = "WiFi is not expected along this outdoor stretch." if not row.wifi_expected else "WiFi is expected in this building-cluster proxy."
    return f"""<div class="zone-popup"><h3>{html.escape(row.zone_id)}</h3>
    <div class="popup-subtitle">Rank {row.priority_rank} · Tier {row.priority_tier} · {context}</div>{significance}
    <table><tr><th>Cellular mean</th><td>{row.cellular_mean_dbm:.2f} dBm</td></tr>
    <tr><th>5 m cells</th><td>{row.cell_count:,}</td></tr>
    <tr><th>Average SD</th><td>{row.avg_uncertainty:.2f} dBm</td></tr>
    <tr><th>Modelled area</th><td>{row.area_m2:,.0f} m²</td></tr>
    <tr><th>Cellular status</th><td>{html.escape(row.cellular_status)}</td></tr>
    <tr><th>WiFi status</th><td>{html.escape(row.wifi_status)}</td></tr>
    <tr><th>True dead zone</th><td>{true_status}</td></tr></table>
    <p>{wifi_context}</p><small>Poor status follows the approved prediction and support rules. Cluster boundaries are geographic proxies.</small></div>"""


def main():
    processed = ROOT / "data/processed"
    output = ROOT / "outputs/maps"
    output.mkdir(parents=True, exist_ok=True)
    cells = pd.read_parquet(processed / "classified_cells.parquet")
    training = pd.read_parquet(processed / "gpr_training_cells.parquet")
    ranked = pd.read_csv(ROOT / "outputs/ranked_dead_zones.csv")
    geometry = json.loads((processed / "grid_metadata.json").read_text())
    rules = import_module("04_clustering_ranking").approved_settings()
    width = geometry["columns"] * geometry["cell_size_m"]
    height = geometry["rows"] * geometry["cell_size_m"]
    shape = (int(height / 5), int(width / 5))
    bounds = [[geometry["origin_lat"], geometry["origin_lon"]],
              [geometry["origin_lat"] + height / geometry["metres_per_lat_degree"],
               geometry["origin_lon"] + width / geometry["metres_per_lon_degree"]]]
    center = np.mean(bounds, axis=0).tolist()
    map_object = folium.Map(location=center, zoom_start=16, tiles=None,
                            control_scale=False, prefer_canvas=True, zoom_control=False,
                            zoom_snap=0.25, zoom_delta=0.5)
    # Embed only the two libraries this map uses. No CDN requests are necessary
    # when opening the final HTML; OSM basemap tiles remain the only online layer.
    vendor = ROOT / "scripts/vendor/map"
    map_object.default_js = []
    map_object.default_css = []
    header = map_object.get_root().header
    header.add_child(Element("<style>" + (vendor / "leaflet.css").read_text(encoding="utf-8") + "</style>"), name="embedded_leaflet_css")
    for asset in ["leaflet.js", "jquery.min.js"]:
        source = (vendor / asset).read_text(encoding="utf-8")
        header.add_child(Element("<script>" + source + "\n</script>"), name="embedded_" + asset)
    # The basemap is always present. Network FeatureGroups become the radio
    # choices in LayerControl, so the two signal surfaces cannot obscure each other.
    basemap = folium.TileLayer("OpenStreetMap", control=False, name="OpenStreetMap").add_to(map_object)
    views, masks, inspect_data, layer_stats = {}, {}, {}, {}
    for network in ["cellular", "wifi"]:
        part = cells.loc[cells.network_type.eq(network)].sort_values(["y_m", "x_m"])
        if len(part) != shape[0] * shape[1]:
            raise ValueError(f"Incomplete {network} prediction grid")
        supported = part.loc[part.status.ne("uncertain")]
        vmin = float(supported.predicted_mean_dbm.min())
        vmax = float(supported.predicted_mean_dbm.max())
        heat, hatch = raster_images(part, shape, vmin, vmax)
        group = folium.FeatureGroup(name=f"{'Cellular' if network == 'cellular' else 'WiFi'} signal heatmap", overlay=False, show=network == "cellular")
        folium.raster_layers.ImageOverlay(heat, bounds=bounds, origin="lower", mercator_project=True,
                                          pixelated=True, control=False, zindex=200).add_to(group)
        group.add_to(map_object)
        views[network] = group
        masks[network] = folium.raster_layers.ImageOverlay(hatch, bounds=bounds, origin="lower", mercator_project=True,
                                                          pixelated=True, control=False, zindex=210)
        inspect_data[network] = {
            "mean": part.predicted_mean_dbm.round(3).tolist(),
            "sd": part.prediction_std_dbm.round(3).tolist(),
            "distance": part.nearest_observation_m.round(2).tolist(),
            "count": part.observed_reading_count_10m.astype(int).tolist(),
            "status": part.status.map({"ok": 0, "poor": 1, "uncertain": 2}).tolist(),
            "context": part.area_context.map({"outdoor": 0, "academic_cluster": 1, "hostel_cluster": 2}).tolist(),
        }
        layer_stats[network] = {
            "vmin": vmin, "vmax": vmax, "supported_cells": len(supported),
            "uncertain_cells": int(part.status.eq("uncertain").sum()),
            "poor_cells": int(part.status.eq("poor").sum()),
            "default_on": network == "cellular",
        }

    uncertain_group = folium.FeatureGroup(name="Uncertain cells · active network", show=True).add_to(map_object)
    masks["cellular"].add_to(uncertain_group)
    # Register the second overlay without displaying it; JS swaps masks with
    # the selected network while preserving the uncertainty checkbox state.
    masks["wifi"].show = False
    masks["wifi"].add_to(map_object)

    zone_group = folium.FeatureGroup(name="Ranked zones · cellular", show=True).add_to(map_object)
    marker_refs, marker_metadata = {}, []
    for row in ranked.itertuples(index=False):
        minor = row.zone_id in MINOR_FRAGMENTS
        style = TIER_STYLE[row.priority_tier]
        radius = 5 if minor else style["radius"]
        colour = "#657381" if minor else style["colour"]
        marker = folium.CircleMarker(
            location=[row.approx_lat, row.approx_lon], radius=radius, color=colour,
            weight=1.5 if minor else 2, opacity=0.85 if minor else 1,
            fill=True, fill_color="#f4f5f6" if minor else colour,
            fill_opacity=0.4 if minor else 0.92, dash_array="2 3" if minor else None,
            bubbling_mouse_events=False,
        ).add_to(zone_group)
        marker.add_child(folium.Popup(zone_popup(row, minor), max_width=340))
        tooltip = f"Rank {row.priority_rank} · {row.zone_id}" + (" · minor fragment, low confidence" if minor else "")
        marker.add_child(folium.Tooltip(tooltip, sticky=True))
        marker_refs[row.zone_id] = marker.get_name()
        marker_metadata.append({
            "zone_id": row.zone_id, "priority_rank": int(row.priority_rank), "priority_tier": int(row.priority_tier),
            "radius_px": radius, "colour": colour, "minor_fragment": minor,
            "label": "minor fragment, low confidence" if minor else "ranked zone",
        })

    for network in ["cellular", "wifi"]:
        samples = folium.FeatureGroup(name=f"Observed {'cellular' if network == 'cellular' else 'WiFi'} cells · counts", show=False)
        for row in training.loc[training.network_type.eq(network)].itertuples(index=False):
            folium.CircleMarker(
                location=[row.cell_lat, row.cell_lon], radius=1.5 + np.log2(row.reading_count + 1),
                color="#222222", weight=0.5, fill=True,
                fill_color="#167c9b" if network == "cellular" else "#7845a3", fill_opacity=0.8,
                bubbling_mouse_events=False,
                tooltip=f"{network}: {row.reading_count} observed readings",
                popup=folium.Popup(f"<b>Observed {network} cell</b><br>Mean: {row.mean_signal_dbm:.2f} dBm<br>Reading count: {row.reading_count}<br>10 m aggregated observations", max_width=240),
            ).add_to(samples)
        samples.add_to(map_object)
    folium.LayerControl(collapsed=False, position="topright").add_to(map_object)
    map_object.fit_bounds(bounds, padding_top_left=(360, 30), padding_bottom_right=(30, 30))

    zone_rows = []
    for row in ranked.itertuples(index=False):
        zone_rows.append({
            "zone_id": row.zone_id, "rank": int(row.priority_rank), "context": CONTEXT_LABELS[row.area_context],
            "count": f"{row.cell_count:,}", "mean": f"{row.cellular_mean_dbm:.1f}",
            "minor": row.zone_id in MINOR_FRAGMENTS,
            "colour": "#657381" if row.zone_id in MINOR_FRAGMENTS else TIER_STYLE[row.priority_tier]["colour"],
        })
    ui = MacroElement()
    ui._name = "DeadzoneMapUI"
    ui._template = Template((ROOT / "scripts/templates/deadzone_map_ui.html").read_text(encoding="utf-8"))
    ui.map_name = map_object.get_name()
    ui.cellular_layer = views["cellular"].get_name()
    ui.wifi_layer = views["wifi"].get_name()
    ui.uncertainty_layer = uncertain_group.get_name()
    ui.cellular_mask = masks["cellular"].get_name()
    ui.wifi_mask = masks["wifi"].get_name()
    ui.zone_layer = zone_group.get_name()
    ui.basemap_layer = basemap.get_name()
    ui.marker_js = "{" + ",".join(json.dumps(k) + ":" + v for k, v in marker_refs.items()) + "}"
    ui.zone_rows = zone_rows
    ui.inspect_json = json.dumps(inspect_data, separators=(",", ":"))
    ui.geometry_json = json.dumps({**geometry, "prediction_columns": shape[1], "prediction_rows": shape[0], "bounds": bounds})
    ui.legend_json = json.dumps(layer_stats)
    ui.rules_json = json.dumps(rules["networks"])
    ui.add_to(map_object)
    output_path = output / "deadzone_map.html"
    map_object.save(output_path)
    manifest = {
        "map_file": str(output_path.relative_to(ROOT)), "default_network": "cellular",
        "network_selection": "Mutually exclusive heatmaps; active-network uncertainty updates automatically",
        "uncertainty_default_on": True, "heatmap_type": "Georeferenced 5 m predicted-dBm raster; uncertain means masked",
        "layers": layer_stats, "markers": marker_metadata,
        "input_classification": "data/processed/classified_cells.parquet",
        "input_ranking": "outputs/ranked_dead_zones.csv",
        "wifi_note": "Modelled WiFi shows uniformly acceptable signal within the supported observed range; no poor zones identified. Outdoor WiFi absence is expected.",
        "runtime_note": "Data, rasters, Leaflet and jQuery embedded in HTML. Only optional street basemap tiles need internet; interactions work offline.",
        "folium_raster_reference": "https://python-visualization.github.io/folium/v0.16.0/user_guide/raster_layers/image_overlay.html",
    }
    (output / "map_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Saved {output_path.relative_to(ROOT)} ({output_path.stat().st_size / 1024 / 1024:.2f} MiB)")
    print("Cellular default on; WiFi off. Active-network uncertainty on. All 7 ranked markers included.")
    print("OUT-CELL-04 and OUT-CELL-03: 5 px muted dashed markers, labelled minor fragment, low confidence.")


if __name__ == "__main__":
    main()
