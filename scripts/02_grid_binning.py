"""Step 2: aggregate observed readings into approximately 10 m square cells.

Run with .venv/Scripts/python.exe scripts/02_grid_binning.py.
All routes/sessions contribute to the mean; networks are always kept separate.
Empty cells are omitted, with no interpolation or synthetic observations.
"""

import json
import os
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Keep matplotlib's writable cache inside this project rather than the user home.
os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "iitg-deadzone-matplotlib"))

import matplotlib
matplotlib.use("Agg")  # Save plots without opening a desktop window.
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


CELL_SIZE_M = 10.0


def bin_readings(readings):
    """Use a local WGS84 approximation, adequate for this small campus extent."""
    if readings.empty:
        raise ValueError("No readings to bin")
    if not np.isfinite(readings[["lat", "lon", "signal_strength_dbm"]]).all().all():
        raise ValueError("Input contains invalid coordinates or signal values")
    if not readings["network_type"].isin(["wifi", "cellular"]).all():
        raise ValueError("Unexpected network_type")

    lat_origin = float(readings["lat"].min())
    lon_origin = float(readings["lon"].min())
    lat_reference = float((readings["lat"].min() + readings["lat"].max()) / 2)
    phi = np.deg2rad(lat_reference)
    # WGS84 ellipsoid radii convert small latitude/longitude offsets to metres.
    a = 6378137.0
    eccentricity_squared = 6.69437999014e-3
    denominator = 1 - eccentricity_squared * np.sin(phi) ** 2
    meridian_radius = a * (1 - eccentricity_squared) / denominator ** 1.5
    prime_radius = a / np.sqrt(denominator)
    metres_per_lat_degree = float(np.pi / 180 * meridian_radius)
    metres_per_lon_degree = float(np.pi / 180 * prime_radius * np.cos(phi))

    east = (readings["lon"] - lon_origin) * metres_per_lon_degree
    north = (readings["lat"] - lat_origin) * metres_per_lat_degree
    indexed = readings.assign(
        grid_x=np.floor(east / CELL_SIZE_M).astype("int64"),
        grid_y=np.floor(north / CELL_SIZE_M).astype("int64"),
    )
    # The network key prevents averaging WiFi and cellular readings together.
    grouped = indexed.groupby(["grid_y", "grid_x", "network_type"], sort=True).agg(
        mean_signal_dbm=("signal_strength_dbm", "mean"),
        reading_count=("signal_strength_dbm", "size"),
    ).reset_index()
    # Export cell centres, not the mean GPS position of their observed readings.
    grouped["cell_lat"] = lat_origin + (grouped["grid_y"] + 0.5) * CELL_SIZE_M / metres_per_lat_degree
    grouped["cell_lon"] = lon_origin + (grouped["grid_x"] + 0.5) * CELL_SIZE_M / metres_per_lon_degree
    result = grouped[["cell_lat", "cell_lon", "network_type", "mean_signal_dbm", "reading_count"]]
    metadata = {
        "cell_size_m": CELL_SIZE_M,
        "origin_lat": lat_origin,
        "origin_lon": lon_origin,
        "reference_lat": lat_reference,
        "metres_per_lat_degree": metres_per_lat_degree,
        "metres_per_lon_degree": metres_per_lon_degree,
        "columns": int(indexed["grid_x"].max() + 1),
        "rows": int(indexed["grid_y"].max() + 1),
        "projection": "Local WGS84 linear approximation at reference latitude",
        "aggregation": "Mean of all observed readings per cell and network across routes/sessions",
        "empty_cells": "Omitted; not assigned zero or interpolated",
    }
    return result, metadata


def plot_cells(cells, metadata, plot_path):
    fig, axes = plt.subplots(2, 1, figsize=(12, 11), layout="constrained")
    for ax, network, title in zip(axes, ["wifi", "cellular"], ["Campus WiFi", "Jio cellular"]):
        part = cells.loc[cells["network_type"].eq(network)]
        east = (part["cell_lon"] - metadata["origin_lon"]) * metadata["metres_per_lon_degree"]
        north = (part["cell_lat"] - metadata["origin_lat"]) * metadata["metres_per_lat_degree"]
        scatter = ax.scatter(east, north, c=part["mean_signal_dbm"], cmap="viridis", s=16, marker="s", linewidths=0)
        fig.colorbar(scatter, ax=ax, label="Mean signal (dBm); higher = stronger", shrink=0.85)
        ax.set_title(f"{title} | {len(part):,} occupied cells | {part['reading_count'].sum():,} readings")
        ax.set(xlabel="East of grid origin (m)", ylabel="North of grid origin (m)",
               xlim=(0, metadata["columns"] * CELL_SIZE_M), ylim=(0, metadata["rows"] * CELL_SIZE_M))
        ax.set_aspect("equal")
        ax.grid(alpha=0.15)
        ax.set_axisbelow(True)
    fig.suptitle("Observed coverage in 10 m cells\nSeparate colour scales; blank areas have no readings; no interpolation", fontsize=14)
    fig.savefig(plot_path, dpi=180)
    plt.close(fig)


def main():
    readings = pd.read_parquet(ROOT / "data/processed/merged_readings.parquet")
    cells, metadata = bin_readings(readings)
    processed = ROOT / "data/processed"
    plots = ROOT / "outputs/plots"
    plots.mkdir(parents=True, exist_ok=True)
    cells.to_parquet(processed / "gridded_readings.parquet", index=False)
    (processed / "grid_metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    plot_path = plots / "grid_coverage.png"
    plot_cells(cells, metadata, plot_path)

    summary = cells.groupby("network_type").agg(
        occupied_cells=("reading_count", "size"),
        readings=("reading_count", "sum"),
        min_readings_per_cell=("reading_count", "min"),
        median_readings_per_cell=("reading_count", "median"),
        max_readings_per_cell=("reading_count", "max"),
        weakest_cell_dbm=("mean_signal_dbm", "min"),
        strongest_cell_dbm=("mean_signal_dbm", "max"),
    )
    both = int(cells.groupby(["cell_lat", "cell_lon"])["network_type"].nunique().eq(2).sum())
    report = "\n".join([
        f"Grid: {metadata['columns']} columns x {metadata['rows']} rows, {CELL_SIZE_M:g} m cells",
        f"Grid origin (southwest): {metadata['origin_lat']:.8f}, {metadata['origin_lon']:.8f}",
        "Empty cells omitted; routes/sessions pooled; networks kept separate.",
        summary.to_string(float_format=lambda value: f"{value:.2f}"),
        f"Cells containing both networks: {both}",
        f"Output rows (cell/network pairs): {len(cells)}",
        "", "First 10 output rows:", cells.head(10).to_string(index=False),
        "", f"Plot: {plot_path.relative_to(ROOT)}",
    ])
    print(report)


if __name__ == "__main__":
    main()
