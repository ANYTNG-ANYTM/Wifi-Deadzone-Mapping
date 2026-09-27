"""Step 4: approved three-state classification and context-aware zone ranking.

Run with .venv/Scripts/python.exe scripts/04_clustering_ranking.py.
WiFi is expected in building clusters, not on the outdoor connecting walk.
Only supported poor predictions enter the priority list. Step 5 is separate.
"""

import json
import os
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "iitg-deadzone-matplotlib"))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import BoundaryNorm, ListedColormap
from matplotlib.patches import Patch
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree
from sklearn.cluster import DBSCAN


PIXEL_M = 5.0
# Eight-neighbour connectivity: touch by an edge or corner, never bridge gaps.
DBSCAN_EPS_M = np.sqrt(2) * PIXEL_M + 1e-6
BUILDING_RADIUS_M = 50.0
BUILDING_ROUTES = {"hostel_cluster": ["barak", "umiam"], "academic_cluster": ["academic_complex"]}
CONTEXTS = ["academic_cluster", "hostel_cluster", "outdoor"]
TIERS = {"building_both_poor": 1, "outdoor_cellular_poor": 1,
         "building_wifi_poor": 2, "building_cellular_poor": 3}


def metre_coordinates(raw, geometry):
    return np.column_stack([
        (raw.lon - geometry["origin_lon"]) * geometry["metres_per_lon_degree"],
        (raw.lat - geometry["origin_lat"]) * geometry["metres_per_lat_degree"],
    ])


def building_context(grid, raw, geometry):
    """Use known building-route observations as spatial references, not filenames.

    No indoor/outdoor labels existed in Step 3. These 50 m neighbourhoods are an
    explicit proxy for building clusters, not measured building footprints.
    Do not seed from the combined WiFi loop: it includes corridor observations.
    """
    result = grid.copy()
    distances = []
    labels = list(BUILDING_ROUTES)
    for label, routes in BUILDING_ROUTES.items():
        seeds = raw.loc[raw.route_id.isin(routes)]
        if seeds.empty:
            raise ValueError(f"No observed reference points for {label}")
        distance, _ = cKDTree(metre_coordinates(seeds, geometry)).query(result[["x_m", "y_m"]])
        result[f"distance_to_{label}_m"] = distance
        distances.append(distance)
    distances = np.column_stack(distances)
    nearest = distances.argmin(axis=1)
    result["nearest_building_cluster"] = np.array(labels)[nearest]
    result["distance_to_building_cluster_m"] = distances.min(axis=1)
    result["area_context"] = np.where(
        result.distance_to_building_cluster_m <= BUILDING_RADIUS_M,
        result.nearest_building_cluster, "outdoor",
    )
    result["wifi_expected"] = result.area_context.ne("outdoor")
    return result


def approved_settings():
    # Frozen approved rules shared by classification, visualization, and verification.
    # The historical proposal and final settings are retained in the Step 4 doc.
    return {
        "approval_status": "approved_by_user",
        # Freeze what was approved rather than silently accepting future edits
        # or recomputed values from the historical proposal file.
        "networks": {
            "wifi": {"poor_signal_cutoff_dbm": -83.0, "uncertainty_sd_cutoff_dbm": 10.767799579805995},
            "cellular": {"poor_signal_cutoff_dbm": -101.0, "uncertainty_sd_cutoff_dbm": 11.763522269946332},
        },
        "distance_limit_m": 50.0,
        "precision_note": "Retain original percentile precision; cellular 11.76 dBm was the rounded approved display value.",
        "status_order": "uncertain if SD > cutoff or distance > 50; otherwise poor if mean <= signal cutoff; otherwise ok",
        "building_proxy": {"reference_routes": BUILDING_ROUTES, "radius_m": BUILDING_RADIUS_M,
                           "interpretation": "Proximity to observed building-cluster routes, not measured indoor location"},
        "dbscan": {"eps_m": DBSCAN_EPS_M, "min_samples": 1, "connectivity": "8-neighbour 5 m grid; no minimum-area exclusion"},
        "priority_tiers": TIERS,
        "within_tier_order": "Mean deficit below relevant signal cutoff descending, area descending, relevant mean SD ascending, stable zone ID",
        "true_dead_zone_rule": "Both networks poor AND within a building-cluster proxy; not applicable outdoors",
        "uncertain_handling": "Exclude uncertain network cells from poor clusters; retain visibly and list uncertain expected service as needs more data without rank",
        "wifi_context": "IITG_CONNECT and eduroam are indoor building networks. Outdoor corridor WiFi absence is expected and is not a problem to investigate.",
    }


def classify(predictions, context, settings):
    cells = predictions.merge(context.drop(columns=["cell_lat", "cell_lon"]), on=["x_m", "y_m"], validate="many_to_one")
    cells["status"] = "ok"
    cells["uncertainty_reason"] = ""
    for network, cutoffs in settings["networks"].items():
        selected = cells.network_type.eq(network)
        sd_flag = cells.prediction_std_dbm > cutoffs["uncertainty_sd_cutoff_dbm"]
        far_flag = cells.nearest_observation_m > settings["distance_limit_m"]
        uncertain = sd_flag | far_flag
        poor = cells.predicted_mean_dbm <= cutoffs["poor_signal_cutoff_dbm"]
        cells.loc[selected & poor & ~uncertain, "status"] = "poor"
        cells.loc[selected & uncertain, "status"] = "uncertain"
        cells.loc[selected & sd_flag & ~far_flag, "uncertainty_reason"] = "high_prediction_sd"
        cells.loc[selected & far_flag & ~sd_flag, "uncertainty_reason"] = "distance_over_50m"
        cells.loc[selected & far_flag & sd_flag, "uncertainty_reason"] = "high_prediction_sd_and_distance_over_50m"
    cells["expected_service"] = cells.network_type.eq("cellular") | cells.wifi_expected
    cells["needs_more_data"] = cells.status.eq("uncertain") & cells.expected_service
    cells["network_poor_zone_id"] = ""
    # Keep per-network clusters distinct. Outdoor WiFi is not an actionable
    # service requirement, even if a future model were to predict poor WiFi.
    for network in ["wifi", "cellular"]:
        for area in CONTEXTS:
            selected = cells.network_type.eq(network) & cells.area_context.eq(area) & cells.status.eq("poor") & cells.expected_service
            subset = cells.loc[selected].sort_values(["y_m", "x_m"])
            if subset.empty:
                continue
            labels = DBSCAN(eps=DBSCAN_EPS_M, min_samples=1).fit_predict(subset[["x_m", "y_m"]])
            for label in np.unique(labels):
                zone = f"{network}_{area}_{label + 1:03d}"
                cells.loc[subset.index[labels == label], "network_poor_zone_id"] = zone
    return cells


def combine_networks(cells, context):
    joint = context.copy()
    fields = ["status", "predicted_mean_dbm", "prediction_std_dbm", "nearest_observation_m", "network_poor_zone_id"]
    for network in ["wifi", "cellular"]:
        part = cells.loc[cells.network_type.eq(network), ["x_m", "y_m", *fields]]
        joint = joint.merge(part.rename(columns={field: f"{network}_{field}" for field in fields}), on=["x_m", "y_m"], validate="one_to_one")
    wifi_poor = joint.wifi_status.eq("poor")
    cell_poor = joint.cellular_status.eq("poor")
    building = joint.wifi_expected
    joint["true_dead_zone_applicable"] = building
    joint["true_dead_zone"] = building & wifi_poor & cell_poor
    joint["priority_category"] = ""
    joint.loc[~building & cell_poor, "priority_category"] = "outdoor_cellular_poor"
    joint.loc[building & wifi_poor & ~cell_poor, "priority_category"] = "building_wifi_poor"
    joint.loc[building & cell_poor & ~wifi_poor, "priority_category"] = "building_cellular_poor"
    joint.loc[joint.true_dead_zone, "priority_category"] = "building_both_poor"
    joint["ranked_zone_id"] = ""
    return joint


def summarized_status(series):
    values = sorted(series.unique())
    return values[0] if len(values) == 1 else "mixed:" + ",".join(values)


def rank_zones(joint, settings):
    records = []
    for area in CONTEXTS:
        for category, tier in TIERS.items():
            subset = joint.loc[joint.area_context.eq(area) & joint.priority_category.eq(category)].sort_values(["y_m", "x_m"])
            if subset.empty:
                continue
            labels = DBSCAN(eps=DBSCAN_EPS_M, min_samples=1).fit_predict(subset[["x_m", "y_m"]])
            for label in np.unique(labels):
                zone = subset.loc[labels == label]
                area_code = {"outdoor": "OUT", "academic_cluster": "ACA", "hostel_cluster": "HOS"}[area]
                service_code = {"building_both_poor": "BOTH", "building_wifi_poor": "WIFI",
                                "building_cellular_poor": "CELL", "outdoor_cellular_poor": "CELL"}[category]
                zone_id = f"{area_code}-{service_code}-{label + 1:02d}"
                joint.loc[zone.index, "ranked_zone_id"] = zone_id
                # Marker must fall inside the zone, unlike a concave polygon's
                # arithmetic centroid. Choose its nearest actual member cell.
                centroid = zone[["x_m", "y_m"]].mean().to_numpy()
                anchor = zone.iloc[np.argmin(np.sum((zone[["x_m", "y_m"]].to_numpy() - centroid) ** 2, axis=1))]
                relevant = ["wifi", "cellular"] if category == "building_both_poor" else ["wifi" if category == "building_wifi_poor" else "cellular"]
                deficits = np.column_stack([
                    settings["networks"][n]["poor_signal_cutoff_dbm"] - zone[f"{n}_predicted_mean_dbm"] for n in relevant
                ])
                uncertainty = np.column_stack([zone[f"{n}_prediction_std_dbm"] for n in relevant])
                # For both-poor zones the weaker qualifying margin is conservative;
                # for this collection only cellular-poor zones exist.
                severity = float(deficits.min(axis=1).mean())
                record = {
                    "zone_id": zone_id, "zone_name": f"{area.replace('_', ' ').title()} {service_code.lower()} gap {label + 1}",
                    "approx_lat": anchor.cell_lat, "approx_lon": anchor.cell_lon,
                    "area_context": area, "wifi_expected": bool(anchor.wifi_expected),
                    "wifi_status": summarized_status(zone.wifi_status),
                    "cellular_status": summarized_status(zone.cellular_status),
                    "true_dead_zone_applicable": bool(anchor.wifi_expected),
                    "true_dead_zone": bool(zone.true_dead_zone.all()),
                    "avg_uncertainty": float(uncertainty.max(axis=1).mean()),
                    "uncertainty_network": "+".join(relevant),
                    "priority_category": category, "priority_tier": tier,
                    "mean_deficit_db": severity, "cell_count": len(zone), "area_m2": len(zone) * PIXEL_M ** 2,
                    "cellular_mean_dbm": float(zone.cellular_predicted_mean_dbm.mean()),
                    "cellular_min_dbm": float(zone.cellular_predicted_mean_dbm.min()),
                    "max_relevant_observation_distance_m": float(zone[[f"{n}_nearest_observation_m" for n in relevant]].to_numpy().max()),
                }
                for network in ["wifi", "cellular"]:
                    for status in ["poor", "ok", "uncertain"]:
                        record[f"{network}_{status}_cells"] = int(zone[f"{network}_status"].eq(status).sum())
                records.append(record)
    if not records:
        raise ValueError("No supported poor zones under the approved rules")
    ranked = pd.DataFrame(records).sort_values(
        ["priority_tier", "mean_deficit_db", "area_m2", "avg_uncertainty", "zone_id"],
        ascending=[True, False, False, True, True],
    ).reset_index(drop=True)
    ranked.insert(0, "priority_rank", np.arange(1, len(ranked) + 1))
    return ranked


def plot_status(joint, ranked, geometry, path):
    width = geometry["columns"] * geometry["cell_size_m"]
    height = geometry["rows"] * geometry["cell_size_m"]
    rows, columns = int(height / PIXEL_M), int(width / PIXEL_M)
    ordered = joint.sort_values(["y_m", "x_m"])
    colours = ["#38a17a", "#d74736", "#bcbcbc"]
    fig, axes = plt.subplots(3, 1, figsize=(13, 14), layout="constrained")
    for ax, network in zip(axes[:2], ["wifi", "cellular"]):
        codes = ordered[f"{network}_status"].map({"ok": 0, "poor": 1, "uncertain": 2}).to_numpy().reshape(rows, columns)
        ax.imshow(codes, origin="lower", extent=(0, width, 0, height), interpolation="nearest",
                  cmap=ListedColormap(colours), norm=BoundaryNorm([-0.5, 0.5, 1.5, 2.5], 3))
        ax.set_title(f"{'WiFi' if network == 'wifi' else 'Cellular'} status | grey cells excluded from this network's poor zones")
        ax.legend(handles=[Patch(color=c, label=s) for c, s in zip(colours, ["OK under model rule", "Poor under model rule", "Uncertain"])], loc="upper center", ncol=3, fontsize=8)
    proxy = ordered.area_context.map({"outdoor": 0, "academic_cluster": 1, "hostel_cluster": 2}).to_numpy().reshape(rows, columns)
    axes[2].imshow(proxy, origin="lower", extent=(0, width, 0, height), interpolation="nearest",
                   cmap=ListedColormap(["#eee9df", "#b0cce8", "#c3dfb6"]), vmin=0, vmax=2)
    axes[2].set_title("Building-cluster proxies and ranked cellular-poor zones | WiFi not expected outdoors")
    axes[2].legend(handles=[Patch(color=c, label=s) for c, s in zip(
        ["#eee9df", "#b0cce8", "#c3dfb6"], ["Outdoor / outside building proxy", "Academic cluster proxy", "Hostel cluster proxy"])], loc="upper center", ncol=3, fontsize=8)
    placed = []
    for row in ranked.itertuples():
        zone = joint.loc[joint.ranked_zone_id.eq(row.zone_id)]
        axes[2].scatter(zone.x_m, zone.y_m, s=3, c="#d74736", marker="s", linewidths=0)
        x = (row.approx_lon - geometry["origin_lon"]) * geometry["metres_per_lon_degree"]
        y = (row.approx_lat - geometry["origin_lat"]) * geometry["metres_per_lat_degree"]
        offset = (-15, 5) if x > width - 50 else (5, 5)
        if any(np.hypot(x - px, y - py) < 40 for px, py in placed):
            offset = (-20, 14)
        placed.append((x, y))
        for ax in [axes[1], axes[2]]:
            ax.annotate(str(row.priority_rank), (x, y), xytext=offset, textcoords="offset points", fontsize=9, fontweight="bold",
                        arrowprops={"arrowstyle": "-", "color": "#333333", "linewidth": 0.7},
                        bbox={"boxstyle": "round,pad=0.15", "facecolor": "white", "alpha": 0.85, "edgecolor": "#333333"})
    # Draw proxy boundaries after the poor pixels so geography remains visible
    # even where an entire building-reference neighbourhood is cellular-poor.
    xs = np.sort(ordered.x_m.unique())
    ys = np.sort(ordered.y_m.unique())
    for area, colour in [("academic_cluster", "#225eaa"), ("hostel_cluster", "#347137")]:
        mask = ordered.area_context.eq(area).to_numpy().reshape(rows, columns)
        axes[2].contour(xs, ys, mask, levels=[0.5], colors=[colour], linewidths=1.2, linestyles="--")
    for ax in axes:
        ax.set(xlim=(0, width), ylim=(0, height), xlabel="East of grid origin (m)", ylabel="North of grid origin (m)")
        ax.set_aspect("equal")
    fig.suptitle("Step 4 | approved signal and uncertainty rules\nOutdoor priorities depend on cellular alone; building outlines are not available", fontsize=14)
    fig.savefig(path, dpi=150)
    plt.close(fig)


def main():
    processed = ROOT / "data/processed"
    output = ROOT / "outputs"
    geometry = json.loads((processed / "grid_metadata.json").read_text())
    settings = approved_settings()
    raw = pd.read_parquet(processed / "merged_readings.parquet")
    predictions = pd.read_parquet(processed / "gpr_predictions.parquet")
    grid = predictions[["cell_lat", "cell_lon", "x_m", "y_m"]].drop_duplicates()
    context = building_context(grid, raw, geometry)
    cells = classify(predictions, context, settings)
    joint = combine_networks(cells, context)
    ranked = rank_zones(joint, settings)
    # An uncertain counterpart remains in the joint table, but it is never a
    # ranked poor member of its own network and never implies a known fallback.
    cells = cells.merge(joint[["x_m", "y_m", "ranked_zone_id"]], on=["x_m", "y_m"], validate="many_to_one")
    cells.loc[~(cells.status.eq("poor") & cells.expected_service), "ranked_zone_id"] = ""
    cells.to_parquet(processed / "classified_cells.parquet", index=False)
    joint.to_parquet(processed / "classified_grid.parquet", index=False)
    cells.loc[cells.needs_more_data].to_parquet(processed / "needs_more_data.parquet", index=False)
    ranked.to_csv(output / "ranked_dead_zones.csv", index=False)
    ranked.to_parquet(processed / "ranked_dead_zones.parquet", index=False)
    settings["source_prediction_file"] = "data/processed/gpr_predictions.parquet"
    counts = cells.groupby(["area_context", "network_type", "status"]).size().unstack(fill_value=0)
    needs = cells.loc[cells.needs_more_data].groupby(["area_context", "network_type"]).size().rename("needs_more_data_cells")
    plot_status(joint, ranked, geometry, output / "plots/zone_status_map.png")
    display = ["priority_rank", "zone_id", "approx_lat", "approx_lon", "wifi_status", "cellular_status", "true_dead_zone", "avg_uncertainty", "cell_count", "cellular_mean_dbm"]
    report = "\n".join([
        "STEP 4: APPROVED CLASSIFICATION AND CONTEXT-AWARE RANKING",
        settings["wifi_context"],
        "Building context: within 50 m of manifest-labelled hostel or academic reference observations; not actual building footprints.",
        "Outdoor cellular-poor and building both-poor share highest priority; building WiFi-poor follows; building cellular-poor follows.",
        "Within a tier: worse mean deficit below threshold, then larger area, then lower uncertainty.",
        "DBSCAN: 8-neighbour 5 m cells; min_samples=1; no poor pixels silently discarded.",
        "", "Status counts:", counts.to_string(),
        "", "Priority-ranked zones:", ranked[display].to_string(index=False, float_format=lambda value: f"{value:.6f}"),
        "", "Unranked needs-more-data cells (expected service only):", needs.to_string(),
        "", "Outdoor uncertain WiFi remains in map-ready classified cells but is not a survey priority: WiFi is not expected there.",
        "An uncertain counterpart is unknown, never assumed OK. Outdoor true_dead_zone is not applicable.",
        "Poor status meets the agreed prediction/support rules; it is not a direct test of a failed call or connection.",
        "Interactive final map is generated by scripts/05_visualization.py.",
    ])
    print(report)


if __name__ == "__main__":
    main()
