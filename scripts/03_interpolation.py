"""Step 3 only: separate count-aware Gaussian processes and uncertainty maps.

Run: .venv/Scripts/python.exe scripts/03_interpolation.py
Inputs are observed 10 m cell means from Step 2. Outputs are explicitly marked
as predictions and never appended to the observed dataset. No poor-signal
thresholds or dead-zone classifications are made here.
"""

import json
import os
import tempfile
from pathlib import Path
import warnings

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "iitg-deadzone-matplotlib"))

import joblib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LogNorm, Normalize
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import ConstantKernel, Matern, WhiteKernel
from threadpoolctl import threadpool_limits


PREDICTION_SPACING_M = 5.0
GAP_X_M = (400.0, 1150.0)  # User-specified diagnostic band, not a coverage cutoff.
SEED = 42


def coordinates(frame, metadata, lat="lat", lon="lon"):
    """Apply the exact local metre conversion established in Step 2."""
    return np.column_stack([
        (frame[lon] - metadata["origin_lon"]) * metadata["metres_per_lon_degree"],
        (frame[lat] - metadata["origin_lat"]) * metadata["metres_per_lat_degree"],
    ])


def prepare_training(raw, cells, metadata):
    """Attach raw within-cell variation without changing Step 2's means/counts."""
    size = metadata["cell_size_m"]
    indices = np.floor(coordinates(raw, metadata) / size).astype(int)
    indexed = raw.assign(grid_x=indices[:, 0], grid_y=indices[:, 1])
    stats = indexed.groupby(["network_type", "grid_y", "grid_x"]).signal_strength_dbm.agg(
        raw_count="size", raw_mean="mean", within_cell_variance_dbm2="var",
    ).reset_index()
    centres = coordinates(cells, metadata, "cell_lat", "cell_lon")
    training = cells.assign(
        grid_x=np.floor(centres[:, 0] / size).astype(int),
        grid_y=np.floor(centres[:, 1] / size).astype(int),
        x_m=centres[:, 0], y_m=centres[:, 1],
    ).merge(stats, on=["network_type", "grid_y", "grid_x"], validate="one_to_one")
    if len(training) != len(cells) or len(stats) != len(cells):
        raise ValueError("Raw observations no longer match the Step 2 cell table")
    np.testing.assert_array_equal(training.reading_count, training.raw_count)
    np.testing.assert_allclose(training.mean_signal_dbm, training.raw_mean)

    for network, part in training.groupby("network_type"):
        # Pool within-cell sample variances per network. A singleton's variance
        # is unknown, NOT zero; pooling supplies a variance estimate for it.
        degrees = part.reading_count - 1
        if degrees.sum() <= 0:
            raise ValueError(f"{network}: no repeated observations to estimate noise")
        pooled = float((degrees * part.within_cell_variance_dbm2.fillna(0)).sum() / degrees.sum())
        training.loc[part.index, "pooled_within_cell_variance_dbm2"] = pooled
        # Variance of a mean scales as 1/n under independence. Wardrive samples
        # can be correlated; a separate learned residual and explicit count maps
        # temper this assumption, but do not establish calibrated confidence.
        training.loc[part.index, "mean_noise_variance_dbm2"] = pooled / part.reading_count
    return training.drop(columns=["raw_count", "raw_mean"])


def prediction_grid(metadata):
    """5 m cell centres tile the entire shared Step 2 rectangle, including gaps."""
    width = metadata["columns"] * metadata["cell_size_m"]
    height = metadata["rows"] * metadata["cell_size_m"]
    xx, yy = np.meshgrid(
        np.arange(PREDICTION_SPACING_M / 2, width, PREDICTION_SPACING_M),
        np.arange(PREDICTION_SPACING_M / 2, height, PREDICTION_SPACING_M),
    )
    return np.column_stack([xx.ravel(), yy.ravel()]), xx.shape


def fit_network(training):
    targets = training.mean_signal_dbm.to_numpy()
    offset, scale = float(targets.mean()), float(targets.std())
    if scale == 0:
        raise ValueError("Constant signal targets cannot identify this GP model")
    # Manually standardize both y and its noise variance to keep units consistent.
    alpha = training.mean_noise_variance_dbm2.to_numpy() / scale ** 2 + 1e-10
    kernel = (
        ConstantKernel(1.0, (1e-3, 1e3))
        * Matern(length_scale=50.0, length_scale_bounds=(5.0, 3000.0), nu=1.5)
        + WhiteKernel(noise_level=0.1, noise_level_bounds=(1e-5, 10.0))
    )
    model = GaussianProcessRegressor(
        kernel=kernel, alpha=alpha, normalize_y=False,
        n_restarts_optimizer=2, random_state=SEED,
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        model.fit(training[["x_m", "y_m"]].to_numpy(), (targets - offset) / scale)
    return model, offset, scale, [str(item.message) for item in caught]


def predict_network(model, offset, scale, points, training, raw, metadata):
    means, deviations = [], []
    # Chunk prediction to bound memory; return_std includes the fitted WhiteKernel
    # residual, but not a new raw reading's count-dependent measurement noise.
    for start in range(0, len(points), 4096):
        mean, std = model.predict(points[start:start + 4096], return_std=True)
        means.append(mean * scale + offset)
        deviations.append(std * scale)
    mean = np.concatenate(means)
    std = np.concatenate(deviations)
    residual_variance = float(model.kernel_.k2.noise_level * scale ** 2)
    latent_variance = np.maximum(std ** 2 - residual_variance, 0)
    prior_variance = float(model.kernel_.k1.k1.constant_value * scale ** 2)
    # Opacity is continuous variance reduction, NOT a probability or threshold.
    # Far from observations, the mean reverts to its prior and fades to grey.
    opacity = np.clip(1 - latent_variance / prior_variance, 0, 1)
    distance, _ = cKDTree(coordinates(raw, metadata)).query(points)
    keys = pd.MultiIndex.from_arrays([
        np.floor(points[:, 0] / metadata["cell_size_m"]).astype(int),
        np.floor(points[:, 1] / metadata["cell_size_m"]).astype(int),
    ], names=["grid_x", "grid_y"])
    # This count is the actual parent 10 m cell's count; it is not the count of
    # a distant nearest cell and must not be summed across 5 m predictions.
    counts = training.set_index(["grid_x", "grid_y"]).reading_count.reindex(keys, fill_value=0).to_numpy()
    predictions = pd.DataFrame({
        "cell_lat": metadata["origin_lat"] + points[:, 1] / metadata["metres_per_lat_degree"],
        "cell_lon": metadata["origin_lon"] + points[:, 0] / metadata["metres_per_lon_degree"],
        "x_m": points[:, 0], "y_m": points[:, 1],
        "network_type": training.network_type.iloc[0],
        "predicted_mean_dbm": mean,
        "prediction_std_dbm": std,
        "latent_std_dbm": np.sqrt(latent_variance),
        "nearest_observation_m": distance,
        "observed_reading_count_10m": counts,
        "mean_display_opacity": opacity,
        "method": "gaussian_process",
        "data_status": "predicted",
    })
    return predictions, residual_variance, prior_variance


def plot_network(predictions, training, metadata, shape, uncertainty_max, distance_max, count_max, path):
    network = training.network_type.iloc[0]
    width = metadata["columns"] * metadata["cell_size_m"]
    height = metadata["rows"] * metadata["cell_size_m"]
    extent = (0, width, 0, height)
    fig, axes = plt.subplots(2, 2, figsize=(16, 9), layout="constrained")
    mean_ax, std_ax, count_ax, distance_ax = axes.ravel()
    all_means = np.r_[predictions.predicted_mean_dbm, training.mean_signal_dbm]
    norm = Normalize(vmin=float(all_means.min()), vmax=float(all_means.max()))
    mean_ax.set_facecolor("#dedede")
    mean_image = mean_ax.imshow(
        predictions.predicted_mean_dbm.to_numpy().reshape(shape), origin="lower", extent=extent,
        cmap="viridis", norm=norm, interpolation="nearest",
        alpha=predictions.mean_display_opacity.to_numpy().reshape(shape),
    )
    # Real sampled locations remain visibly distinct from the smooth prediction.
    mean_ax.scatter(training.x_m, training.y_m, s=4, c="black", alpha=0.6, linewidths=0)
    mean_ax.set_title("Predicted mean | fades to grey as spatial support falls\nBlack dots = observed cell centres", fontsize=11)
    fig.colorbar(mean_image, ax=mean_ax, label="Predicted signal (dBm)", shrink=0.8)

    std_image = std_ax.imshow(
        predictions.prediction_std_dbm.to_numpy().reshape(shape), origin="lower", extent=extent,
        cmap="magma", vmin=0, vmax=uncertainty_max, interpolation="nearest",
    )
    std_ax.set_title("UNCERTAINTY | brighter = less certain\nModel SD including fitted residual noise", fontsize=11, fontweight="bold")
    fig.colorbar(std_image, ax=std_ax, label="Prediction standard deviation (dBm)", shrink=0.8)

    # Both marker size and colour distinguish singletons from repeated samples.
    counts = count_ax.scatter(
        training.x_m, training.y_m, c=training.reading_count,
        s=8 + 12 * np.log2(training.reading_count), cmap="cividis",
        norm=LogNorm(vmin=1, vmax=count_max), linewidths=0,
    )
    # Keep one common count scale for both networks using the actual dataset max.
    count_ax.set_title("Actual sampling | small dark dots = one reading\nMarker size and colour show 10 m cell reading_count", fontsize=11)
    count_ticks = sorted({1, int(count_max), *[n for n in [2, 5, 10, 20, 40] if n < count_max]})
    count_bar = fig.colorbar(counts, ax=count_ax, label="Observed readings per 10 m cell", shrink=0.8, ticks=count_ticks)
    count_bar.set_ticklabels([str(n) for n in count_ticks])

    distances = distance_ax.imshow(
        predictions.nearest_observation_m.to_numpy().reshape(shape), origin="lower", extent=extent,
        cmap="YlOrRd", vmin=0, vmax=distance_max, interpolation="nearest",
    )
    distance_ax.set_title("Distance to nearest actual observation\nSampling support, independent of GP assumptions", fontsize=11)
    fig.colorbar(distances, ax=distance_ax, label="Distance (m)", shrink=0.8)
    for ax in axes.ravel():
        for edge in GAP_X_M:
            ax.axvline(edge, color="#555555" if ax in [mean_ax, count_ax] else "cyan", linestyle="--", linewidth=1)
        ax.set(xlabel="East of grid origin (m)", ylabel="North of grid origin (m)", xlim=(0, width), ylim=(0, height))
        ax.set_aspect("equal")
    gap = training.x_m.between(*GAP_X_M)
    fig.suptitle(
        f"{'Campus WiFi' if network == 'wifi' else 'Jio cellular'} | 5 m GP predictions, not confirmed coverage\n"
        f"Dashed lines: x=400–1150 m band; {gap.sum()} observed cells / {training.loc[gap, 'reading_count'].sum()} readings. "
        "Uncertainty is model-based, not independently calibrated.", fontsize=14,
    )
    fig.savefig(path, dpi=160)
    plt.close(fig)


def main():
    processed = ROOT / "data/processed"
    plots = ROOT / "outputs/plots"
    models = ROOT / "outputs/models"
    plots.mkdir(parents=True, exist_ok=True)
    models.mkdir(parents=True, exist_ok=True)
    raw = pd.read_parquet(processed / "merged_readings.parquet")
    cells = pd.read_parquet(processed / "gridded_readings.parquet")
    metadata = json.loads((processed / "grid_metadata.json").read_text())
    training = prepare_training(raw, cells, metadata)
    points, shape = prediction_grid(metadata)
    prediction_parts, summaries = [], []
    notes = {
        "prediction_spacing_m": PREDICTION_SPACING_M,
        "grid_shape": list(shape), "grid_metadata": metadata,
        "noise_method": "Network pooled within-cell variance / count plus fitted WhiteKernel residual",
        "prediction_std_definition": "GP spatial posterior variance plus fitted residual variance; excludes new raw-reading measurement noise",
        "latent_std_definition": "Spatial posterior standard deviation without WhiteKernel residual",
        "mean_display_opacity": "1 - latent posterior variance / latent prior variance, clipped to [0,1]; not a probability",
        "limitations": [
            "Counts may overstate independent samples because wardrive readings are correlated.",
            "Uncertainty is conditional on the fitted model and has not been calibrated on held-out routes.",
            "Cells aggregate APs and sessions; maps describe pooled observations, not throughput or connectivity guarantees.",
            "Near-prior means in unsupported areas are predictions, not evidence of coverage.",
            "Prediction grid includes the less-than-10-m padding of the Step 2 rectangle.",
        ],
        "sklearn_reference": "https://scikit-learn.org/stable/modules/gaussian_process.html",
        "models": {},
    }
    # Limit BLAS threads: these small covariance matrices do not benefit from
    # starting dozens of threads on a laptop.
    with threadpool_limits(limits=2):
        for network in ["wifi", "cellular"]:
            part = training.loc[training.network_type.eq(network)].copy()
            observed = raw.loc[raw.network_type.eq(network)]
            print(f"Fitting {network}: {len(part)} cells / {part.reading_count.sum()} readings...", flush=True)
            model, offset, scale, fit_warnings = fit_network(part)
            pred, residual, prior = predict_network(model, offset, scale, points, part, observed, metadata)
            training.loc[part.index, "fitted_residual_variance_dbm2"] = residual
            training.loc[part.index, "effective_training_noise_variance_dbm2"] = part.mean_noise_variance_dbm2 + residual
            prediction_parts.append(pred)
            gap = part.x_m.between(*GAP_X_M)
            gap_pred = pred.loc[pred.x_m.between(*GAP_X_M)]
            # Distance bins are diagnostics only, never quality or dead-zone flags.
            near = pred.loc[pred.nearest_observation_m <= metadata["cell_size_m"]]
            far = pred.loc[pred.nearest_observation_m >= 10 * metadata["cell_size_m"]]
            summaries.append({
                "network_type": network, "training_cells": len(part),
                "readings": int(part.reading_count.sum()),
                "single_reading_cells": int(part.reading_count.eq(1).sum()),
                "mean_readings_per_cell": float(part.reading_count.mean()),
                "gap_observed_cells": int(gap.sum()),
                "gap_readings": int(part.loc[gap, "reading_count"].sum()),
                "length_scale_m": float(model.kernel_.k1.k2.length_scale),
                "pooled_within_cell_sd_dbm": float(np.sqrt(part.pooled_within_cell_variance_dbm2.iloc[0])),
                "fitted_residual_sd_dbm": float(np.sqrt(residual)),
                "prior_prediction_sd_dbm": float(np.sqrt(prior + residual)),
                "prediction_points": len(pred),
                "predicted_min_dbm": float(pred.predicted_mean_dbm.min()),
                "predicted_max_dbm": float(pred.predicted_mean_dbm.max()),
                "near_10m_median_sd_dbm": float(near.prediction_std_dbm.median()),
                "far_100m_median_sd_dbm": float(far.prediction_std_dbm.median()),
                "gap_median_sd_dbm": float(gap_pred.prediction_std_dbm.median()),
                "gap_median_nearest_observation_m": float(gap_pred.nearest_observation_m.median()),
            })
            notes["models"][network] = {
                "kernel": str(model.kernel_), "target_offset_dbm": offset,
                "target_scale_dbm": scale, "random_seed": SEED,
                "optimizer_restarts": 2, "optimizer_warnings": fit_warnings,
                "log_marginal_likelihood": float(model.log_marginal_likelihood_value_),
            }
            joblib.dump({"model": model, "target_offset_dbm": offset,
                         "target_scale_dbm": scale, "grid_metadata": metadata}, models / f"gpr_{network}.joblib")
            print(f"  Fitted kernel: {model.kernel_}", flush=True)
            for message in fit_warnings:
                print(f"  Fit warning: {message}", flush=True)

    predictions = pd.concat(prediction_parts, ignore_index=True)
    predictions.to_parquet(processed / "gpr_predictions.parquet", index=False)
    training.to_parquet(processed / "gpr_training_cells.parquet", index=False)
    summary = pd.DataFrame(summaries)
    (models / "gpr_metadata.json").write_text(json.dumps(notes, indent=2) + "\n", encoding="utf-8")
    for network in ["wifi", "cellular"]:
        plot_network(
            predictions.loc[predictions.network_type.eq(network)],
            training.loc[training.network_type.eq(network)], metadata, shape,
            predictions.prediction_std_dbm.max(), predictions.nearest_observation_m.max(), training.reading_count.max(),
            plots / f"{network}_signal_uncertainty.png",
        )
    report = "\n".join([
        "STEP 3: count-aware GPR (WiFi and cellular fitted separately)",
        f"Prediction grid: {shape[1]} x {shape[0]} at {PREDICTION_SPACING_M:g} m spacing, per network",
        "Alpha: pooled within-cell signal variance / reading_count, plus learned WhiteKernel residual.",
        "GP SD includes fitted residual; it is not a calibrated guarantee of signal coverage.",
        "Mean panels fade continuously with declining GP variance reduction; grey means weak spatial support.",
        "Near/far diagnostics use <=10 m / >=100 m from raw observations, not classification thresholds.",
        "", summary.T.to_string(float_format=lambda value: f"{value:.3f}"),
        "", "Models:", json.dumps(notes["models"], indent=2),
        "", "Limitations:", *[f"- {item}" for item in notes["limitations"]],
        "", "Predictions saved separately with data_status=predicted. No dead-zone thresholds applied.",
    ])
    print(report)


if __name__ == "__main__":
    main()
