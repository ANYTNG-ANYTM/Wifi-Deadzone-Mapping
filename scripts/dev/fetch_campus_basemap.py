"""Fetch one small public OSM vector extract; normal builds use the saved GeoJSON."""

import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
BBOX = [26.179, 91.685, 26.195, 91.708]  # south, west, north, east
QUERY = ('[out:json][timeout:25];way[~"^(highway|building|natural|landuse|leisure|waterway)$"~"."]'
         '(' + ','.join(map(str, BBOX)) + ');out geom;')
URL = 'https://overpass-api.de/api/interpreter?' + urlencode({'data': QUERY})


def convert(payload):
    features = []
    for element in payload['elements']:
        tags = element.get('tags', {})
        coords = [[point['lon'], point['lat']] for point in element.get('geometry', [])]
        if len(coords) < 2:
            continue
        closed = len(coords) >= 4 and coords[0] == coords[-1]
        if 'building' in tags:
            kind = 'building'
        elif tags.get('natural') == 'water' or tags.get('waterway') == 'riverbank':
            kind = 'water'
        elif 'waterway' in tags:
            kind = 'stream'
        elif 'highway' in tags:
            kind = 'path' if tags['highway'] in {'footway', 'path', 'steps', 'cycleway'} else 'road'
        else:
            kind = 'land'
        polygon = closed and kind in {'building', 'water', 'land'}
        features.append({'type': 'Feature', 'id': f"way/{element['id']}",
                         'properties': {'kind': kind, 'name': tags.get('name', ''), 'osm_tags': tags},
                         'geometry': {'type': 'Polygon' if polygon else 'LineString',
                                      'coordinates': [coords] if polygon else coords}})
    order = {'land': 0, 'water': 1, 'stream': 2, 'building': 3, 'road': 4, 'path': 5}
    features.sort(key=lambda feature: order[feature['properties']['kind']])
    return {'type': 'FeatureCollection', 'features': features,
            'source': {'attribution': 'OpenStreetMap contributors',
                       'license': 'ODbL-1.0', 'license_url': 'https://opendatacommons.org/licenses/odbl/1-0/',
                       'url': URL, 'bbox_south_west_north_east': BBOX,
                       'osm_timestamp': payload.get('osm3s', {}).get('timestamp_osm_base'),
                       'purpose': 'Display-only geographic context; never used to fit or classify survey data'}}


def save(payload):
    output = ROOT / 'data/context/campus_basemap.geojson'
    output.parent.mkdir(parents=True, exist_ok=True)
    result = convert(payload)
    output.write_text(json.dumps(result, ensure_ascii=False, separators=(',', ':')) + '\n', encoding='utf-8')
    print(f'Saved {len(result["features"])} OSM features to {output}')


if __name__ == '__main__':
    request = Request(URL, headers={'User-Agent': 'IITG-Campus-Connectivity-Map/1.0 (campus basemap export)'})
    with urlopen(request, timeout=40) as response:
        save(json.load(response))
