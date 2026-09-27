"""Step 1 only: clean observed exports and merge them using manifest metadata.

Run from the project root with .venv/Scripts/python.exe scripts/01_clean_merge.py.
WiGLE's timezone-free timestamps are interpreted as UTC, as documented in
docs/schema.md. Cellular timestamps are Unix milliseconds (already UTC).
"""

from pathlib import Path
import warnings

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data/raw/manifest.csv"
OUTPUT = ROOT / "data/processed/merged_readings.parquet"
COLUMNS = [
    "timestamp", "lat", "lon", "route_id", "session", "network_type",
    "carrier_or_ssid", "signal_strength_dbm", "latency_ms", "method",
    "data_status", "accuracy_m", "source_file",
]
STRING_COLUMNS = [
    "route_id", "session", "network_type", "carrier_or_ssid", "method",
    "data_status", "source_file",
]
FLOAT_COLUMNS = ["lat", "lon", "signal_strength_dbm", "latency_ms", "accuracy_m"]


def numeric(values):
    """Treat unparseable numeric values as missing, for explicit filtering."""
    return pd.to_numeric(values, errors="coerce").astype("float64")


def clean_file(path, metadata):
    network = metadata["network_type"]
    raw = pd.read_csv(path, skiprows=1 if network == "wifi" else 0)
    stats = {"source_file": path.name, "loaded": len(raw),
             "other_ssid": 0, "accuracy_over_30m": 0, "invalid_values": 0}

    if network == "wifi":
        # Match campus SSIDs exactly after trimming whitespace; preserve case.
        raw["SSID"] = raw["SSID"].astype("string").str.strip()
        keep = raw["SSID"].isin(["IITG_CONNECT", "eduroam"])
        stats["other_ssid"] = int((~keep).sum())
        raw = raw.loc[keep].copy()
        raw["AccuracyMeters"] = numeric(raw["AccuracyMeters"])
        # Only >30 is rejected by the requested rule; missing accuracy stays null.
        bad_accuracy = raw["AccuracyMeters"] > 30
        stats["accuracy_over_30m"] = int(bad_accuracy.sum())
        raw = raw.loc[~bad_accuracy].copy()
        frame = pd.DataFrame({
            "timestamp": pd.to_datetime(raw["FirstSeen"], utc=True, errors="coerce"),
            "lat": numeric(raw["CurrentLatitude"]),
            "lon": numeric(raw["CurrentLongitude"]),
            "carrier_or_ssid": raw["SSID"],
            "signal_strength_dbm": numeric(raw["RSSI"]),
            "accuracy_m": raw["AccuracyMeters"],
        })
    else:
        frame = pd.DataFrame({
            "timestamp": pd.to_datetime(
                pd.to_numeric(raw["measured_at"], errors="coerce"),
                unit="ms", utc=True, errors="coerce",
            ),
            "lat": numeric(raw["lat"]),
            "lon": numeric(raw["lon"]),
            "carrier_or_ssid": "Jio",
            "signal_strength_dbm": numeric(raw["signal"]),
            "accuracy_m": np.nan,
        })

    # Validate geographic bounds and finite values without inventing dBm cutoffs.
    valid = (
        np.isfinite(frame[["lat", "lon", "signal_strength_dbm"]]).all(axis=1)
        & frame["lat"].between(-90, 90)
        & frame["lon"].between(-180, 180)
    )
    stats["invalid_values"] = int((~valid).sum())
    frame = frame.loc[valid].copy()
    if frame["timestamp"].isna().any():
        raise ValueError(f"{path.name}: invalid timestamps in retained rows; inspect export")

    # Metadata comes exclusively from the manifest, never from the filename.
    direction = metadata["direction"].strip()
    frame["route_id"] = metadata["route_id"]
    frame["session"] = metadata["session"] + (f"_{direction}" if direction else "")
    frame["network_type"] = network
    frame["latency_ms"] = np.nan
    frame["method"] = "wardrive_continuous"
    frame["data_status"] = "observed"
    frame["source_file"] = path.name
    frame = frame.reindex(columns=COLUMNS).astype(
        {**dict.fromkeys(STRING_COLUMNS, "string"),
         **dict.fromkeys(FLOAT_COLUMNS, "float64")}
    )
    stats["kept"] = len(frame)
    return frame, stats


def main():
    manifest = pd.read_csv(MANIFEST, dtype="string", keep_default_na=False)
    required = {"filename", "network_type", "route_id", "session", "direction", "notes"}
    if not required.issubset(manifest.columns):
        raise ValueError(f"Manifest missing columns: {sorted(required - set(manifest.columns))}")
    if manifest["filename"].duplicated().any():
        raise ValueError("Duplicate manifest filenames would make metadata ambiguous")
    if not manifest["network_type"].isin(["wifi", "cellular"]).all():
        raise ValueError("Manifest network_type must be wifi or cellular")
    for column in ["filename", "route_id", "session"]:
        if manifest[column].str.strip().eq("").any():
            raise ValueError(f"Manifest contains empty {column}")
    lookup = manifest.set_index("filename")

    frames, audits, seen = [], [], set()
    for network in ["wifi", "cellular"]:
        for path in sorted((ROOT / "data/raw" / network).glob("*.csv")):
            if path.name not in lookup.index:
                warnings.warn(f"Skipping file absent from manifest: {path.name}")
                continue
            metadata = lookup.loc[path.name]
            if metadata["network_type"] != network:
                raise ValueError(f"{path.name}: folder and manifest network_type disagree")
            frame, stats = clean_file(path, metadata)
            frames.append(frame)
            audits.append(stats)
            seen.add(path.name)
    for missing in sorted(set(lookup.index) - seen):
        warnings.warn(f"Manifest file not found in raw folders: {missing}")
    if not frames:
        raise ValueError("No raw files matched the manifest")

    merged = pd.concat(frames, ignore_index=True)
    if merged.empty:
        raise ValueError("No readings survived cleaning")
    audit = pd.DataFrame(audits)
    breakdown = merged.groupby(
        ["route_id", "session", "network_type"], sort=True
    ).size().rename("rows").reset_index()
    report = "\n".join([
        f"Manifest: {MANIFEST.relative_to(ROOT)}",
        "WiGLE timestamps interpreted as UTC per docs/schema.md.",
        f"Files loaded: {len(audits)}",
        f"Total rows loaded: {audit['loaded'].sum():,}",
        f"Dropped non-campus SSIDs: {audit['other_ssid'].sum():,}",
        f"Dropped WiFi accuracy >30 m: {audit['accuracy_over_30m'].sum():,}",
        f"Dropped invalid lat/lon/signal: {audit['invalid_values'].sum():,}",
        f"Rows after cleaning: {len(merged):,}",
        "", "Per-file cleaning (drop categories are sequential):", audit.to_string(index=False),
        "", "Route / session / network breakdown:", breakdown.to_string(index=False),
        "", f"Saved: {OUTPUT.relative_to(ROOT)}",
    ])
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    # Write a temporary sibling first so failed serialization cannot damage the old output.
    temporary = OUTPUT.with_suffix(".tmp.parquet")
    merged.to_parquet(temporary, index=False)
    temporary.replace(OUTPUT)
    print(report)


if __name__ == "__main__":
    main()
