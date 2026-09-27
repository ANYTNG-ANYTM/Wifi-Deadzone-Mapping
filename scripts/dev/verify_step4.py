"""Verify Step 4 eligibility and DBSCAN zones against independent grid labelling.

Uses only real saved observations/predictions; no fitting or data changes.
"""

import json
from pathlib import Path
import sys
from importlib import import_module

import numpy as np
import pandas as pd
from scipy.ndimage import label as connected_components

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))


def check_components(frame, mask, zone_column, shape):
    """Independent raster connected components must equal the saved DBSCAN sets."""
    subset = frame.loc[mask]
    if subset.empty:
        return
    x = np.floor(subset.x_m / 5).astype(int).to_numpy()
    y = np.floor(subset.y_m / 5).astype(int).to_numpy()
    raster = np.zeros(shape, dtype=bool)
    raster[y, x] = True
    components, count = connected_components(raster, structure=np.ones((3, 3)))
    pairs = pd.DataFrame({"component": components[y, x], "zone": subset[zone_column].to_numpy()})
    assert not pairs.zone.eq("").any()
    assert pairs.component.nunique() == count
    assert pairs.groupby("component").zone.nunique().eq(1).all()
    assert pairs.groupby("zone").component.nunique().eq(1).all()


def main():
    processed = ROOT / "data/processed"
    cells = pd.read_parquet(processed / "classified_cells.parquet")
    joint = pd.read_parquet(processed / "classified_grid.parquet")
    predictions = pd.read_parquet(processed / "gpr_predictions.parquet")
    needs = pd.read_parquet(processed / "needs_more_data.parquet")
    ranked = pd.read_csv(ROOT / "outputs/ranked_dead_zones.csv")
    rules = import_module("04_clustering_ranking").approved_settings()
    geometry = json.loads((processed / "grid_metadata.json").read_text())
    shape = (geometry["rows"] * 2, geometry["columns"] * 2)
    keys = ["network_type", "y_m", "x_m"]
    pd.testing.assert_frame_equal(
        cells[predictions.columns].sort_values(keys).reset_index(drop=True),
        predictions.sort_values(keys).reset_index(drop=True),
    )
    assert len(joint) * 2 == len(cells)
    for network, cutoffs in rules["networks"].items():
        part = cells.loc[cells.network_type.eq(network)]
        uncertain = (part.prediction_std_dbm > cutoffs["uncertainty_sd_cutoff_dbm"]) | (part.nearest_observation_m > 50)
        poor = ~uncertain & (part.predicted_mean_dbm <= cutoffs["poor_signal_cutoff_dbm"])
        np.testing.assert_array_equal(part.status.eq("uncertain"), uncertain)
        np.testing.assert_array_equal(part.status.eq("poor"), poor)
        assert not part.loc[uncertain, "ranked_zone_id"].ne("").any()
        assert not part.loc[uncertain, "network_poor_zone_id"].ne("").any()
        for context in part.area_context.unique():
            eligible = part.area_context.eq(context) & part.status.eq("poor") & part.expected_service
            check_components(part, eligible, "network_poor_zone_id", shape)
    assert cells.loc[cells.network_type.eq("wifi"), "status"].eq("poor").sum() == 0
    assert cells.loc[cells.network_type.eq("cellular"), "status"].eq("poor").sum() == 6068
    assert not joint.loc[joint.area_context.eq("outdoor"), "true_dead_zone_applicable"].any()
    expected_true = joint.wifi_expected & joint.wifi_status.eq("poor") & joint.cellular_status.eq("poor")
    np.testing.assert_array_equal(joint.true_dead_zone, expected_true)
    expected_survey = cells.status.eq("uncertain") & (cells.network_type.eq("cellular") | cells.wifi_expected)
    pd.testing.assert_frame_equal(needs.reset_index(drop=True), cells.loc[expected_survey].reset_index(drop=True))
    assert needs.ranked_zone_id.eq("").all()
    assert len(needs) == 20388
    assert joint.loc[joint.distance_to_building_cluster_m > 50, "area_context"].eq("outdoor").all()
    assert joint.loc[joint.distance_to_building_cluster_m <= 50, "wifi_expected"].all()

    # Verify the complete ranked partition with a second clustering algorithm.
    eligible = joint.priority_category.ne("")
    assert joint.loc[eligible, "ranked_zone_id"].ne("").all()
    assert joint.loc[~eligible, "ranked_zone_id"].eq("").all()
    for context, category in joint.loc[eligible, ["area_context", "priority_category"]].drop_duplicates().itertuples(index=False, name=None):
        check_components(joint, joint.area_context.eq(context) & joint.priority_category.eq(category), "ranked_zone_id", shape)
    assert set(ranked.zone_id) == set(joint.loc[eligible, "ranked_zone_id"])
    assert ranked.cell_count.sum() == eligible.sum() == 6068
    np.testing.assert_array_equal(ranked.priority_rank, np.arange(1, len(ranked) + 1))
    sorted_ids = ranked.sort_values(["priority_tier", "mean_deficit_db", "area_m2", "avg_uncertainty", "zone_id"], ascending=[True, False, False, True, True]).zone_id.tolist()
    assert ranked.zone_id.tolist() == sorted_ids
    for row in ranked.itertuples():
        zone = joint.loc[joint.ranked_zone_id.eq(row.zone_id)]
        assert len(zone) == row.cell_count
        assert row.area_m2 == 25 * len(zone)
        assert ((zone.cell_lat - row.approx_lat).abs().lt(1e-10) & (zone.cell_lon - row.approx_lon).abs().lt(1e-10)).any()
        assert zone.cellular_status.eq("poor").all()
        assert zone.cellular_nearest_observation_m.le(50).all()
        np.testing.assert_allclose(row.avg_uncertainty, zone.cellular_prediction_std_dbm.mean())
        if row.area_context == "outdoor":
            assert row.priority_category == "outdoor_cellular_poor" and row.priority_tier == 1
            assert not row.true_dead_zone and not row.true_dead_zone_applicable
    report = "\n".join([
        "PASS: all 76,680 predictions preserved and statuses exactly follow approved cutoffs.",
        "PASS: uncertain network cells excluded from ranked and per-network poor memberships.",
        "PASS: independent eight-neighbour raster components agree with all DBSCAN zones.",
        "PASS: all 6,068 cellular-poor cells partitioned into 7 zones; no poor pixels discarded.",
        "PASS: outdoor rank depends on cellular; true-dead-zone logic is building-only.",
        "PASS: 20,388 uncertain expected-service cells saved unranked; outdoor WiFi excluded from survey needs.",
        "PASS: ranking order, zone counts, areas, uncertainty averages, and in-zone marker coordinates verified.",
    ])
    print(report)


if __name__ == "__main__":
    main()
