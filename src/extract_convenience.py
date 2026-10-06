"""Extract convenience stores from the exact SEMAS source CSV (G20405)."""
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def main():
    source = ROOT / 'data/raw/seoul_stores_202606.csv'
    output = ROOT / 'data/raw/seoul_convenience_202606.json'
    with source.open(encoding='utf-8-sig', newline='') as f:
        rows = [r for r in csv.DictReader(f) if r['상권업종소분류코드'] == 'G20405']
    if not rows:
        raise ValueError('편의점 코드 G20405에 해당하는 기록이 없습니다.')
    output.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Convenience records: {len(rows)}')

if __name__ == '__main__':
    main()
