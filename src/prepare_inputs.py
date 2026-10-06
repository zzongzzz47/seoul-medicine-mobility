"""Normalize public source records, retaining provenance and candidate flags."""
import json, hashlib, collections, re
from pathlib import Path
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
RAW=ROOT/'data/raw'; OUT=ROOT/'data/processed'
OUT.mkdir(exist_ok=True, parents=True)
(ROOT/'results').mkdir(parents=True,exist_ok=True)
def write(name,obj):
    (OUT/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')
def district(addr):
    m=re.search(r'(\S+구)\s',addr+' ')
    return m.group(1) if m else None

fs=json.loads((RAW/'seoul_smartmap_bins_20261004.json').read_text())['body']['geojsons']['1649132420936']['features']
bins=[]
for f in fs:
    p=f['properties']; lon,lat=f['geometry']['coordinates'][:2]
    addr=p.get('cot_addr_full_new') or p.get('cot_addr_full_old') or ''
    if not (126 < lon < 128 and 37 < lat < 38): continue
    bins.append(dict(id='BIN_'+p['cot_conts_id'],name=p.get('cot_value_01') or p['cot_conts_name'],
                     lon=lon,lat=lat,address=addr,district=district(addr),kind='전용 수거함',
                     category=p.get('sub_cate_name'),source='스마트서울맵',checked_on='2026-10-04',
                     opening_hours=None,medicine_types='공식 안내상 물약 포함',site_operation_verified=False))
write('existing_bins.json',bins)
rawpost=json.loads((RAW/'seoul_postboxes_search_20261004.json').read_text())
postgroups=collections.defaultdict(list)
for r in rawpost: postgroups[r['postId']].append(r)
posts=[]; conflicting=[]
for key,group in postgroups.items():
    coordinate_pairs={(r['postLat'],r['postLon']) for r in group}
    if len(coordinate_pairs)>1: conflicting.append(key)
    r=max(group,key=lambda r:r.get('modDt','')); lon=float(r['postLon']); lat=float(r['postLat'])
    if not (126 < lon < 128 and 37 < lat < 38): continue
    posts.append(dict(id='POST_'+key,name='우체통',lon=lon,lat=lat,address=r['postAddr'],district=district(r['postAddr']),
                      kind='우체통',source='인터넷우체국',checked_on='2026-10-04',source_modified=r.get('modDt'),
                      collection_time=r.get('postServiceTime'),medicine_types='알약·가루약 등; 물약 제외',
                      medicine_acceptance_basis='서울시 우체통 수거 정책',site_operation_verified=False,duplicate_source_rows=len(group)))
write('postboxes.json',posts)

stores=json.loads((RAW/'seoul_convenience_202606.json').read_text())
groups=collections.defaultdict(list)
for r in stores:
    try: lon,lat=float(r['경도']),float(r['위도'])
    except (ValueError,TypeError): continue
    if 126 < lon < 128 and 37 < lat < 38: groups[(lon,lat)].append(r)
candidates=[]
for (lon,lat),group in groups.items():
    names=sorted({(r['상호명']+' '+r['지점명']).strip() for r in group})
    addr=group[0]['도로명주소']; text=' '.join(names+[r['건물명'] for r in group])
    flags=[]
    if len(group)>1: flags.append('동일 좌표 복수 기록')
    if re.search('노브랜드|더프레시|THE FRESH',text,re.I): flags.append('슈퍼마켓 가능성')
    if re.search('병원|의료원|대학교|캠퍼스|부대|군부대|역내|구내',text): flags.append('시설 내부 출입 확인')
    if any(r['층정보'] and r['층정보'] not in ('1','1층') for r in group): flags.append('층 정보 확인')
    if any(r['표준산업분류코드']!='G47122' for r in group): flags.append('업종 코드 교차 확인')
    candidates.append(dict(id='CVS_'+hashlib.sha256('|'.join(sorted(r['상가업소번호'] for r in group)).encode()).hexdigest()[:12],
                           name=' / '.join(names),names=names,lon=lon,lat=lat,address=addr,district=group[0]['시군구명'],
                           dong=group[0]['행정동명'],legal_dong=group[0]['법정동명'],raw_rows=len(group),
                           source_ids=[r['상가업소번호'] for r in group],flags=flags,source_date='2026-06-30',
                           participation_verified=False,opening_hours=None))
write('convenience_candidates.json',candidates)
bus=pd.read_excel(RAW/'seoul_bus_20260902.xlsx',dtype={'NODE_ID':str,'ARS_ID':str})
busrows=[]
for _,r in bus.iterrows():
    busrows.append(dict(id=r['NODE_ID'],ars_id=str(r['ARS_ID']).zfill(5),name=r['정류소명'],lon=float(r['X좌표']),lat=float(r['Y좌표']),kind=r['정류소타입']))
write('bus_stops.json',busrows)

districts=[]
for gu in ['관악구','종로구']:
    cc=[r for r in candidates if r['district']==gu]
    districts.append(dict(district=gu,convenience_raw=sum(r['시군구명']==gu for r in stores),convenience_locations=len(cc),
                          candidates_with_flags=sum(bool(r['flags']) for r in cc),dedicated_bins=sum(r['district']==gu for r in bins),
                          postboxes=sum(r['district']==gu for r in posts)))
audit=dict(checked_on='2026-10-04',districts=districts,seoul_convenience_records=len(stores),seoul_convenience_locations=len(candidates),
           smartmap_feature_count=len(fs),smartmap_valid_coordinate_count=len(bins),postbox_raw_count=len(rawpost),postbox_unique_ids=len(postgroups),
           postbox_coordinate_conflicts=conflicting,bus_records=len(busrows),
           caveats=['수거함과 우체통은 기관별 원천 명부이며 실제 수거 여부는 개별 확인 전.',
                    '전용 수거함 명부의 구별 건수는 주소에서 구를 확인할 수 있는 기록 기준.',
                    '편의점 위치는 업종 분류 기반 후보. 중복 좌표 정리 후 출입·업종 확인 대상 표시.',
                    '우체통 주소 검색은 서울/서울특별시 표기에 따라 일부 기록만 반환. 서울 전체 응답에서 구명을 추출함.',
                    '이 감사는 시설 정제 단계이며 주민 인구 연결은 prepare_resident_inputs.py에서 수행.'])
(ROOT/'results/data_audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2))

sources=[
    ('seoul_stores_202606.csv','소상공인시장진흥공단 상가정보','https://www.data.go.kr/data/15083033/fileData.do','2026-06-30','2026-09-28에 확보한 전국 원본 ZIP에서 서울 추출'),
    ('seoul_smartmap_bins_20261004.json','스마트서울맵 폐의약품 전용수거함','https://map.seoul.go.kr/smgis2/','2026-10-04 조회','공개 지도 테마 1649132420936 getContentAll 응답'),
    ('seoul_postboxes_search_20261004.json','인터넷우체국 우체통 검색','https://m.epost.go.kr/mobile/postFind/postMapSearch.jsp','2026-10-04 조회','공개 지역 검색 서울 전체 응답. 동일 postId 중복 제거'),
    ('seoul_bus_20260902.xlsx','서울시 버스정류소 위치정보','https://data.seoul.go.kr/dataList/OA-15067/S/1/datasetView.do','2026-09-02','X/Y 값으로 WGS84 경위도 확인; ARS ID 다섯 자리 문자열 처리'),
]
manifest=[]
for file,name,url,date,note in sources:
    path=RAW/file
    manifest.append(dict(name=name,path=str(path.relative_to(ROOT)),source_url=url,reference_date=date,note=note,sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
for path in RAW.glob('*osm_20261004.metadata.json'):
    manifest.append(json.loads(path.read_text()))
write('source_manifest.json',manifest)
print(json.dumps(audit,ensure_ascii=False,indent=2))
