"""Equity, drop-out replacement, age uncertainty, and tagged-stair sensitivity."""
import json,pickle
import numpy as np
from mobility_network import ROOT
from location_model import solve_location

OUT=ROOT/'results/resident_analysis'
def read(p):return json.loads(p.read_text())
def dump(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False))
def avg(v,w):return float(np.average(v,weights=w))
def after_cost(base,c,selected):return np.minimum(base,c[:,selected].min(axis=1)) if selected else base.copy()

def main():
    summary=read(OUT/'summary.json');ext=[]
    for area in ['bongcheon','changsin_sungin']:
        context=read(OUT/f'{area}_cost_context.json');rows=context['demand'];N=context['resident_count'];M=len(context['existing'])
        data=np.load(OUT/context['cost_cache']);roundtrip=data['to_sites']+data['from_sites']
        stop_index={b:i for i,b in enumerate(context['target_stops'])}
        chain=np.full_like(roundtrip,np.inf)
        for i,b in enumerate(context['nearest_stop']):
            if b is not None:chain[i]=data['to_sites'][i]+data['site_to_stop'][stop_index[b]]-context['stop_distance'][i]
        chain=np.maximum(chain,0)
        all_ids={r['id']:i for i,r in enumerate(rows)}
        for trip,costs in [('roundtrip',roundtrip),('stop_detour',chain)]:
            for medicine in ('solid','liquid'):
                efficient=next(r for r in summary if r['area']==area and r['trip_type']==trip and r['medicine']==medicine and r['k']==5)
                cohort=read(OUT/f'{area}_{medicine}_{trip}_k5_origins.json')
                idx=np.array([all_ids[r['id']] for r in cohort]);base=np.array([r['baseline_m'] for r in cohort]);c=costs[idx,M:]
                pop=np.array([r['population'] if r['source_kind']=='grid100m' else 0 for r in cohort])
                low=np.array([r['population_lower'] if r['source_kind']=='census' else 0 for r in cohort])
                high=np.array([r['population_upper'] if r['source_kind']=='census' else 0 for r in cohort])
                E=efficient['selected_indices'];eff_after=after_cost(base,c,E)
                B=avg(base,pop);Emean=avg(eff_after,pop)
                fair=[]
                for retained in (.90,.95,1.):
                    limit=B-retained*(B-Emean)+1e-6
                    solved=solve_location(base,c,low,5,group_weights=pop,group_max_mean=[limit],time_limit=90)
                    if not solved['success']:raise RuntimeError(solved)
                    F=solved['selected_indices'];v=after_cost(base,c,F)
                    fair.append({'retained_total_benefit_fraction':retained,'selected_indices':F,
                                 'population_mean_m':avg(v,pop),'elderly_lower_weighted_mean_m':avg(v,low),
                                 'elderly_upper_weighted_mean_m':avg(v,high),'proven_optimal':solved['proven_optimal'],
                                 'mip_gap':solved['mip_gap'],'overlap_with_efficiency':len(set(E)&set(F))})
                upper_solve=solve_location(base,c,high,5,group_weights=pop,
                    group_max_mean=[B-.95*(B-Emean)+1e-6],time_limit=90)
                if not upper_solve['success']:raise RuntimeError(upper_solve)
                replacements=[]
                for missing in E:
                    fixed=[j for j in E if j!=missing];lost=after_cost(base,c,fixed)
                    eligible=[j for j in range(c.shape[1]) if j not in E]
                    j=min(eligible,key=lambda j:avg(np.minimum(lost,c[:,j]),pop))
                    replacements.append({'dropped_index':missing,'replacement_index':j,
                                         'dropout_mean_m':avg(lost,pop),'replacement_mean_m':avg(np.minimum(lost,c[:,j]),pop)})
                largest=int(np.argmax(pop));wo=pop.copy();wo[largest]=0
                outlier=solve_location(base,c,wo,5,time_limit=90)
                restricted=[j for j,r in enumerate(context['candidates']) if any(f in r['flags'] for f in ['시설 내부 출입 확인','층 정보 확인'])]
                restricted_result=solve_location(base,c,pop,5,forbidden_sites=restricted,time_limit=90)
                ext.append({'area':area,'trip_type':trip,'medicine':medicine,
                            'population_before_m':B,'population_efficient_m':Emean,
                            'elderly_before_lower_m':avg(base,low),'elderly_efficient_lower_m':avg(eff_after,low),
                            'elderly_before_upper_m':avg(base,high),'elderly_efficient_upper_m':avg(eff_after,high),
                            'fairness':fair,'elderly_upper_95_selected':upper_solve['selected_indices'],
                            'age_weight_interval_note':'하한·상한 가중치 두 시나리오이며 가능한 모든 인구 배치의 최악값을 뜻하지 않음.',
                            'dropout_replacements':replacements,
                            'largest_grid_sensitivity':{'grid_id':cohort[largest]['id'],'population':float(pop[largest]),
                                'share_pct':float(pop[largest]/pop.sum()*100),'selected':outlier['selected_indices'],
                                'overlap_with_main':len(set(E)&set(outlier['selected_indices'])),
                                'after_mean_on_omitted_sample_m':outlier['after_mean_m']},
                            'restricted_candidates':{'excluded_count':len(restricted),'selected':restricted_result['selected_indices'],
                                'after_mean_m':restricted_result['after_mean_m'],'reduction_pct':restricted_result['reduction_pct']}})
        # Evaluate the already-selected five stores when all OSM-tagged stairs are removed.
        with (OUT/f'{area}_network.pkl').open('rb') as f:net=pickle.load(f)
        selected_union=sorted(set(j for r in summary if r['area']==area and r['trip_type']=='roundtrip' and r['k']==5 for j in r['selected_indices']))
        all_sites=context['existing']+context['candidates']
        cols=list(range(M))+[M+j for j in selected_union]
        no_steps=np.full((len(rows),len(cols)),np.inf)
        for q,j in enumerate(cols):
            sid=all_sites[j]['id'];fwd=net.distances(sid,[r['id'] for r in rows],no_tagged_steps=True)
            rev=fwd if net.audit['explicit_foot_oneway']==0 else net.distances(sid,[r['id'] for r in rows],reverse=True,no_tagged_steps=True)
            no_steps[:,q]=fwd+rev
        stairs=[]
        for medicine in ('solid','liquid'):
            entry=next(r for r in summary if r['area']==area and r['trip_type']=='roundtrip' and r['medicine']==medicine and r['k']==5)
            cohort=read(OUT/f'{area}_{medicine}_roundtrip_k5_origins.json');idx=np.array([all_ids[r['id']] for r in cohort])
            pop=np.array([r['population'] if r['source_kind']=='grid100m' else 0 for r in cohort]);base=np.array([r['baseline_m'] for r in cohort]);old_after=np.array([r['after_m'] for r in cohort])
            existing_cols=[j for j,r in enumerate(context['existing']) if medicine=='solid' or r['kind']=='전용 수거함']
            base_new=no_steps[np.ix_(idx,existing_cols)].min(axis=1)
            new_cols=existing_cols+[cols.index(M+j) for j in entry['selected_indices']]
            after_new=no_steps[np.ix_(idx,new_cols)].min(axis=1)
            reachable=np.isfinite(base_new)&np.isfinite(after_new)
            margins=np.array([net.snaps[r['id']]['boundary_margin_m'] for r in cohort])
            finite=reachable & (base_new<2*margins)
            if np.any(base_new[finite]+.01<base[finite]) or np.any(after_new[finite]+.01<old_after[finite]):raise AssertionError('Removing steps shortened a route.')
            stairs.append({'medicine':medicine,'common_reachable_population':float(pop[finite].sum()),
                           'boundary_excluded_population':float(pop[reachable&~finite].sum()),
                           'baseline_unreachable_population':float(pop[~np.isfinite(base_new)].sum()),
                           'after_unreachable_population':float(pop[~np.isfinite(after_new)].sum()),
                           'normal_before_common_m':avg(base[finite],pop[finite]),'normal_after_common_m':avg(old_after[finite],pop[finite]),
                           'no_tagged_steps_before_common_m':avg(base_new[finite],pop[finite]),'no_tagged_steps_after_common_m':avg(after_new[finite],pop[finite]),
                           'same_selected_stores':True,'reoptimized':False})
        dump(OUT/f'{area}_stair_sensitivity.json',stairs)
        print(area,'extensions complete',flush=True)
    dump(OUT/'extensions.json',ext)

if __name__=='__main__':main()
