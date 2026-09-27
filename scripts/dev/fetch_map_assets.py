"""Fetch public display libraries only; never send map coordinates or tile requests.

These fixed public URLs contain no project data. Downloads are retained locally
so 05_visualization.py and offline browser checks need no external library requests.
"""

import hashlib
import json
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
DEST = ROOT / "scripts/vendor/map"
ASSETS = {
    "leaflet.js": "https://cdn.jsdelivr.net/npm/leaflet@1.9.3/dist/leaflet.js",
    "leaflet.css": "https://cdn.jsdelivr.net/npm/leaflet@1.9.3/dist/leaflet.css",
    "jquery.min.js": "https://code.jquery.com/jquery-3.7.1.min.js",
    "LEAFLET-LICENSE.txt": "https://cdn.jsdelivr.net/npm/leaflet@1.9.3/LICENSE",
    "JQUERY-LICENSE.txt": "https://cdn.jsdelivr.net/npm/jquery@3.7.1/LICENSE.txt",
}


def main():
    DEST.mkdir(parents=True, exist_ok=True)
    records = {}
    for filename, url in ASSETS.items():
        with urlopen(url, timeout=30) as response:
            content = response.read()
        (DEST / filename).write_bytes(content)
        records[filename] = {"public_url": url, "sha256": hashlib.sha256(content).hexdigest()}
        print(f"Saved public asset {filename}: {len(content):,} bytes", flush=True)
    (DEST / "sources.json").write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
