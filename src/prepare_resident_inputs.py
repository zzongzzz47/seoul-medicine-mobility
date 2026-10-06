"""Import SGIS downloads; retain released counts and original spatial units.

The 100m grids represent total resident population. Older residents are kept
at their own census-area representative points, never uniformly allocated to
100m grids. Missing census values remain missing, including suppressed counts.
"""
import argparse, hashlib, json, unicodedata, zipfile
from pathlib import Path
import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
from pyproj import CRS, Transformer

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data/processed/residents'
ANALYSIS_CRS=CRS.from_epsg(5179)
STUDIES={
 'bongcheon':{'district_prefix':'11210','names':['보라매동','청림동','성현동','행운동','낙성대동','청룡동','은천동','중앙동','인헌동']},
 'changsin_sungin':{'district_prefix':'11010','names':['창신1동','창신2동','창신3동','숭인1동','숭인2동']},
}

def unpack(path, folder):
    folder.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(path) as z:
        if z.testzip() is not None: raise ValueError(f'Corrupt archive: {path.name}')
        for info in z.infolist():
            name=info.filename
            if not info.flag_bits&0x800:
                try: name=name.encode('cp437').decode('cp949')
                except UnicodeError: pass
            name=unicodedata.normalize('NFC',name)
            destination=folder/name
            if not destination.resolve().is_relative_to(folder.resolve()): raise ValueError('Unsafe archive path')
            if info.is_dir(): destination.mkdir(parents=True,exist_ok=True);continue
            destination.parent.mkdir(parents=True,exist_ok=True)
            if not destination.exists(): destination.write_bytes(z.read(info))
    for nested in list(folder.rglob('*.zip')):
        unpack(nested,nested.with_suffix(''))

def read_table(path):
    for encoding in ('utf-8-sig','cp949'):
        try:
            data=pd.read_csv(path,header=None,names=['year','id','code','value'],dtype=str,encoding=encoding)
            break
        except UnicodeDecodeError: pass
    else: raise ValueError(f'Unknown table encoding: {path}')
    data['value']=pd.to_numeric(data['value'],errors='coerce')
    return data

def read_projected(path, bounds=None):
    """Read a layer in EPSG:5179; bounds, when supplied, are also EPSG:5179.

    A bounding-box tuple must use the source layer's CRS when passed to
    Pyogrio. Convert that filter first, then reproject the returned geometry.
    Never relabel source coordinates with set_crs(..., allow_override=True).
    """
    source_crs=pyogrio.read_info(path).get('crs')
    if not source_crs:
        raise ValueError(f'{Path(path).name}: 원본 좌표계 정보가 없습니다. 함께 제공된 .prj 파일을 확인하세요.')
    source_crs=CRS.from_user_input(source_crs)
    options={'engine':'pyogrio'}
    if bounds is not None:
        options['bbox']=Transformer.from_crs(
            ANALYSIS_CRS,source_crs,always_xy=True
        ).transform_bounds(*bounds,densify_pts=21)
    frame=gpd.read_file(path,**options)
    if frame.crs is None:
        raise ValueError(f'{Path(path).name}: 읽은 도형의 좌표계가 없습니다.')
    return frame.to_crs(ANALYSIS_CRS)

def points_json(frame, count_column, prefix, source_kind):
    points=frame.copy()
    points.geometry=points.geometry.representative_point() if source_kind=='census' else points.geometry.centroid
    ll=points.to_crs(4326)
    rows=[]
    for (_,row),p in zip(points.iterrows(),ll.geometry):
        value=row[count_column]
        record=dict(id=prefix+str(row['id']),source_id=str(row['id']),lon=float(p.x),lat=float(p.y),
                         population=None if pd.isna(value) else float(value),adm_cd=str(row['adm_cd']),
                         dong=row['ADM_NM'],source_kind=source_kind,reference_year=2024)
        if source_kind=='census':
            record.update(population_lower=float(row['elderly_lower']),population_upper=float(row['elderly_upper']),
                          known_age_bins=int(row['known_age_bins']),weight_basis='연령구간·총인구에서 산출한 65세 이상 인구 하한')
        rows.append(record)
    return rows

def main(input_paths):
    (ROOT/'results').mkdir(parents=True,exist_ok=True)
    OUT.mkdir(parents=True,exist_ok=True); cache=ROOT/'.cache/sgis_seoul';cache.mkdir(parents=True,exist_ok=True)
    manifest=[]
    for path in input_paths:
        path=path.resolve()
        if not path.is_file(): raise FileNotFoundError(path)
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        unpack(path,cache/path.stem)
        manifest.append({'file':path.name,'sha256':digest})
    shapes=list(cache.rglob('*.shp'))
    admin_path=next((p for p in shapes if p.stem.startswith('bnd_dong_11_')),None)
    census_path=next((p for p in shapes if p.stem.startswith('bnd_oa_11_')),None)
    grid_paths=[p for p in shapes if p.stem.upper().endswith('_100M')]
    if not admin_path or not grid_paths: raise ValueError('서울 읍면동 경계와 100M 격자 경계가 필요합니다.')
    admins=read_projected(admin_path)
    admins['ADM_CD']=admins['ADM_CD'].astype(str)
    tables=[]
    for p in cache.rglob('*.csv'):
        if '인구' in p.name or p.name.startswith('in_') or p.name.startswith('to_in'):
            tables.append((p.name,read_table(p)))
    grid_total=pd.concat([t for name,t in tables if '_100M' in name.upper()],ignore_index=True)
    grid_total=grid_total.loc[grid_total.code=='to_in_001',['id','value']].drop_duplicates()
    if grid_total.id.duplicated().any(): raise ValueError('Conflicting population counts for one grid.')
    census_tables=[t for name,t in tables if '_100M' not in name.upper() and '_500M' not in name.upper() and '_1K' not in name.upper()]
    ct=pd.concat(census_tables,ignore_index=True).drop_duplicates() if census_tables else None
    audit={'statistics_year':2024,'boundary_year':2025,'inputs':manifest,'areas':{}}
    for area,config in STUDIES.items():
        adm=admins.loc[admins.ADM_CD.str.startswith(config['district_prefix']) & admins.ADM_NM.isin(config['names'])].copy()
        if len(adm)!=len(config['names']): raise ValueError(f'{area}: requested administrative boundaries not matched: {adm.ADM_NM.tolist()}')
        polygon=adm.geometry.union_all()
        grid_parts=[read_projected(p,bounds=polygon.bounds) for p in grid_paths]
        grids=gpd.GeoDataFrame(pd.concat(grid_parts,ignore_index=True),geometry='geometry')
        grids=grids.rename(columns={'GRID_CD':'id'}).drop_duplicates('id')
        centers=gpd.GeoDataFrame({'id':grids.id},geometry=grids.centroid,crs=grids.crs)
        mapped=gpd.sjoin(centers,adm[['ADM_CD','ADM_NM','geometry']],predicate='within',how='inner')
        if mapped.id.duplicated().any(): raise ValueError('Grid center belongs to multiple administrative polygons.')
        grids=grids.merge(mapped[['id','ADM_CD','ADM_NM']],on='id').rename(columns={'ADM_CD':'adm_cd'})
        grids=grids.merge(grid_total.rename(columns={'value':'population'}),on='id',how='left')
        residents=points_json(grids,'population','POP_','grid100m')
        (OUT/f'{area}_population.json').write_text(json.dumps(residents,ensure_ascii=False,indent=2,allow_nan=False))
        adm.to_file(OUT/'residents.gpkg',layer=f'{area}_admin',driver='GPKG')
        grids.to_file(OUT/'residents.gpkg',layer=f'{area}_grid100m',driver='GPKG')
        a={'administrative_names':adm.ADM_NM.tolist(),'grid_count':len(grids),
           'grid_known_count':int(grids.population.notna().sum()),'grid_missing_count':int(grids.population.isna().sum()),
           'released_population_sum':float(grids.population.sum()),
           'selection_rule':'100m 격자 중심이 연구 대상 행정동 내부에 있는 격자. 경계 격자의 면적 배분 없음.',
           'disclosure_note':'SGIS 격자 값에는 iLBA 비밀보호 조정이 적용됨. 원래 주민 수의 정밀 관측값으로 해석하지 않음.'}
        if census_path and ct is not None:
            census=read_projected(census_path,bounds=polygon.bounds)
            code_col=next(c for c in census.columns if c.upper() in ('TOT_OA_CD','OA_CD'))
            census=census.rename(columns={code_col:'id'});census['id']=census.id.astype(str)
            # Use the provided eight-character dong key, rather than a MOIS key.
            census['adm_cd']=census['ADM_CD'].astype(str)
            census=census.drop(columns='ADM_CD')
            census=census.merge(adm[['ADM_CD','ADM_NM']].rename(columns={'ADM_CD':'adm_cd'}),on='adm_cd')
            age_codes=[f'in_age_{i:03d}' for i in range(1,22)]
            age_data=ct.loc[ct.code.isin(age_codes),['id','code','value']].drop_duplicates()
            if age_data.duplicated(['id','code']).any(): raise ValueError('Conflicting age rows.')
            age=age_data.pivot(index='id',columns='code',values='value').reindex(index=census.id,columns=age_codes)
            totals=ct.loc[ct.code=='to_in_001',['id','value']].drop_duplicates().set_index('id').value.reindex(census.id)
            old=age[[f'in_age_{i:03d}' for i in range(14,22)]]
            young=age[[f'in_age_{i:03d}' for i in range(1,14)]]
            lower=old.sum(axis=1,min_count=0)
            # Suppressed or omitted cells are integer values from 0 to 4 under
            # SGIS's census-area rule. The total and other age bins tighten bounds.
            lower=np.maximum(lower,totals-(young.sum(axis=1)+young.isna().sum(axis=1)*4))
            upper=np.minimum(old.sum(axis=1)+old.isna().sum(axis=1)*4,totals-young.sum(axis=1))
            if totals.isna().any(): raise ValueError('Missing census total: cannot bound suppressed age cells.')
            if (upper<lower).any(): raise ValueError('Inconsistent total/age counts.')
            census['elderly_lower']=lower.to_numpy();census['elderly_upper']=upper.to_numpy()
            census['elderly']=census['elderly_lower'];census['known_age_bins']=old.notna().sum(axis=1).to_numpy()
            rows=points_json(census,'elderly','AGE_','census')
            (OUT/f'{area}_elderly.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2,allow_nan=False))
            census.to_file(OUT/'residents.gpkg',layer=f'{area}_elderly',driver='GPKG')
            a['elderly']={'census_areas':len(census),'all_eight_age_bins_published':int((census.known_age_bins==8).sum()),
                          'lower_sum':float(census.elderly_lower.sum()),'upper_sum':float(census.elderly_upper.sum()),
                          'uncertainty_rule':'65세 이상 8개 연령구간과 총인구로 하한·상한 계산. 비공개 연령구간은 0~4명.',
                          'location':'집계구 내부 대표점. 고령인구를 100m 격자로 임의 배분하지 않음.'}
        audit['areas'][area]=a
    (ROOT/'results/resident_input_audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2))
    print(json.dumps(audit,ensure_ascii=False,indent=2))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('archives',nargs='+',type=Path)
    main(parser.parse_args().archives)
