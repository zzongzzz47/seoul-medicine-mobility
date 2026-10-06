"""Download small, adjacent read-only OSM extracts with a manifest and caching."""
import datetime, hashlib, json, urllib.request, xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'data/raw/expanded_osm'
OUT.mkdir(parents=True, exist_ok=True)
AREAS = {
    'bongcheon': {'bbox': [126.925, 37.462, 126.980, 37.508], 'tiles': [3, 3]},
    'changsin_sungin': {'bbox': [126.994, 37.565, 127.035, 37.600], 'tiles': [2, 3]},
}

def main():
    manifest = []
    for area, config in AREAS.items():
        west, south, east, north = config['bbox']
        nx, ny = config['tiles']
        for ix in range(nx):
            for iy in range(ny):
                b = [west + (east-west)*ix/nx, south+(north-south)*iy/ny,
                     west+(east-west)*(ix+1)/nx, south+(north-south)*(iy+1)/ny]
                b = [round(v, 7) for v in b]
                path = OUT / f'{area}_{ix}_{iy}.osm'
                url = 'https://api.openstreetmap.org/api/0.6/map?bbox=' + ','.join(map(str,b))
                if not path.exists():
                    request = urllib.request.Request(url, headers={'User-Agent': 'SeoulMobilityResearch/1.0'})
                    with urllib.request.urlopen(request, timeout=50) as response:
                        raw = response.read()
                    root = ET.fromstring(raw)
                    if root.tag != 'osm':
                        raise ValueError(f'Not an OSM document: {path.name}')
                    path.write_bytes(raw)
                else:
                    root = ET.parse(path).getroot()
                rec = {'area':area, 'bbox':b, 'url':url, 'file':str(path.relative_to(ROOT)),
                       'retrieved_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                       'nodes':len(root.findall('node')), 'ways':len(root.findall('way')),
                       'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
                metadata = path.with_suffix('.metadata.json')
                if metadata.exists():
                    rec['retrieved_at'] = json.loads(metadata.read_text())['retrieved_at']
                metadata.write_text(json.dumps(rec,ensure_ascii=False,indent=2))
                manifest.append(rec)
                print(area,ix,iy,rec['nodes'],flush=True)
    (OUT/'manifest.json').write_text(json.dumps({'areas':AREAS,'files':manifest,
       'license':'© OpenStreetMap contributors, ODbL 1.0 https://www.openstreetmap.org/copyright'},ensure_ascii=False,indent=2))

if __name__ == '__main__': main()
