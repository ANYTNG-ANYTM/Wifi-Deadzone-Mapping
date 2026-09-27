"""Check the generated Folium map in an installed Brave, Chrome, or Edge browser.

Run: .venv/Scripts/python.exe scripts/dev/verify_step5.py
Requires requirements-dev.txt. Uses a fresh headless browser, never a personal
browser profile. All external requests are aborted before network access; this
checks the embedded campus basemap and interactions offline.
"""

import json
from pathlib import Path
import sys
from importlib import import_module

import numpy as np
import pandas as pd
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
raster_images = import_module("05_visualization").raster_images


def main():
    map_file = ROOT / "outputs/maps/deadzone_map.html"
    manifest = json.loads((map_file.parent / "map_manifest.json").read_text())
    ranked = pd.read_csv(ROOT / "outputs/ranked_dead_zones.csv")
    cells = pd.read_parquet(ROOT / "data/processed/classified_cells.parquet")
    assert len(manifest["markers"]) == len(ranked) == 7
    for network in ["cellular", "wifi"]:
        part = cells.loc[cells.network_type.eq(network)].sort_values(["y_m", "x_m"])
        limits = manifest["layers"][network]
        shape = (part.y_m.nunique(), part.x_m.nunique())
        heat, mask = raster_images(part, shape, limits["vmin"], limits["vmax"])
        uncertain = part.status.eq("uncertain").to_numpy().reshape(shape)
        assert (heat[:, :, 3][uncertain] == 0).all()
        assert (heat[:, :, 3][~uncertain] > 0).all()
        np.testing.assert_array_equal(mask[::4, ::4, 3] > 0, uncertain)

    candidates = [Path("C:/Program Files/BraveSoftware/Brave-Browser/Application/brave.exe"),
                  Path("C:/Program Files/Google/Chrome/Application/chrome.exe"),
                  Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe")]
    executable = next((p for p in candidates if p.exists()), None)
    if executable is None:
        raise RuntimeError("No Brave, Chrome, or Edge installation found")
    errors = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(executable), headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)
        # Never disclose survey geography to a tile server during verification.
        external_requests = []
        page.route("https://**/*", lambda route: (external_requests.append(route.request.url), route.abort()))
        page.route("http://**/*", lambda route: (external_requests.append(route.request.url), route.abort()))
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(map_file.as_uri(), wait_until="networkidle", timeout=60000)
        page.wait_for_function("window.deadzoneMap !== undefined", timeout=30000)
        state = page.evaluate("""() => {
          const s=window.deadzoneMap;return {network:s.getActiveNetwork(),cell:s.map.hasLayer(s.views.cellular),
            wifi:s.map.hasLayer(s.views.wifi),uncertainty:s.map.hasLayer(s.uncertainty),
            cellMask:s.uncertainty.hasLayer(s.masks.cellular),wifiMask:s.map.hasLayer(s.masks.wifi),
            markers:Object.keys(s.markers).length,tiles:[...document.querySelectorAll('.leaflet-tile')].filter(i=>i.complete&&i.naturalWidth>0).length};
        }""")
        assert state["network"] == "cellular" and state["cell"] and not state["wifi"]
        assert state["uncertainty"] and state["cellMask"] and not state["wifiMask"]
        assert state["markers"] == 7
        assert state["tiles"] == 0, "Offline verification must not load external tiles"
        assert page.evaluate("window.deadzoneMap.map.hasLayer(window.deadzoneMap.basemap)")
        assert page.evaluate("window.deadzoneMap.map.getPane('campusBasemap').querySelectorAll('path').length") > 100
        assert page.locator('.campus-place-label').filter(has_text='Umiam Hostel').count() == 1
        assert page.locator('.campus-place-label').filter(has_text='Barak Hostel').count() == 1
        assert page.locator('.leaflet-control-attribution').inner_text().find('OpenStreetMap contributors') >= 0
        panel_toggle = page.locator("#panel-toggle")
        assert panel_toggle.is_visible() and panel_toggle.get_attribute("aria-expanded") == "true"
        panel_toggle.click()
        assert not page.locator("#campus-panel").is_visible()
        assert panel_toggle.get_attribute("aria-expanded") == "false"
        panel_toggle.click()
        assert page.locator("#campus-panel").is_visible()
        for row in ranked.itertuples(index=False):
            details = page.evaluate("""id => {
              const m=window.deadzoneMap.markers[id];m.openPopup();
              return {radius:m.getRadius(),dash:m.options.dashArray,content:m.getPopup().getContent()};
            }""", row.zone_id)
            # Leaflet briefly retains a previous popup during fade-out; target
            # the current zone explicitly rather than matching both DOM nodes.
            popup_text = page.locator(".leaflet-popup-content").filter(has_text=row.zone_id).inner_text()
            for text in [row.zone_id, f"{row.cellular_mean_dbm:.2f}", f"{row.cell_count:,}", f"{row.avg_uncertainty:.2f}", "True dead zone"]:
                assert text in popup_text, (row.zone_id, text)
            if row.zone_id in ["OUT-CELL-03", "OUT-CELL-04"]:
                assert details["radius"] == 5 and details["dash"] == "2 3"
                assert "minor fragment, low confidence" in popup_text.lower()
            else:
                assert details["radius"] > 5
        page.evaluate("window.deadzoneMap.map.closePopup()")
        page.locator(".leaflet-control-layers-base label").filter(has_text="WiFi signal heatmap").click()
        page.wait_for_function("window.deadzoneMap.getActiveNetwork() === 'wifi'")
        assert page.evaluate("window.deadzoneMap.map.hasLayer(window.deadzoneMap.views.wifi) && !window.deadzoneMap.map.hasLayer(window.deadzoneMap.views.cellular)")
        assert page.evaluate("window.deadzoneMap.uncertainty.hasLayer(window.deadzoneMap.masks.wifi) && !window.deadzoneMap.map.hasLayer(window.deadzoneMap.masks.cellular)")
        assert "uniformly acceptable" in page.locator("#network-note").inner_text()
        assert "no poor zones identified" in page.locator("#network-note").inner_text()
        wifi_uncertain = cells.loc[cells.network_type.eq("wifi") & cells.status.eq("uncertain")].iloc[0]
        result = page.evaluate("p => window.deadzoneMap.inspectCell(L.latLng(p[0],p[1]))", [wifi_uncertain.cell_lat, wifi_uncertain.cell_lon])
        assert result["status"] == "uncertain" and result["network"] == "wifi"
        assert "Nearest observation" in page.locator(".leaflet-popup-content").last.inner_text()
        page.evaluate("window.deadzoneMap.map.closePopup()")

        uncertainty_checkbox = page.locator(".leaflet-control-layers-overlays label").filter(has_text="Uncertain cells")
        uncertainty_checkbox.click()
        assert not page.evaluate("window.deadzoneMap.map.hasLayer(window.deadzoneMap.uncertainty)")
        page.locator(".leaflet-control-layers-base label").filter(has_text="Cellular signal heatmap").click()
        page.wait_for_function("window.deadzoneMap.getActiveNetwork() === 'cellular'")
        # Switching network must preserve the user's disabled-overlay choice.
        assert not page.evaluate("window.deadzoneMap.map.hasLayer(window.deadzoneMap.uncertainty)")
        uncertainty_checkbox.click()
        assert page.evaluate("window.deadzoneMap.map.hasLayer(window.deadzoneMap.masks.cellular)")
        # Sidebar click must navigate to and open its corresponding zone.
        page.locator('[data-zone="OUT-CELL-02"]').click()
        assert "OUT-CELL-02" in page.locator(".leaflet-popup-content").last.inner_text()
        page.set_viewport_size({"width": 390, "height": 844})
        page.reload(wait_until="networkidle")
        page.wait_for_function("window.deadzoneMap !== undefined")
        assert page.locator("#panel-toggle").is_visible()
        page.locator("#panel-toggle").click()
        assert page.locator("#campus-panel").is_visible()
        assert page.locator("#panel-toggle").get_attribute("aria-expanded") == "true"
        assert not errors, errors
        assert not external_requests, external_requests
        browser.close()
    report = "\n".join([
        "PASS: cellular on / WiFi off by default, with visible uncertainty; external requests blocked.",
        "PASS: network selector swaps heatmap, uncertainty mask, legend, and cell inspector.",
        "PASS: uncertainty toggle remains consistent across network changes.",
        "PASS: every uncertain cell masked from signal colour and present in the grey hatch raster.",
        "PASS: all 7 popups match ranked CSV; both minor fragments have smaller dashed markers and labels.",
        "PASS: sidebar navigation and desktop/mobile survey panel toggle; no browser JavaScript errors.",
        "PASS: embedded campus roads, buildings, hostel labels, and attribution rendered; zero external requests.",
    ])
    print(report)


if __name__ == "__main__":
    main()
