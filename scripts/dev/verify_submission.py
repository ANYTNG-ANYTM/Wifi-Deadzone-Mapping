"""Rebuild in isolation; verify submitted artifacts without modifying the master report."""

import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
STAGES = ["01_clean_merge.py", "02_grid_binning.py", "03_interpolation.py",
          "04_clustering_ranking.py", "05_visualization.py"]
CHECKS = ["dev/verify_step3.py", "dev/verify_step4.py", "dev/verify_step5.py"]
REMOVED = [
    "data/processed/gridded_readings.csv", "data/processed/gpr_training_cells.csv",
    "data/processed/ranked_dead_zones.csv", "outputs/step1_summary.txt",
    "outputs/step2_summary.txt", "outputs/step3_summary.csv", "outputs/step3_summary.txt",
    "outputs/step3_verification.txt", "outputs/step4_approved_rules.json",
    "outputs/step4_needs_more_data_summary.csv", "outputs/step4_status_counts.csv",
    "outputs/step4_summary.txt", "outputs/step4_verification.txt", "outputs/step5_verification.txt",
]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(root, script):
    print(f"Running {script} ({'submission' if root == ROOT else 'isolated rebuild'})", flush=True)
    subprocess.run([sys.executable, "-B", str(root / "scripts" / script)],
                   cwd=root, check=True)


def check_layout(root):
    for name in REMOVED:
        assert not (root / name).exists(), f"Removed artifact recreated: {name}"
    assert (root / "outputs/ranked_dead_zones.csv").stat().st_nlink == 1, "Judge CSV must not be a hard link"
    pd.testing.assert_frame_equal(
        pd.read_parquet(root / "data/processed/ranked_dead_zones.parquet").replace("", float("nan")),
        pd.read_csv(root / "outputs/ranked_dead_zones.csv"),
        check_dtype=False, check_exact=False, rtol=1e-7, atol=1e-7,
    )


def main():
    report_path = ROOT / "outputs/submission_checks.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    baseline = {Path(name).as_posix(): value for name, value in report["protected_sha256"].items()}
    protected = {p.relative_to(ROOT).as_posix()
                 for p in list((ROOT / "data/raw").rglob("*.csv"))
                 + list((ROOT / "data/processed").glob("*.parquet"))}
    assert protected == set(baseline), "Protected file inventory changed"
    immutable = [report_path, ROOT / "scripts/templates/deadzone_map_ui.html"]
    for folder in ["scripts/vendor/map", "outputs/maps", "outputs/models", "outputs/plots"]:
        immutable.extend(p for p in (ROOT / folder).rglob("*") if p.is_file())
    untouched = {p: digest(p) for p in immutable}
    try:
        for name, expected in baseline.items():
            assert digest(ROOT / name) == expected, f"Protected file changed: {name}"
        check_layout(ROOT)
        with tempfile.TemporaryDirectory(prefix="iitg-submission-") as temporary:
            stage = Path(temporary)
            shutil.copytree(ROOT / "scripts", stage / "scripts",
                            ignore=shutil.ignore_patterns("__pycache__"))
            shutil.copytree(ROOT / "data/raw", stage / "data/raw")
            shutil.copytree(ROOT / "data/context", stage / "data/context")
            for script in STAGES + CHECKS:
                run(stage, script)
            check_layout(stage)
            for path in (ROOT / "data/processed").glob("*.parquet"):
                pd.testing.assert_frame_equal(
                    pd.read_parquet(path),
                    pd.read_parquet(stage / "data/processed" / path.name),
                    check_exact=False, rtol=1e-7, atol=1e-7,
                )
            pd.testing.assert_frame_equal(
                pd.read_csv(ROOT / "outputs/ranked_dead_zones.csv"),
                pd.read_csv(stage / "outputs/ranked_dead_zones.csv"),
                check_exact=False, rtol=1e-7, atol=1e-7,
            )
        for script in CHECKS:
            run(ROOT, script)
        observed = pd.read_parquet(ROOT / "data/processed/merged_readings.parquet")
        assert observed.network_type.value_counts().to_dict() == {"wifi": 2087, "cellular": 994}
        assert observed.data_status.eq("observed").all()
        for target in re.findall(r"\]\(([^)]+)\)", (ROOT / "README.md").read_text(encoding="utf-8")):
            if "://" not in target:
                assert (ROOT / target).exists(), f"Broken README link: {target}"
        check_layout(ROOT)
    finally:
        for name, expected in baseline.items():
            assert (ROOT / name).exists() and digest(ROOT / name) == expected, f"Protected file changed: {name}"
        for path, expected in untouched.items():
            assert path.exists() and digest(path) == expected, f"Immutable artifact changed: {path}"
    print("PASS: isolated full pipeline, submitted artifacts, browser checks, links, protected hashes, and cleaned layout.")
    print("PASS: master verification report, map deliverables, vendor assets, template, models, and PNGs unchanged.")


if __name__ == "__main__":
    main()
