"""Fixed existing service + optional sites; population-weighted distance minimization.

Costs have the same units within one solve. Each row retains its best existing
facility as column zero. Rows may be resident round trips or hypothetical trips
via a fixed bus stop. Inaccessible candidate assignments are omitted.
"""
import itertools
import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix

def solve_location(baseline, candidate_costs, population, k, *, group_weights=None,
                   group_max_mean=None, fixed_sites=(), forbidden_sites=(), time_limit=120):
    baseline=np.asarray(baseline,float); costs=np.asarray(candidate_costs,float)
    weights=np.asarray(population,float)
    n,m=costs.shape
    if baseline.shape!=(n,) or weights.shape!=(n,): raise ValueError('Input dimensions disagree.')
    if np.any(~np.isfinite(baseline)) or np.any(baseline<0): raise ValueError('Baseline must be finite. Report unreachable origins separately.')
    if np.any(~np.isfinite(weights)) or np.any(weights<0) or weights.sum()<=0: raise ValueError('Population weights invalid.')
    if np.any(np.isfinite(costs)&(costs<0)): raise ValueError('Negative travel cost.')
    k=min(int(k),m)
    if k<0: raise ValueError('k must be nonnegative.')
    # Do not assign a demand point to a site worse than its existing alternative.
    rows,cols=np.where(np.isfinite(costs)&(costs<baseline[:,None]-1e-9))
    pairs=list(zip(rows.tolist(),cols.tolist()))
    nv=m+n+len(pairs)
    objective=np.zeros(nv); objective[m:m+n]=weights*baseline/weights.sum()
    for p,(i,j) in enumerate(pairs): objective[m+n+p]=weights[i]*costs[i,j]/weights.sum()
    # Binary site decisions; assignment variables may be continuous because, for
    # a fixed set, assigning to the cheapest site minimizes every cost criterion.
    integrality=np.zeros(nv,int); integrality[:m]=1
    lo=np.zeros(nv); hi=np.ones(nv)
    for j in fixed_sites: lo[j]=1
    for j in forbidden_sites: hi[j]=0
    rr=[]; cc=[]; vv=[]; lower=[]; upper=[]
    def add(terms,lb,ub):
        row=len(lower)
        for col,val in terms:
            rr.append(row);cc.append(col);vv.append(float(val))
        lower.append(lb);upper.append(ub)
    add([(j,1) for j in range(m)],-np.inf,k)
    by_origin=[[(m+i,1)] for i in range(n)]
    for p,(i,j) in enumerate(pairs):
        col=m+n+p
        by_origin[i].append((col,1))
        add([(col,1),(j,-1)],-np.inf,0)
    for terms in by_origin: add(terms,1,1)
    if group_weights is not None:
        gw=np.atleast_2d(np.asarray(group_weights,float)); thresholds=np.atleast_1d(group_max_mean)
        if gw.shape[1]!=n or len(thresholds)!=len(gw): raise ValueError('Fairness dimensions disagree.')
        for g,threshold in zip(gw,thresholds):
            if np.any(~np.isfinite(g)) or np.any(g<0) or g.sum()<=0: raise ValueError('Fairness weights invalid.')
            terms=[(m+i,g[i]*baseline[i]/g.sum()) for i in range(n)]
            terms += [(m+n+p,g[i]*costs[i,j]/g.sum()) for p,(i,j) in enumerate(pairs)]
            add(terms,-np.inf,float(threshold))
    matrix=coo_matrix((vv,(rr,cc)),shape=(len(lower),nv)).tocsc()
    result=milp(objective,integrality=integrality,bounds=Bounds(lo,hi),
                constraints=LinearConstraint(matrix,lower,upper),
                options={'time_limit':time_limit,'mip_rel_gap':1e-7})
    if result.x is None:
        return {'success':False,'status':int(result.status),'message':str(result.message)}
    selected=np.flatnonzero(result.x[:m]>.5)
    after=np.minimum(baseline,costs[:,selected].min(axis=1)) if len(selected) else baseline.copy()
    before=float(np.average(baseline,weights=weights)); mean=float(np.average(after,weights=weights))
    out={'success':True,'proven_optimal':bool(result.success),'status':int(result.status),
         'selected_indices':selected.tolist(),'baseline_mean_m':before,'after_mean_m':mean,
         'reduction_mean_m':before-mean,'reduction_pct':(before-mean)/before*100 if before>0 else 0.,
         'weighted_distance_reduction_person_m':float(np.dot(weights,baseline-after)),
         'mip_gap':float(result.mip_gap),'solver_bound_mean_m':float(result.mip_dual_bound),
         'solver_message':str(result.message),'cost_after':after.tolist()}
    if group_weights is not None:
        out['group_after_mean_m']=[float(np.average(after,weights=g)) for g in gw]
        if any(a>b+1e-4 for a,b in zip(out['group_after_mean_m'],thresholds)):
            raise AssertionError('Selected locations violate fairness bound.')
    if mean>before+1e-6: raise AssertionError('Optional new sites worsened access.')
    if not np.isclose(mean,result.fun,rtol=1e-5,atol=1e-4):
        raise AssertionError('Reported assignment cost does not match selected sites.')
    return out

def validate_model():
    """Small mathematical checks, separate from empirical results."""
    rng=np.random.default_rng(24)
    checked=0
    for _ in range(6):
        baseline=rng.uniform(100,900,7); costs=rng.uniform(0,1000,(7,6)); w=rng.integers(1,100,7)
        costs[0,0]=np.inf
        previous=float(np.average(baseline,weights=w))
        for k in range(4):
            solved=solve_location(baseline,costs,w,k)
            brute=min(float(np.average(np.minimum(baseline,costs[:,s].min(axis=1)),weights=w)) if s else float(np.average(baseline,weights=w))
                      for size in range(k+1) for s in itertools.combinations(range(6),size))
            assert solved['proven_optimal'] and abs(solved['after_mean_m']-brute)<1e-5
            assert solved['after_mean_m']<=previous+1e-6
            previous=solved['after_mean_m']; checked+=1
    return {'enumeration_comparisons':checked,'passed':True,'empirical_results':False}

if __name__=='__main__':
    import json
    print(json.dumps(validate_model()))
