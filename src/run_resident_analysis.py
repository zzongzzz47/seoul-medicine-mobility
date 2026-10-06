"""Run resident-weighted walking and hypothetical bus-stop detour scenarios.

Requires actual downloaded SGIS inputs from prepare_resident_inputs.py.
There is deliberately no synthetic-data fallback for missing resident files.
"""
import hashlib, json, pickle
from pathlib import Path
import numpy as np
from mobility_network import ROOT, WalkingNetwork
from location_model import solve_location

DATA=ROOT/'data/processed'; RES=DATA/'residents'; OUT=ROOT/'results/resident_analysis'
CONFIGS={'bongcheon':('관악구',['봉천동']),'changsin_sungin':('종로구',['창신동','숭인동'])}

def read(path): return json.loads(path.read_text())
def dump(path,data): path.write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False))
def weighted_quantile(values,weights,q):
    order=np.argsort(values);v=np.asarray(values)[order];w=np.asarray(weights)[order]
    return float(v[np.searchsorted(np.cumsum(w),q*w.sum(),side='left')])

def main():
    for area in CONFIGS:
        if not (RES/f'{area}_population.json').exists():
            raise FileNotFoundError(f'SGIS 주민 인구 원본을 먼저 연결해야 합니다: {area}')
    OUT.mkdir(parents=True,exist_ok=True)
    cvs=read(DATA/'convenience_candidates.json'); bins=read(DATA/'existing_bins.json'); posts=read(DATA/'postboxes.json'); bus=read(DATA/'bus_stops.json')
    summaries=[]
    for area,(gu,dongs) in CONFIGS.items():
        net=WalkingNetwork(area);w,s,e,n=net.bbox
        inside=lambda r:w<=r['lon']<=e and s<=r['lat']<=n
        all_population=read(RES/f'{area}_population.json')
        all_elderly=read(RES/f'{area}_elderly.json') if (RES/f'{area}_elderly.json').exists() else []
        known=[r for r in all_population if r['population'] is not None and r['population']>0]
        elderly_known=[r for r in all_elderly if r['population'] is not None and r.get('population_upper',r['population'])>0]
        pop=[r for r in known if inside(r)];older=[r for r in elderly_known if inside(r)]
        demand=pop+older; N=len(pop)
        candidates=[r for r in cvs if r['district']==gu and r['legal_dong'] in dongs and inside(r) and '슈퍼마켓 가능성' not in r['flags']]
        existing=[r for r in bins+posts if inside(r)]
        sites=existing+candidates;M=len(existing)
        stops=[{**r,'id':'BUS_'+r['id']} for r in bus if inside(r) and r['kind']!='한강선착장']
        net.attach(demand+sites+stops)
        ids=[r['id'] for r in demand];site_ids=[r['id'] for r in sites];stop_ids=[r['id'] for r in stops]
        stop_distance,nearest_stop=net.nearest(stop_ids,ids,reverse=True)
        target_stops=list(dict.fromkeys(b for b in nearest_stop if b is not None))
        stop_lookup={b:i for i,b in enumerate(target_stops)}
        to_sites=np.full((len(demand),len(sites)),np.inf);from_sites=to_sites.copy()
        site_to_stop=np.full((len(target_stops),len(sites)),np.inf)
        undirected=net.audit['explicit_foot_oneway']==0
        network_manifest=read(ROOT/'data/raw/expanded_osm/manifest.json')
        network_sources=[r['sha256'] for r in network_manifest['files'] if r['area']==area]
        signature=hashlib.sha256(json.dumps({'points':demand+sites+stops,'network':net.audit,'sources':network_sources,
          'network_code':hashlib.sha256((ROOT/'src/mobility_network.py').read_bytes()).hexdigest()},ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        cache=OUT/f'{area}_{signature[:16]}_costs.npz'
        if cache.exists():
            arrays=np.load(cache);to_sites=arrays['to_sites'];from_sites=arrays['from_sites'];site_to_stop=arrays['site_to_stop']
        else:
            for j,sid in enumerate(site_ids):
                forward=net.distances(sid,ids+target_stops)
                from_sites[:,j]=forward[:len(ids)];site_to_stop[:,j]=forward[len(ids):]
                to_sites[:,j]=forward[:len(ids)] if undirected else net.distances(sid,ids,reverse=True)
            np.savez_compressed(cache,to_sites=to_sites,from_sites=from_sites,site_to_stop=site_to_stop)
        dump(OUT/f'{area}_cost_context.json',{'demand':demand,'resident_count':N,'candidates':candidates,'existing':existing,
             'stops':stops,'nearest_stop':nearest_stop,'target_stops':target_stops,'cost_cache':cache.name,
             'stop_distance':[float(d) if np.isfinite(d) else None for d in stop_distance]})
        with (OUT/f'{area}_network.pkl').open('wb') as f:pickle.dump(net,f)
        roundtrip=to_sites+from_sites
        chain=np.full_like(roundtrip,np.inf)
        for i,b in enumerate(nearest_stop):
            if b is None: continue
            chain[i]=to_sites[i]+site_to_stop[stop_lookup[b]]-stop_distance[i]
        if np.any(np.isfinite(chain)&(chain<-.01)): raise AssertionError('Detour must be nonnegative by the shortest-path triangle inequality.')
        chain=np.maximum(chain,0)
        scenario_baseline={}
        for medicine in ('solid','liquid'):
            valid=[j for j,r in enumerate(existing) if medicine=='solid' or r['kind']=='전용 수거함']
            if not valid: raise ValueError(f'No existing facilities: {area} {medicine}')
            scenario_baseline[(medicine,'roundtrip')]=np.min(roundtrip[:,valid],axis=1)
            scenario_baseline[(medicine,'stop_detour')]=np.min(chain[:,valid],axis=1)
        pop_weights=np.array([r['population'] if i<N else 0 for i,r in enumerate(demand)],float)
        age_weights=np.array([r['population'] if i>=N else 0 for i,r in enumerate(demand)],float)
        margins=np.array([net.snaps[r['id']]['boundary_margin_m'] for r in demand])
        stop_margins=np.array([net.snaps[b]['boundary_margin_m'] if b else 0 for b in nearest_stop])
        audit={'area':area,'input_population':float(sum(r['population'] for r in known)),
               'population_outside_network':float(sum(r['population'] for r in known if not inside(r))),
               'population_connector_over80m':float(sum(r['population'] for r in pop if not net.snaps[r['id']]['matched'])),
               'elderly_released_population':float(sum(r['population'] for r in elderly_known)),
               'elderly_weight_basis':'집계구 연령·총인구에서 산출한 하한',
               'candidate_count':len(candidates),'network':net.audit,'cohorts':{}}
        for trip_type,costs in [('roundtrip',roundtrip),('stop_detour',chain)]:
            finite=np.isfinite(scenario_baseline[('solid',trip_type)])&np.isfinite(scenario_baseline[('liquid',trip_type)])
            if trip_type=='roundtrip':
                # Any route that exits and returns must travel to the extraction edge twice.
                safe=finite & (scenario_baseline[('liquid',trip_type)]<2*margins)
            else:
                # A path leaving the extract must travel origin→edge and edge→fixed stop.
                full_path=scenario_baseline[('liquid',trip_type)]+stop_distance
                safe=finite & (full_path<margins+stop_margins) & (stop_distance<margins)
            included=np.flatnonzero(safe)
            weights=pop_weights[included];ages=age_weights[included]
            if weights.sum()<=0: raise ValueError('No resident population in the verified comparison cohort.')
            audit['cohorts'][trip_type]={'population':float(weights.sum()),'elderly_released':float(ages.sum()),
                                      'resident_points':int(sum(i<N for i in included)),
                                      'population_share_of_input_pct':float(weights.sum()/audit['input_population']*100)}
            c=costs[np.ix_(included,range(M,len(sites)))]
            for medicine in ('solid','liquid'):
                base=scenario_baseline[(medicine,trip_type)][included]
                for k in (0,3,5,10,15):
                    solved=solve_location(base,c,weights,k,time_limit=90)
                    if not solved['success']: raise RuntimeError(solved)
                    after=np.array(solved.pop('cost_after'))
                    solved.update(area=area,medicine=medicine,trip_type=trip_type,k=k,
                                  population=float(weights.sum()),
                                  baseline_p90_m=weighted_quantile(base,weights,.9),after_p90_m=weighted_quantile(after,weights,.9),
                                  selected_sites=[candidates[j] for j in solved['selected_indices']],
                                  elderly_mean_before_m=float(np.average(base,weights=ages)) if ages.sum()>0 else None,
                                  elderly_mean_after_m=float(np.average(after,weights=ages)) if ages.sum()>0 else None,
                                  trip_assumption='각 주민 1회 왕복 배출의 잠재 보행거리' if trip_type=='roundtrip' else '각 거주지에서 보행거리상 가장 가까운 정류소로 가는 가정 경로의 추가거리')
                    # Leave-one-out is a participation failure scenario, not a measured probability.
                    losses=[]
                    for missing in solved['selected_indices']:
                        remaining=[j for j in solved['selected_indices'] if j!=missing]
                        fallback=np.minimum(base,c[:,remaining].min(axis=1)) if remaining else base.copy()
                        losses.append({'site_id':candidates[missing]['id'],'mean_added_distance_m':float(np.average(fallback-after,weights=weights))})
                    solved['single_store_dropout']=losses
                    summaries.append(solved)
                    detail=[{**demand[i],'weight_in_total_objective':float(weights[p]),'baseline_m':float(base[p]),'after_m':float(after[p])} for p,i in enumerate(included)]
                    dump(OUT/f'{area}_{medicine}_{trip_type}_k{k}_origins.json',detail)
            # Save the exact common cohort used for both medicine categories.
        dump(OUT/f'{area}_audit.json',audit)
        print(area,audit['cohorts'],flush=True)
    dump(OUT/'summary.json',summaries)

if __name__=='__main__': main()
