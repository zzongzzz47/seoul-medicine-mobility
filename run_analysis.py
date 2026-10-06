"""Prepare authorized inputs, check them, and run the report analysis."""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROCESSED = [
    'data/processed/existing_bins.json', 'data/processed/postboxes.json',
    'data/processed/convenience_candidates.json', 'data/processed/bus_stops.json',
    'data/processed/source_manifest.json', 'results/resident_input_audit.json',
    'data/processed/residents/residents.gpkg',
] + [f'data/processed/residents/{area}_{kind}.json'
     for area in ('bongcheon', 'changsin_sungin') for kind in ('population', 'elderly')]
RAW = [
    'seoul_stores_202606.csv', 'seoul_smartmap_bins_20261004.json',
    'seoul_postboxes_search_20261004.json', 'seoul_bus_20260902.xlsx',
]
SGIS = ['sgis_seoul_population_2024.zip', 'bnd_dong_11_2025_2Q.zip',
        'bnd_oa_11_2025_2Q.zip', 'grid_다사.zip']

def run(script, *args):
    print(f'Running {script}', flush=True)
    subprocess.run([sys.executable, str(ROOT / 'src' / script), *map(str, args)],
                   cwd=ROOT, check=True)

def require(paths):
    missing = [p for p in paths if not (ROOT / p).is_file()]
    if missing:
        print('필요한 입력 파일이 없습니다. docs/DATA.md를 확인하세요.')
        for p in missing:
            print('  ' + str(p))
        return False
    return True

def check():
    required = list(PROCESSED) + ['data/raw/expanded_osm/manifest.json']
    if not require(required):
        return False
    manifest = json.loads((ROOT / 'data/raw/expanded_osm/manifest.json').read_text(encoding='utf-8'))
    return require([r['file'] for r in manifest['files']])

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Check input file presence without analyzing or downloading')
    parser.add_argument('--prepare', action='store_true', help='Prepare source data and SGIS ZIP inputs before analyzing')
    parser.add_argument('--download-network', action='store_true', help='Explicitly download current OSM extracts before analyzing')
    args = parser.parse_args()
    os.environ.setdefault('PYTHONUTF8', '1')
    os.environ.setdefault('MPLCONFIGDIR', str(ROOT / '.cache/matplotlib'))
    if args.check:
        ok = check()
        if ok:
            print('Required input files are present. No analysis or download was performed.')
        return 0 if ok else 2
    (ROOT / 'results').mkdir(exist_ok=True)
    if args.prepare:
        if not require([Path('data/raw') / p for p in RAW + SGIS]):
            return 2
        run('extract_convenience.py')
        run('prepare_inputs.py')
        run('prepare_resident_inputs.py', *[ROOT / 'data/raw' / p for p in SGIS])
    if args.download_network:
        run('fetch_expanded_network.py')
        run('add_network_buffer.py')
    if not check():
        return 2
    for script in ('run_resident_analysis.py', 'run_resident_extensions.py', 'build_resident_report.py'):
        run(script)
    print('Completed. Open results/resident_analysis for results and figures.')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
