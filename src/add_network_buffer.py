"""Extend extracts where actual resident routing revealed boundary exclusions."""
import datetime, hashlib, json, urllib.request, xml.etree.ElementTree as ET
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];F=ROOT/'data/raw/expanded_osm'
patches=[('bongcheon','west',[126.911,37.462,126.925,37.508],1,3),
         ('bongcheon','south',[126.911,37.450,126.980,37.462],4,1),
         ('changsin_sungin','south',[126.994,37.552,127.035,37.565],3,1),
         ('bongcheon','east_fine',[126.980,37.450,126.984,37.508],1,4),
         ('bongcheon','south_fine',[126.911,37.447,126.984,37.450],4,1)]
manifest=json.loads((F/'manifest.json').read_text())
for area,label,(w,s,e,n),nx,ny in patches:
    for ix in range(nx):
        for iy in range(ny):
            b=[round(w+(e-w)*ix/nx,7),round(s+(n-s)*iy/ny,7),round(w+(e-w)*(ix+1)/nx,7),round(s+(n-s)*(iy+1)/ny,7)]
            path=F/f'{area}_buffer_{label}_{ix}_{iy}.osm'
            url='https://api.openstreetmap.org/api/0.6/map?bbox='+','.join(map(str,b))
            if not path.exists():
                req=urllib.request.Request(url,headers={'User-Agent':'SeoulMobilityResearch/1.0'})
                with urllib.request.urlopen(req,timeout=50) as resp:raw=resp.read()
                root=ET.fromstring(raw)
                if root.tag!='osm':raise ValueError('Invalid OSM response')
                path.write_bytes(raw)
            else:root=ET.parse(path).getroot()
            rec={'area':area,'bbox':b,'url':url,'file':str(path.relative_to(ROOT)),
                 'retrieved_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
                 'nodes':len(root.findall('node')),'ways':len(root.findall('way')),
                 'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
            mp=path.with_suffix('.metadata.json')
            if mp.exists():rec['retrieved_at']=json.loads(mp.read_text())['retrieved_at']
            mp.write_text(json.dumps(rec,ensure_ascii=False,indent=2))
            manifest['files']=[r for r in manifest['files'] if r['file']!=rec['file']]+[rec]
            print(path.name,rec['nodes'],flush=True)
manifest['areas']['bongcheon']['bbox']=[126.911,37.447,126.984,37.508]
manifest['areas']['changsin_sungin']['bbox']=[126.994,37.552,127.035,37.600]
manifest['buffer_reason']='Initial resident cohorts excluded 9.3% and 1.6% near extraction edges; south/west buffers extended before reporting.'
(F/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
