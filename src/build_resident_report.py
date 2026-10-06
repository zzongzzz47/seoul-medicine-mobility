"""Validate completed resident models and publish a local, self-contained briefing."""
import html, json, pickle, hashlib
from pathlib import Path
import numpy as np
import geopandas as gpd
from shapely.geometry import Point
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager, colors
from matplotlib.collections import LineCollection
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from mobility_network import ROOT, xy

R=ROOT/'results/resident_analysis'; F=R/'figures'; F.mkdir(parents=True,exist_ok=True)
def read(p): return json.loads(p.read_text())
def dump(p,x): p.write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False))
def mean(v,w): return float(np.average(v,weights=w))
def esc(x): return html.escape(str(x))
from plot_fonts import korean_font
plt.rcParams.update({'font.family':korean_font(),'axes.unicode_minus':False,'font.size':12,
                    'axes.spines.top':False,'axes.spines.right':False,'figure.facecolor':'white'})
LABELS={'bongcheon':'봉천동 일대','changsin_sungin':'창신·숭인동'}
S=read(R/'summary.json'); E=read(R/'extensions.json'); INPUT=read(ROOT/'results/resident_input_audit.json')
C={a:read(R/f'{a}_cost_context.json') for a in LABELS}
A={a:read(R/f'{a}_audit.json') for a in LABELS}
def result(a,med='liquid',trip='roundtrip',k=5):
    return next(s for s in S if (s['area'],s['medicine'],s['trip_type'],s['k'])==(a,med,trip,k))
def extension(a,med='liquid',trip='roundtrip'):
    return next(s for s in E if (s['area'],s['medicine'],s['trip_type'])==(a,med,trip))
def save(fig,name):
    fig.savefig(F/f'{name}.png',dpi=190,bbox_inches='tight',facecolor='white')
    fig.savefig(F/f'{name}.svg',bbox_inches='tight',facecolor='white')
    plt.close(fig)

# Results are independently recomputed from origin records; no reported number is hand-entered.
checks=[]; dongs=[]; cross=[]; coverage=[]; network_scope=[]
all_candidates=read(ROOT/'data/processed/convenience_candidates.json')
for area in LABELS:
    admin=gpd.read_file(ROOT/'data/processed/residents/residents.gpkg',layer=f'{area}_admin')
    bound=admin.to_crs(4326).geometry.union_all()
    ids={r['id'] for r in all_candidates if bound.covers(Point(r['lon'],r['lat'])) and '슈퍼마켓 가능성' not in r['flags']}
    assert ids=={r['id'] for r in C[area]['candidates']}, 'Demand/candidate boundary mismatch'
    network_scope.append({'area':area,'candidate_boundary_matches_demand_admin_union':True,'candidate_count':len(ids)})
    for med in ('solid','liquid'):
        for trip in ('roundtrip','stop_detour'):
            prev=np.inf
            for k in (0,3,5,10,15):
                s=result(area,med,trip,k);rows=read(R/f'{area}_{med}_{trip}_k{k}_origins.json')
                p=[r for r in rows if r['source_kind']=='grid100m'];w=np.array([r['population'] for r in p]);b=np.array([r['baseline_m'] for r in p]);v=np.array([r['after_m'] for r in p])
                assert s['proven_optimal'] and s['mip_gap']<=1.1e-7
                assert np.all(v>=0) and np.all(v<=b+1e-6)
                assert np.isclose(mean(v,w),s['after_mean_m']) and np.isclose(mean(b,w),s['baseline_mean_m'])
                assert s['after_mean_m']<=prev+1e-6;prev=s['after_mean_m']
                if k==5 and trip=='roundtrip':
                    for radius in (200,350,500):
                        coverage.append({'area':area,'medicine':med,'walking_oneway_threshold_m':radius,
                            'before_pct':float(w[b<=2*radius].sum()/w.sum()*100),'after_pct':float(w[v<=2*radius].sum()/w.sum()*100)})
                    if med=='liquid':
                        for dong in sorted({r['dong'] for r in p}):
                            z=[r for r in p if r['dong']==dong];ww=[r['population'] for r in z]
                            dongs.append({'area':area,'dong':dong,'population':sum(ww),
                                          'before_m':mean([r['baseline_m'] for r in z],ww),'after_m':mean([r['after_m'] for r in z],ww)})
                checks.append({'area':area,'medicine':med,'trip':trip,'k':k,'passed':True})
    context=C[area];data=np.load(R/context['cost_cache']);M=len(context['existing'])
    stop_idx={b:i for i,b in enumerate(context['target_stops'])};idx_by_id={r['id']:i for i,r in enumerate(context['demand'])}
    for med in ('solid','liquid'):
        cohort=read(R/f'{area}_{med}_stop_detour_k5_origins.json')
        pop=[r for r in cohort if r['source_kind']=='grid100m'];idx=[idx_by_id[r['id']] for r in pop]
        c=np.array([data['to_sites'][i,M:]+data['site_to_stop'][stop_idx[context['nearest_stop'][i]],M:]-context['stop_distance'][i] for i in idx])
        c=np.maximum(c,0);base=np.array([r['baseline_m'] for r in pop]);w=np.array([r['population'] for r in pop])
        round_sel=result(area,med)['selected_indices'];chain_sel=result(area,med,'stop_detour')['selected_indices']
        same=mean(np.minimum(base,c[:,round_sel].min(axis=1)),w)
        cross.append({'area':area,'medicine':med,'before_detour_m':mean(base,w),'roundtrip_selected_detour_m':same,
                      'detour_selected_detour_m':result(area,med,'stop_detour')['after_mean_m'],
                      'common_selected_stores':len(set(round_sel)&set(chain_sel))})
dump(R/'validation.json',{'models_checked':len(checks),'all_passed':True,'scope':network_scope,'checks':checks})
dump(R/'interpretation_metrics.json',{'districts':dongs,'same_store_cross_evaluation':cross,'walking_coverage':coverage})

# Maps: same scale and same resident cohort in the before/after panels.
for area,label in LABELS.items():
    admin=gpd.read_file(ROOT/'data/processed/residents/residents.gpkg',layer=f'{area}_admin')
    grid=gpd.read_file(ROOT/'data/processed/residents/residents.gpkg',layer=f'{area}_grid100m')
    rows=read(R/f'{area}_liquid_roundtrip_k5_origins.json');lookup={r['source_id']:r for r in rows if r['source_kind']=='grid100m'}
    grid['before']=grid['id'].map(lambda s:lookup[s]['baseline_m'] if s in lookup else np.nan)
    grid['after']=grid['id'].map(lambda s:lookup[s]['after_m'] if s in lookup else np.nan)
    with (R/f'{area}_network.pkl').open('rb') as f: net=pickle.load(f)
    roads=[np.asarray(s[2].coords) for s in net.segments]
    positive=grid[grid.population>0];bounds=positive.total_bounds;pad=130
    norm=colors.Normalize(0,2000,clip=True);cmap=plt.get_cmap('YlOrRd')
    fig,axes=plt.subplots(1,2,figsize=(13.5,7.0))
    fig.subplots_adjust(left=.01,right=.9,bottom=.16,top=.93,wspace=.05)
    selected=result(area)['selected_sites']
    for ax,col,title in zip(axes,['before','after'],['기존 수거망','편의점 5곳 추가']):
        admin.plot(ax=ax,color='#f7f7f5',edgecolor='#b6c1c6',linewidth=.6,zorder=0)
        ax.add_collection(LineCollection(roads,colors='#ced7dc',linewidths=.27,zorder=1))
        grid[grid.population.isna()].plot(ax=ax,color='#e6e8ea',edgecolor='none',zorder=2)
        grid[grid[col].notna()].plot(ax=ax,column=col,cmap=cmap,norm=norm,edgecolor='white',linewidth=.18,zorder=3)
        excluded=grid[(grid.population>0)&grid[col].isna()]
        if len(excluded): excluded.plot(ax=ax,facecolor='none',edgecolor='#626f78',hatch='///',linewidth=.8,zorder=4)
        bins=[r for r in C[area]['existing'] if r['kind']=='전용 수거함'];X=np.array([xy(r) for r in bins])
        ax.scatter(X[:,0],X[:,1],s=26,marker='s',c='#174b68',edgecolors='white',linewidth=.65,zorder=6)
        if col=='after':
            for n,r in enumerate(selected,1):
                x,y=xy(r);ax.scatter(x,y,s=250,c='#ffffff',edgecolors='#006a64',linewidths=2,zorder=8)
                ax.text(x,y,str(n),ha='center',va='center',color='#006a64',fontsize=11,fontweight='bold',zorder=9)
        for _,r in admin.iterrows():
            p=r.geometry.representative_point()
            if bounds[0]<p.x<bounds[2] and bounds[1]<p.y<bounds[3]:
                ax.text(p.x,p.y,r.ADM_NM,fontsize=8,color='#233e4a',ha='center',zorder=5,bbox=dict(facecolor='white',edgecolor='none',alpha=.65,pad=.5))
        ax.set_xlim(bounds[0]-pad,bounds[2]+pad);ax.set_ylim(bounds[1]-pad,bounds[3]+pad);ax.set_aspect('equal');ax.axis('off');ax.set_title(title,fontsize=16,pad=12)
        length=500 if area=='bongcheon' else 250
        sx=bounds[0]+10;sy=bounds[1]-70;ax.plot([sx,sx+length],[sy,sy],color='#294652',lw=2);ax.text(sx+length/2,sy+30,f'{length} m',ha='center',fontsize=9)
    color_axis=fig.add_axes([.92,.23,.016,.58])
    cb=fig.colorbar(plt.cm.ScalarMappable(norm=norm,cmap=cmap),cax=color_axis,extend='max')
    cb.set_label('물약류 배출 왕복 보행거리 (m)',labelpad=10)
    fig.legend(handles=[Line2D([0],[0],ls='',marker='s',color='#174b68',label='기존 전용 수거함'),
                        Line2D([0],[0],ls='',marker='o',mfc='white',mec='#006a64',label='선정 편의점 (번호는 표와 연결)'),
                        Patch(facecolor='#e6e8ea',label='인구 미공개 격자'),
                        Patch(facecolor='white',edgecolor='#626f78',hatch='///',label='경로 연결이 없어 비교에서 제외')],loc='lower center',bbox_to_anchor=(.5,.055),ncol=2,fontsize=10,frameon=False)
    fig.text(.5,.022,'자료: SGIS(2024 인구·2025 경계), 스마트서울맵, 소상공인시장진흥공단, © OpenStreetMap contributors / ODbL',ha='center',fontsize=9,color='#61727b')
    save(fig,f'01_{area}_왕복거리_전후지도')

# Number of sites, travel situations, and elderly tradeoff.
fig,axes=plt.subplots(1,2,figsize=(12,4.8),layout='constrained')
for ax,(a,l) in zip(axes,LABELS.items()):
    for med,c,t in [('liquid','#c05130','물약류'),('solid','#218681','알약류')]:
        rr=[result(a,med,k=k) for k in (0,3,5,10,15)];ax.plot([r['k'] for r in rr],[r['after_mean_m'] for r in rr],'-o',color=c,label=t,lw=2.5)
        for r in rr: ax.annotate(f"{r['after_mean_m']:.0f}",(r['k'],r['after_mean_m']),xytext=(0,9 if med=='liquid' else -18),textcoords='offset points',ha='center',fontsize=10,color=c)
    ax.set_title(l);ax.set_xlabel('추가 편의점 수 (곳)');ax.set_ylabel('인구 가중 평균 왕복거리 (m)');ax.set_xticks([0,3,5,10,15]);ax.grid(axis='y',alpha=.18);ax.legend(frameon=False);ax.set_ylim(0,1250)
save(fig,'02_도입규모와_왕복거리')

fig,axes=plt.subplots(1,2,figsize=(12,4.5),layout='constrained')
for ax,(a,l) in zip(axes,LABELS.items()):
    r=next(r for r in cross if r['area']==a and r['medicine']=='liquid')
    vals=[r['before_detour_m'],r['roundtrip_selected_detour_m'],r['detour_selected_detour_m']]
    bars=ax.bar(['기존망','왕복거리로 선정한\n같은 5곳','경유거리로\n다시 선정한 5곳'],vals,color=['#97a8b4','#268781','#316bac'],width=.62)
    ax.bar_label(bars,fmt='%.0f m',padding=5);ax.set_title(l);ax.set_ylabel('정류소 경유 추가거리 (m)');ax.set_ylim(0,1000);ax.grid(axis='y',alpha=.15);ax.set_axisbelow(True)
save(fig,'03_같은점포의_정류소경유효과')

fig,axes=plt.subplots(1,2,figsize=(12,4.8),layout='constrained')
for ax,(a,l) in zip(axes,LABELS.items()):
    e=extension(a);rr=e['fairness'];xx=[e['population_efficient_m']]+[r['population_mean_m'] for r in rr[:2]];yy=[e['elderly_efficient_lower_m']]+[r['elderly_lower_weighted_mean_m'] for r in rr[:2]]
    ax.scatter(xx,yy,s=[120,85,110],color=['#266882','#b8b8b8','#148579'],zorder=3)
    for x,y,t,offset in zip(xx,yy,['전체 거리 우선','효과 90% 유지','효과 95% 유지'],[(6,7),(8,-32),(6,9)]):
        ax.annotate(f'{t}\n({x:.0f}, {y:.0f})',(x,y),xytext=offset,textcoords='offset points',fontsize=10)
    ax.set_title(l);ax.set_xlabel('전체 인구 평균 왕복거리 (m)');ax.set_ylabel('65세 이상 평균 왕복거리 (m)');ax.grid(alpha=.2)
    ax.set_xlim(min(xx)-10,max(xx)+43);ax.set_ylim(min(yy)-13,max(yy)+20)
fig.text(.5,-.035,'물약류 · 5곳 추가 · 전체 인구는 100m 격자, 고령인구는 집계구의 연령별 인구 하한 가중치. 자료: 본 연구 계산.',ha='center',fontsize=9,color='#61727b')
save(fig,'04_전체효과와_고령층개선')

fig,axes=plt.subplots(1,2,figsize=(12,5.5),layout='constrained')
for ax,(a,l) in zip(axes,LABELS.items()):
    rr=sorted([r for r in dongs if r['area']==a],key=lambda r:r['before_m']-r['after_m'])
    for y,r in enumerate(rr):
        ax.plot([r['after_m'],r['before_m']],[y,y],color='#becdd4',lw=4)
        ax.scatter(r['before_m'],y,color='#98a9b3',s=55,zorder=3);ax.scatter(r['after_m'],y,color='#218681',s=55,zorder=3)
    ax.set_yticks(range(len(rr)),[r['dong'] for r in rr]);ax.set_title(l);ax.set_xlabel('동별 인구 가중 평균 왕복거리 (m)');ax.grid(axis='x',alpha=.15);ax.set_xlim(0,1900)
fig.legend(handles=[Line2D([0],[0],ls='',marker='o',color='#98a9b3',label='기존망'),Line2D([0],[0],ls='',marker='o',color='#218681',label='5곳 추가')],loc='outside lower center',ncol=2,frameon=False)
save(fig,'05_동별_개선효과')

def img(name,alt): return f'<figure><a href="figures/{name}.png" target="_blank"><img src="figures/{name}.png" alt="{esc(alt)}"></a><figcaption><a href="figures/{name}.png" download>PNG 저장</a> · <a href="figures/{name}.svg" download>SVG 저장</a></figcaption></figure>'
def table(headers,rows):return '<div class="scroll"><table><thead><tr>'+''.join(f'<th>{esc(h)}</th>' for h in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join(f'<td>{v}</td>' for v in row)+'</tr>' for row in rows)+'</tbody></table></div>'
headline_rows=[];cards=[]
for a,l in LABELS.items():
    s=result(a);cards.append(f'<div class="card"><span>{l} · 물약류 왕복</span><strong>{s["baseline_mean_m"]:.0f} → {s["after_mean_m"]:.0f} m</strong><em>5곳 추가로 {s["reduction_pct"]:.1f}% 감소</em></div>')
    for med,t in [('solid','알약류'),('liquid','물약류')]:
        s=result(a,med);headline_rows.append([l,t,f'{s["baseline_mean_m"]:.0f} m',f'{s["after_mean_m"]:.0f} m',f'{s["reduction_pct"]:.1f}%',f'{s["baseline_p90_m"]:.0f} → {s["after_p90_m"]:.0f} m'])
maps=''.join(f'<h3>{l}</h3>'+img(f'01_{a}_왕복거리_전후지도',f'{l} 물약류 왕복거리 전후 비교') for a,l in LABELS.items())
sites=''
for a,l in LABELS.items():
    s=result(a);sites+=f'<h3>{l}</h3>'+table(['지도 번호','선정 후보','행정동','주소','자료 확인 항목'],[[str(i),esc(r['name']),esc(r['dong']),esc(r['address']),esc(' · '.join(r['flags']) or '별도 표시 없음')] for i,r in enumerate(s['selected_sites'],1)])
fair_rows=[];fair_notes=[];risk_rows=[]
for a,l in LABELS.items():
    e=extension(a);f=e['fairness'][1];delta=e['elderly_efficient_lower_m']-f['elderly_lower_weighted_mean_m']
    fair_rows.append([l,f'{e["population_efficient_m"]:.0f} → {f["population_mean_m"]:.0f} m',f'{e["elderly_efficient_lower_m"]:.0f} → {f["elderly_lower_weighted_mean_m"]:.0f} m',f'{5-f["overlap_with_efficiency"]}곳 교체'])
    overlap=len(set(f['selected_indices'])&set(e['elderly_upper_95_selected']))
    fair_notes.append(f'{l}은 고령인구 하한·상한 가중치를 바꿨을 때 5곳 중 {overlap}곳이 같았습니다.')
    worst=max(e['dropout_replacements'],key=lambda r:r['dropout_mean_m']);cs=C[a]['candidates']
    risk_rows.append([l,esc(cs[worst['dropped_index']]['name']),f'{e["population_efficient_m"]:.0f} → {worst["dropout_mean_m"]:.0f} m',esc(cs[worst['replacement_index']]['name']),f'{worst["replacement_mean_m"]:.0f} m'])
stairs_rows=[]
for a,l in LABELS.items():
    r=next(x for x in read(R/f'{a}_stair_sensitivity.json') if x['medicine']=='liquid')
    stairs_rows.append([l,f'{r["common_reachable_population"]:,.0f}',f'{r["normal_before_common_m"]:.0f} → {r["normal_after_common_m"]:.0f} m',f'{r["no_tagged_steps_before_common_m"]:.0f} → {r["no_tagged_steps_after_common_m"]:.0f} m',f'{r["baseline_unreachable_population"]:,.0f}'])

sources=[('SGIS 자료제공','https://sgis.mods.go.kr/view/pss/openDataIntrcn','2024 인구·연령 통계, 2025년 2분기 행정동·집계구 경계, 100m 격자. 승인 자료 4개 ZIP 확보.'),
('소상공인시장진흥공단 상가정보','https://www.data.go.kr/data/15083033/fileData.do','2026.6.30 편의점 분류 자료. 동일 좌표 정리 및 슈퍼마켓 가능 후보 제외.'),
('스마트서울맵','https://map.seoul.go.kr/smgis2/','2026.10.4 조회, 폐의약품 전용수거함 테마.'),
('인터넷우체국 우체통 찾기','https://m.epost.go.kr/mobile/postFind/postMapSearch.jsp','2026.10.4 조회. 알약류 배출 시나리오에 사용.'),
('서울시 버스정류소 위치정보','https://data.seoul.go.kr/dataList/OA-15067/S/1/datasetView.do','2026.9.2 자료. 한강선착장 제외.'),
('© OpenStreetMap contributors / ODbL','https://www.openstreetmap.org/copyright','2026.10.4 보행망. 전체 33개 분할 추출 파일을 중복 정리해 연결.'),
('서울시 폐의약품 배출 안내','https://mediahub.seoul.go.kr/archives/2015766','2025.10.24. 우체통의 물약류 수거 제외를 반영.'),
('Hakimi (1964), Optimum Locations of Switching Centers','https://doi.org/10.1287/opre.12.3.450','도로망 위에서 수요 가중 거리를 최소화하는 입지 분석의 방법론적 배경.')]
source_html='<ol>'+''.join(f'<li><a href="{u}">{t}</a> — {d}</li>' for t,u,d in sources)+'</ol>'
page='''<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>서울 폐의약품 배출 이동부담 — 주민 인구를 반영한 최적화</title>
<style>body{margin:0;background:#f2f5f6;color:#223b48;font:17px/1.75 -apple-system,BlinkMacSystemFont,'Apple SD Gothic Neo',sans-serif}main{max-width:1120px;margin:auto;padding:40px 22px 70px}header,section{background:#fff;padding:30px 36px;margin-bottom:20px;border-radius:12px}h1{font-size:34px;line-height:1.35;letter-spacing:-.8px}h2{font-size:25px;margin-top:0}h3{font-size:20px;margin-top:28px}.kicker{color:#177f79;font-size:14px;letter-spacing:.4px}.lead{font-size:21px}.cards{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin:24px 0}.card{background:#eef7f5;border-radius:10px;padding:22px}.card span,.card strong,.card em{display:block}.card strong{font-size:30px;color:#125e58}.card em{font-style:normal;color:#237e74}.note,figcaption{font-size:14px;color:#5b707a}a{color:#186e95}nav{display:flex;gap:18px;flex-wrap:wrap;padding:12px 0}figure{margin:24px 0}img{width:100%;height:auto}figcaption{text-align:right}.scroll{overflow:auto}table{border-collapse:collapse;width:100%;font-size:15px;margin:18px 0}th,td{border-bottom:1px solid #dbe4e8;text-align:left;padding:10px 9px}th{background:#edf3f5;white-space:nowrap}.callout{background:#edf7f5;border-left:4px solid #258b81;padding:16px 20px}.formula{padding:18px 24px;background:#f3f6f8;border-radius:8px}summary{cursor:pointer;font-weight:600}details{padding:15px 0;border-top:1px solid #e0e7eb}li{margin:7px 0}.tag{font-size:13px;color:#667b86}@media(max-width:700px){main{padding:16px 10px}header,section{padding:23px 17px}.cards{grid-template-columns:1fr}h1{font-size:27px}h2{font-size:22px}table{font-size:13px}}@media print{body{background:#fff}main{padding:0}section{break-inside:avoid}nav,figcaption{display:none}}</style></head><body><main>'''
page+=f'''<header><div class="kicker">2026.10.04 분석 · SGIS 주민 인구 연결 완료</div><h1>폐의약품을 버리러 걷는 거리,<br>편의점 5곳을 더하면 얼마나 줄어들까?</h1><p class="lead">봉천동 일대와 창신·숭인동의 주민 위치를 보행망에 연결하고, 기존 수거망을 유지하면서 추가 편의점을 선정했습니다.</p><div class="cards">{''.join(cards)}</div><p>비교에 포함한 공개 인구는 총 <b>259,200명</b>입니다. 위 수치는 각 주민이 한 번 배출하러 간다고 가정했을 때의 인구 가중 평균 왕복거리입니다.</p><nav><a href="#maps">전후 지도</a><a href="#scale">추가 점포 수</a><a href="#trip">정류소 경유</a><a href="#age">고령층</a><a href="#sites">선정 후보</a><a href="#method">분석 방법</a></nav></header>'''
page+='''<section><h2>이번 분석의 질문</h2><p>기존 수거지가 있어도 찾아가는 데 긴 우회가 필요할 수 있습니다. <b>“수거지를 생활권에 더했을 때 주민의 배출 이동 부담을 얼마나 줄일 수 있는가?”</b>를 중심 질문으로 삼았습니다.</p><p>이를 <b>집에서 수거지까지의 왕복 배출</b>과 <b>정류소로 가면서 수거지를 들르는 경유 배출</b>로 나눴습니다. 주민 수·고령인구·보행망·정류소·수거 가능 품목은 각각 수요, 형평성, 이동 비용, 이동 상황, 이용 가능한 시설을 결정합니다.</p><div class="callout">선정 기준은 주변 시설의 개수를 합산한 점수가 아니라, <b>기존 수거망에 비해 줄어드는 주민의 보행거리</b>입니다. 기존 수거지와 효과가 겹치는 후보는 추가 이익이 작게 계산됩니다.</div></section>'''
page+=f'<section id="maps"><h2>1. 어느 곳의 이동 부담이 줄었나</h2><p>격자의 색이 옅어질수록 배출을 위한 왕복거리가 짧습니다. 왼쪽과 오른쪽에 같은 색 기준을 적용했고, 오른쪽 번호는 아래 선정 점포 표와 연결됩니다.</p>{maps}<p class="note">물약류 · 각 지역 5곳 · 전체 인구의 거리 최소화 결과. 100m 인구 격자 중심에서 계산. 회색은 인구 미공개 격자이며 0명으로 처리하지 않았습니다. 지도: SGIS, 스마트서울맵, 소상공인시장진흥공단, © OpenStreetMap contributors / ODbL.</p>{table(["지역","품목","기존 평균","5곳 추가 평균","감소율","상위 10% 경계 거리¹"],headline_rows)}<p class="note">¹ 인구 가중 90백분위 거리. 주민의 90%가 이 값 이하에 위치한다는 뜻입니다. 품목마다 5곳을 따로 최적화했으므로, 알약류와 물약류의 선정 점포가 모두 같지는 않습니다.</p>{img("05_동별_개선효과","동별 물약류 왕복거리 개선")}<p>지역 전체 평균과 함께 동별 개선을 확인할 수 있습니다. 지도에서 남은 짙은 격자는 편의점 5곳만으로 충분히 보완되지 않은 곳입니다.</p></section>'
page+=f'<section id="scale"><h2>2. 몇 곳을 추가하는 것이 좋은가</h2>{img("02_도입규모와_왕복거리","추가 점포 수에 따른 왕복거리")}<p>0·3·5·10·15곳을 각각 계산했습니다. 이 곡선으로 점포를 더 늘릴 때 얻는 추가 개선을 비교할 수 있습니다. 실제 도입 규모는 점포당 운영·회수 비용을 확인한 뒤 결정하는 것이 적절합니다.</p><p class="note">각 규모를 독립적으로 최적화했습니다. 5곳의 선정 점포가 10곳 선정안에 모두 포함된다는 뜻은 아닙니다. 고정 순서의 단계별 도입안은 별도 제약을 두어 계산해야 합니다.</p></section>'
page+=f'<section id="trip"><h2>3. 정류소로 가면서 배출할 때도 도움이 될까</h2><div class="formula"><b>추가 경유거리</b> = 집 → 수거지 → 정류소 거리 − 집 → 정류소 거리</div><p>각 거주지에서 보행거리상 가장 가까운 정류소를 하나 정했습니다. 아래 가운데 막대는 앞서 왕복거리로 선정한 <b>같은 5곳</b>을 활용한 결과이고, 오른쪽은 경유거리 감소를 목표로 다시 선정한 결과입니다.</p>{img("03_같은점포의_정류소경유효과","같은 점포의 정류소 경유 효과와 경유 최적화 비교")}<p>이 비교는 “배출만을 위한 방문”과 “이동 중 들르기”에 적합한 점포가 얼마나 겹치는지 보여줍니다. 정류소 위치만으로 실제 통근 경로나 배출 참여율을 알 수는 없어, 현재는 이동 상황을 가정한 비교로 사용합니다.</p></section>'
page+=f'<section id="age"><h2>4. 고령층을 우선하면 선정 결과가 달라질까</h2><p>전체 거리 감소를 최대로 만드는 배치를 먼저 찾고, 그 효과의 <b>95% 이상을 유지</b>하면서 65세 이상 주민의 거리를 가장 많이 줄이는 배치를 계산했습니다. 95%는 정책 선택을 보여주기 위한 조건이며, 90%·100%도 함께 비교했습니다.</p>{img("04_전체효과와_고령층개선","전체 효과와 고령층 개선의 절충")}{table(["지역","전체 평균: 효율안 → 고령층 우선안","65세 이상: 효율안 → 고령층 우선안","점포 구성"],fair_rows)}<p>창신·숭인동에서는 전체 평균거리가 약 11m 늘어나는 대신 고령층 평균거리를 약 27m 더 줄일 수 있었습니다. 봉천동에서는 고령층의 추가 개선이 약 6m로 상대적으로 작았습니다. <b>고령층 변수를 넣는 효과가 두 지역에서 같지는 않았습니다.</b></p><p class="note">고령인구는 집계구 대표점으로 계산했습니다. 미공개 연령값은 총인구와 공개 연령값을 이용해 하한·상한을 구했습니다. 그림·주 결과는 하한 가중치이며, 전체 인구의 100m 격자 결과와 절대 수준을 직접 비교해 연령 차이라고 해석하지 않습니다. {esc(" ".join(fair_notes))}</p></section>'
page+=f'<section id="sites"><h2>5. 물약류 왕복거리 기준 선정 후보</h2><p>지역별 5곳을 추가하는 효율안입니다. 점포명과 주소는 확보한 상가정보의 표기를 유지했습니다.</p>{sites}<p class="note">입지 분석 후보이며 점포의 참여·영업·보관 공간·실제 출입구를 확인한 목록은 아닙니다. 선정 전 확인 항목은 원본 자료의 표시를 그대로 남겼습니다.</p><h3>한 곳이 참여하지 않을 때의 대안</h3><p>선정 점포를 한 곳씩 제외하고, 나머지 4곳을 유지한 채 대체 후보를 찾았습니다. 아래는 각 지역에서 손실이 가장 큰 한 곳의 사례입니다.</p>{table(["지역","참여 불발 점포","평균거리 변화","대체 후보","대체 후"],risk_rows)}<p class="note">불참 확률을 추정한 값은 아니며, 5개 단일 불참 상황을 각각 계산한 결과입니다.</p></section>'
page+=f'<section><h2>6. 결과가 얼마나 안정적인가</h2><p>40개 기본 모형은 모두 설정한 허용 오차 안에서 최적해를 확인했습니다. 점포 수가 늘수록 평균거리가 증가하지 않는지, 전후 비교 인구가 같은지, 후보 지역이 주민 분석 범위와 맞는지도 검증했습니다.</p><details><summary>계단으로 표시된 길을 제외한 경우</summary>{table(["지역","공통 비교 인구","일반 보행망 전→후","계단 제외 전→후","경로 미연결 인구"],stairs_rows)}<p class="note">물약류, 같은 선정 5곳을 유지한 평가. 계단 제외 전후 모두 경로가 연결되고 지도 경계의 영향을 피하는 인구끼리 비교했습니다. 미연결 인구를 0거리로 넣지 않았습니다. OSM 계단 표기의 완전성은 확인되지 않았고 경사·승강기·문턱은 반영하지 않아 무장애 접근성을 뜻하지 않습니다.</p></details><details><summary>큰 인구 격자와 후보 출입 조건에 대한 점검</summary><p>가장 인구가 큰 격자를 한 개 제외하고 다시 선정하면 두 지역 모두 물약류 왕복거리 기준 5곳 중 4곳이 유지됐습니다. 봉천동의 해당 격자는 공개 인구 6,088명으로 분석 인구의 2.7%를 차지합니다. 이 격자는 기본 분석에 그대로 포함하고, 제외 결과를 별도 민감도로 남겼습니다.</p><p>시설 내부 출입 또는 층 정보 확인 표시가 있는 후보를 제외해도 두 지역의 물약류 왕복 5곳 선정안은 유지됐습니다. 이 확인만으로 다른 후보의 실제 영업·출입 상태가 보장되는 것은 아닙니다.</p></details><details><summary>350m 기준은 어떻게 다뤘나</summary><p>이번 최적화에는 350m 경계가 없습니다. 가까워지는 거리 자체를 계산하므로 349m와 351m가 전혀 다른 집단으로 나뉘지 않습니다. 200·350·500m 이내 보행 접근률은 이전 분석과 비교할 수 있는 보조 지표로만 별도 저장했습니다.</p></details></section>'
page+='''<section id="method"><h2>분석 범위와 계산 방법</h2><p><b>공간 범위:</b> 봉천동에 대응하는 9개 행정동, 창신·숭인동의 5개 행정동. 기존 수거지는 행정경계 밖의 인접 시설도 포함하며, 편의점 후보는 해당 행정동 범위 안에서 선정했습니다. 후보는 각각 142곳과 40곳입니다.</p><p><b>인구와 거리:</b> 2024년 100m 인구 격자를 2025년 2분기 행정경계와 연결했습니다. 도로망·시설은 2026년 자료이므로 “2024 인구 분포에 현재 공개 시설망을 적용한 분석”입니다. 봉천동 공개 인구 223,327명 중 223,164명, 창신·숭인동 36,036명 전원을 비교에 포함했습니다.</p><p><b>보행망:</b> OSM의 보행 금지·사유 접근 도로를 제외하고, 공유 노드를 통해 도로를 연결했습니다. 거주지와 시설을 가장 가까운 도로 구간에 연결하며 최대 연결 거리는 80m입니다. 연결 거리도 이동 비용에 포함했습니다. 지도 경계 밖을 경유하는 더 짧은 경로의 가능성은 거리 하한으로 점검했습니다.</p><p><b>수거 품목:</b> 알약류는 전용 수거함과 우체통, 물약류는 전용 수거함을 기존망으로 사용했습니다. 추가 편의점에는 해당 품목을 수거할 수 있는 설비를 도입하는 상황을 가정합니다. 시간대별 수거 가능 여부는 계산에 넣지 않았습니다.</p><div class="formula"><b>기본 모형</b><br>각 거주지의 이용 비용 = 기존 수거지와 선정 편의점 중 가장 짧은 이동거리<br>목표 = 모든 거주지의 [인구 × 이용 비용] 합 최소화<br>조건 = 추가 점포 수 ≤ K, 기존 수거망 유지<br><br><b>고령층 우선 모형</b><br>목표 = [65세 이상 인구 × 이용 비용] 합 최소화<br>추가 조건 = 전체 인구의 거리 감소가 효율안 감소량의 90%·95%·100% 이상</div><p>혼합정수 최적화로 계산했으며 점포 간 중복 혜택은 같은 주민에게 두 번 합산하지 않습니다. 실제 배출 횟수·회수량·사업비·영업시간 자료가 추가되면 수요와 운영 제약을 확장할 수 있습니다.</p><p class="note">SGIS 격자 인구에는 비밀보호 조정이 적용됩니다. 이번 결과는 공개 인구를 가중치로 사용한 잠재 보행거리이며, 관측된 개인 이동거리나 연간 총거리 절감량은 아닙니다. 연령 자료는 집계구 단위를 유지했습니다.</p></section>'''
page+=f'<section><h2>현재 결과에서 가져갈 이야기</h2><p><b>“기존 수거망을 유지하면서 생활권 거점을 더하면 배출을 위해 따로 걷는 거리와 이동 중 우회 부담을 줄일 수 있다.”</b> 주민 인구를 반영한 이번 결과가 이를 뒷받침합니다.</p><p>연구의 주축은 물약류의 왕복 이동 부담과 보완 입지로 두고, 정류소 경유와 고령층 우선 배치를 확장 분석으로 연결하면 흐름이 분명합니다. 물약류는 우체통을 이용할 수 없어 기존망과 추가 거점의 역할을 구분하기도 좋습니다.</p><p>다음 검증은 선정 후보 주변의 실제 횡단·출입구·계단 연결과 수거 운영 조건에 집중하면 됩니다. 경사에 따른 보행시간은 고도 자료를 연결한 뒤 별도로 계산해야 합니다.</p></section><section><h2>출처와 결과 자료</h2>{source_html}<p><a href="summary.json">전체 40개 기본 분석</a> · <a href="extensions.json">고령층·불참 대안·민감도 결과</a> · <a href="interpretation_metrics.json">동별·동일 점포 경유·거리별 접근률</a> · <a href="validation.json">결과 검증</a> · <a href="../../data/processed/source_manifest.json">자료 출처와 원본 해시</a></p><p class="note">자료: 각 제공기관 및 본 연구 계산. 모든 그림은 바로 아래 링크로 따로 저장할 수 있습니다. 분석·정리에는 AI의 코드 작성과 검토 지원을 사용했습니다. 이 페이지는 연구 검토용 결과물입니다.</p></section></main></body></html>'
path=R/'서울_주민기준_이동부담과_편의점최적화.html';path.write_text(page,encoding='utf-8')

# Extend provenance without rewriting or deleting earlier source records.
manifest_path=ROOT/'data/processed/source_manifest.json';manifest=read(manifest_path)
present={r.get('path') for r in manifest}
names=['SGIS 서울 2024 인구·연령 통계','SGIS 서울 2025Q2 행정동 경계','SGIS 서울 2025Q2 집계구 경계','SGIS 다사 격자 경계']
for rec,name in zip(INPUT['inputs'],names):
    rel='data/raw/'+rec['file']
    if rel not in present: manifest.append({'name':name,'path':rel,'sha256':rec['sha256'],'source_url':'https://sgis.mods.go.kr/view/pss/downloadList','obtained_on':'2026-10-04','reference_date':'2024 통계 / 2025 경계','note':'사용자 신청·승인 후 공식 다운로드. 신청자 개인정보는 분석 파일에 포함하지 않음.'})
for rec in read(ROOT/'data/raw/expanded_osm/manifest.json')['files']:
    rel=rec['file']
    if rel not in present: manifest.append({'name':'OSM 보행망 확장 추출','path':rel,'sha256':rec['sha256'],'source_url':rec.get('url',rec.get('source_url','https://api.openstreetmap.org/api/0.6/map')),'obtained_on':'2026-10-04','license':'ODbL / © OpenStreetMap contributors'})
dump(manifest_path,manifest)
dump(ROOT/'results/continuation_status.json',{'stage':'resident_models_completed','updated_on':'2026-10-04',
      'report':str(path),'models':40,'validations':'passed','scope':['봉천동 9개 행정동','창신·숭인동 5개 행정동'],
      'remaining_research_checks':['선정 점포 출입구·횡단·보행 연결 대조','고도 자료와 경사 이동시간','점포 운영·참여 조건'],
      'note':'수집·공간 연결·주민 가중 최적화 완료. 공모전 제출 또는 현장 검증 완료를 뜻하지 않음.'})
print(json.dumps({'report':str(path),'models_validated':len(checks),'figures':len(list(F.glob('*.png'))),'cross':cross},ensure_ascii=False,indent=2))
