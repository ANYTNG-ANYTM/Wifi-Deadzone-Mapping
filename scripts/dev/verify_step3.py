"""Validate Step 3 using actual project observations and saved fitted models.

Run: .venv/Scripts/python.exe scripts/dev/verify_step3.py
This does not refit models, fabricate readings, or change any data outputs.
"""

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from scipy.linalg import solve_triangular
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parents[2]


def main():
    processed = ROOT / "data/processed"
    raw = pd.read_parquet(processed / "merged_readings.parquet")
    cells = pd.read_parquet(processed / "gridded_readings.parquet")
    training = pd.read_parquet(processed / "gpr_training_cells.parquet")
    predictions = pd.read_parquet(processed / "gpr_predictions.parquet")
    metadata = json.loads((processed / "grid_metadata.json").read_text())
    assert raw.data_status.eq("observed").all()
    assert predictions.data_status.eq("predicted").all()
    assert not predictions.duplicated(["cell_lat", "cell_lon", "network_type"]).any()
    numeric = predictions.select_dtypes(include="number")
    assert np.isfinite(numeric).all().all()
    assert predictions.prediction_std_dbm.gt(0).all()
    assert predictions.latent_std_dbm.ge(0).all()
    assert predictions.mean_display_opacity.between(0, 1).all()
    assert predictions.nearest_observation_m.ge(0).all()
    assert training.reading_count.sum() == len(raw)
    keys = ["cell_lat", "cell_lon", "network_type"]
    pd.testing.assert_frame_equal(
        cells.sort_values(keys).reset_index(drop=True),
        training[cells.columns].sort_values(keys).reset_index(drop=True),
    )
    # Coverage refers to pixel edges, not their centres: each 5 m pixel extends
    # 2.5 m outward from its reported coordinate.
    half_lat = 2.5 / metadata["metres_per_lat_degree"]
    half_lon = 2.5 / metadata["metres_per_lon_degree"]
    assert predictions.cell_lat.min() - half_lat <= raw.lat.min() + 1e-10
    assert predictions.cell_lat.max() + half_lat >= raw.lat.max()
    assert predictions.cell_lon.min() - half_lon <= raw.lon.min() + 1e-10
    assert predictions.cell_lon.max() + half_lon >= raw.lon.max()

    lines = []
    grids = []
    for network in ["wifi", "cellular"]:
        p = predictions.loc[predictions.network_type.eq(network)].reset_index(drop=True)
        t = training.loc[training.network_type.eq(network)]
        r = raw.loc[raw.network_type.eq(network)]
        grids.append(p[["cell_lat", "cell_lon", "x_m", "y_m"]])
        assert len(p) == metadata["rows"] * metadata["columns"] * 4
        fitted = joblib.load(ROOT / "outputs/models" / f"gpr_{network}.joblib")
        model = fitted["model"]
        scale, offset = fitted["target_scale_dbm"], fitted["target_offset_dbm"]
        np.testing.assert_allclose(model.X_train_, t[["x_m", "y_m"]])
        np.testing.assert_allclose(model.y_train_, (t.mean_signal_dbm - offset) / scale)
        np.testing.assert_allclose(model.alpha, t.mean_noise_variance_dbm2 / scale ** 2 + 1e-10)
        np.testing.assert_allclose(t.mean_noise_variance_dbm2 * t.reading_count, t.pooled_within_cell_variance_dbm2)
        by_count = t.groupby("reading_count").effective_training_noise_variance_dbm2.first().sort_index()
        assert np.all(np.diff(by_count) < 0), "Observation noise should fall with increasing count"

        # Recompute posterior mean/variance directly from the fitted covariance
        # factor at sampled prediction points, independently of predict().
        indices = sorted(set(np.linspace(0, len(p) - 1, 31, dtype=int).tolist()
                             + [int(p.nearest_observation_m.idxmin()), int(p.nearest_observation_m.idxmax())]))
        selected = p.iloc[indices]
        xy = selected[["x_m", "y_m"]].to_numpy()
        cross = model.kernel_(xy, model.X_train_)
        posterior_mean = (cross @ model.alpha_) * scale + offset
        projected = solve_triangular(model.L_, cross.T, lower=True)
        posterior_variance = (model.kernel_.diag(xy) - np.sum(projected ** 2, axis=0)) * scale ** 2
        np.testing.assert_allclose(posterior_mean, selected.predicted_mean_dbm, atol=1e-9)
        np.testing.assert_allclose(posterior_variance, selected.prediction_std_dbm ** 2, atol=1e-9)
        residual = model.kernel_.k2.noise_level * scale ** 2
        prior = model.kernel_.k1.k1.constant_value * scale ** 2
        np.testing.assert_allclose(p.latent_std_dbm ** 2 + residual, p.prediction_std_dbm ** 2, atol=1e-9)
        assert (p.latent_std_dbm ** 2 <= prior + 1e-8).all()

        # Verify support distances against actual GPS observations, not GP cells.
        actual_xy = np.column_stack([
            (r.lon - metadata["origin_lon"]) * metadata["metres_per_lon_degree"],
            (r.lat - metadata["origin_lat"]) * metadata["metres_per_lat_degree"],
        ])
        distance, _ = cKDTree(actual_xy).query(p[["x_m", "y_m"]])
        np.testing.assert_allclose(distance, p.nearest_observation_m)
        # There are four 5 m prediction pixels per 10 m parent cell. Counting a
        # parent's observations once per child is support metadata, not new data.
        assert p.observed_reading_count_10m.sum() == 4 * len(r)
        near_sd = p.loc[p.nearest_observation_m <= 10, "prediction_std_dbm"].median()
        far_sd = p.loc[p.nearest_observation_m >= 100, "prediction_std_dbm"].median()
        assert far_sd > near_sd, "Uncertainty should increase away from observations"
        lines.append(f"PASS {network}: count weights, posterior equations/units, support distances, and increasing uncertainty away from data.")

    pd.testing.assert_frame_equal(grids[0], grids[1])
    lines.append("PASS: original Step 2 means/counts retained; shared complete 5 m grid; all 76,680 predictions finite and labelled predicted.")
    report = "\n".join(lines) + "\n"
    print(report)


if __name__ == "__main__":
    main()
