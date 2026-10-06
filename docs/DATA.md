# 데이터 준비

보고서의 입력 기준일과 파일명을 아래에 기록했습니다. 원자료 재배포 여부와 이용 조건은 제공기관 안내를 따릅니다.
SGIS 신청 자료는 신청·승인 후 확보한 원본을 이용합니다. 이 저장소에는 신청자의 계정이나 로그인 정보가 없습니다.

## 제공기관

| 자료 | 기준 시점 | 출처 |
|---|---|---|
| 서울 상가정보 | 2026년 6월 | 소상공인시장진흥공단 · https://www.data.go.kr/data/15083033/fileData.do |
| 폐의약품 전용 수거함 | 2026-10-04 조회 | 스마트서울맵 · https://map.seoul.go.kr/smgis2/ |
| 우체통 위치 | 2026-10-04 조회 | 인터넷우체국 · https://m.epost.go.kr/mobile/postFind/postMapSearch.jsp |
| 서울 버스정류소 | 2026-09-02 | 서울 열린데이터광장 · https://data.seoul.go.kr/dataList/OA-15067/S/1/datasetView.do |
| 100m 인구 격자, 집계구 총인구·연령 | 2024년 | SGIS · https://sgis.mods.go.kr/view/pss/openDataIntrcn |
| 행정동·집계구 경계 | 2025년 2분기 | SGIS · https://sgis.mods.go.kr/view/pss/openDataIntrcn |
| 다사 100m 격자 경계 | 다운로드 원본 | SGIS · https://sgis.mods.go.kr/view/pss/openDataIntrcn |
| 보행 도로망 | 2026-10-04 추출 | OpenStreetMap · https://www.openstreetmap.org/copyright |

## 방법 A: 보관된 정제 자료를 사용하는 경우

프로젝트 루트에 다음 상대경로로 배치합니다.

```text
data/processed/
  existing_bins.json
  postboxes.json
  convenience_candidates.json
  bus_stops.json
  source_manifest.json
  residents/
    bongcheon_population.json
    bongcheon_elderly.json
    changsin_sungin_population.json
    changsin_sungin_elderly.json
    residents.gpkg
data/raw/expanded_osm/
  manifest.json
  (manifest.json에 기록된 모든 .osm 파일)
results/
  resident_input_audit.json
```

`residents.gpkg`에는 각 지역의 `_admin`, `_grid100m`, `_elderly` 레이어가 필요합니다.
원래 분석에 사용한 `data/processed/`, `data/raw/expanded_osm/`, `results/resident_input_audit.json`을
그대로 복사하면 같은 형식을 사용할 수 있습니다. 다운로드 페이지나 로그인 화면 파일은 필요하지 않습니다.

## 방법 B: 원자료에서 정제하는 경우

다음 파일을 `data/raw/`에 준비한 뒤 `python run_analysis.py --prepare`를 실행합니다.

- `seoul_stores_202606.csv`: 서울 상가정보 원본 CSV, UTF-8 BOM 허용.
  `상권업종소분류코드 == G20405` 기록을 추출하며 원래 분석에서는 9,395개입니다.
- `seoul_smartmap_bins_20261004.json`: 스마트서울맵 테마 `1649132420936`의 공개 조회 JSON.
  `body.geojsons.1649132420936.features` 형식과 `cot_conts_id`, `cot_conts_name`,
  `cot_value_01`, `cot_addr_full_new`, `cot_addr_full_old`, `sub_cate_name` 속성 및 좌표를 사용합니다.
- `seoul_postboxes_search_20261004.json`: 인터넷우체국 서울 검색 결과를 배열로 저장한 JSON.
  `postId`, `postLat`, `postLon`, `postAddr`, `modDt`, `postServiceTime` 필드를 사용합니다.
- `seoul_bus_20260902.xlsx`: `NODE_ID`, `ARS_ID`, `정류소명`, `X좌표`, `Y좌표`, `정류소타입` 열을 사용합니다.
- `sgis_seoul_population_2024.zip`: 2024 서울 100m 격자 총인구와 집계구 총인구·연령 통계 ZIP 묶음.
  총인구 코드 `to_in_001`, 집계구 연령 코드 `in_age_001`부터 `in_age_021`을 사용합니다.
- `bnd_dong_11_2025_2Q.zip`: 서울 행정동 경계. `ADM_CD`, `ADM_NM` 열을 사용합니다.
- `bnd_oa_11_2025_2Q.zip`: 서울 집계구 경계. `TOT_OA_CD` 또는 `OA_CD`와 `ADM_CD` 열을 사용합니다.
- `grid_다사.zip`: 파일명이 `_100M`으로 끝나는 다사 100m 격자 경계.

상가정보 외 시설 원자료는 해당 서비스에서 확보한 응답 형식을 전제로 합니다.
공개 화면·응답 형식이나 제공 연도가 바뀌면 열 이름과 정제 코드를 확인해야 합니다.
이 저장소는 로그인이나 비공개 API를 자동 호출하지 않습니다.

OSM 파일이 없을 때 `python run_analysis.py --prepare --download-network`로 현재 도로망을 받을 수 있습니다.
보고서 시점 자료와 동일한지 확인하려면 `reference/input_checksums.json` 및
`reference/osm_manifest.json`의 SHA-256과 비교합니다. 나중에 받은 파일은 내용과 결과가 달라질 수 있습니다.
