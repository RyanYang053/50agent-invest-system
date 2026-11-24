"""Research diagnostics: probabilistic/deflated Sharpe and CSCV overfit estimates.
Conditional on stated sample and experiment assumptions; never authorize promotion.
References: Bailey & Lopez de Prado (2014), doi:10.3905/jpm.2014.40.5.094;
Bailey et al. (2016), Probability of Backtest Overfitting, doi:10.21314/JCF.2016.322.
"""
from __future__ import annotations
import math,statistics,itertools
from statistics import NormalDist
from .research import num
from .ledger import digest


def _sharpe(values):
    if len(values)<2:raise ValueError('too few returns')
    sd=statistics.stdev(values)
    if not sd>0:raise ValueError('zero variance')
    return statistics.mean(values)/sd


def deflated_sharpe(excess_returns,*,trial_sharpes,effective_trials,independent_observations):
    """All Sharpe values at native frequency, no annualization or hidden trial count.
    Trial Sharpes must be complete; effective_trials and independent_observations
    are explicit conservative externally justified inputs, not fitted by this routine.
    """
    xs=[num(x) for x in excess_returns];trials=[num(x) for x in trial_sharpes];n=len(xs)
    if n<100 or len(trials)<2 or type(effective_trials) is not int or not 2<=effective_trials<=len(trials) or type(independent_observations) is not int or not 30<=independent_observations<=n:raise ValueError('insufficient or inconsistent research sample')
    sr=_sharpe(xs);mean=statistics.mean(xs);m2=statistics.mean((x-mean)**2 for x in xs)
    skew=statistics.mean((x-mean)**3 for x in xs)/m2**1.5;kurt=statistics.mean((x-mean)**4 for x in xs)/m2**2
    sd=statistics.stdev(trials);N=effective_trials;g=.5772156649015329;normal=NormalDist()
    expected_max=sd*((1-g)*normal.inv_cdf(1-1/N)+g*normal.inv_cdf(1-1/(N*math.e)))
    var=1-skew*sr+(kurt-1)*sr**2/4
    if var<=0:raise ValueError('invalid Sharpe sampling variance')
    dsr=normal.cdf((sr-expected_max)*math.sqrt(independent_observations-1)/math.sqrt(var))
    return {'status':'CONDITIONAL_DIAGNOSTIC','observations':n,'effective_observations':independent_observations,'recorded_trials':len(trials),'effective_trials':N,'native_sharpe':sr,'expected_null_max_sharpe':expected_max,'deflated_sharpe_probability':dsr,'skewness':skew,'pearson_kurtosis':kurt,'input_hash':digest({'returns':xs,'trial_sharpes':trials}),'promotion_allowed':False,'can_trade':False,'limitations':['zero-mean null Sharpe approximation; moment estimation and dependence matter','effective trials/observations require independent justification; no alpha claim']}


def cscv_pbo(return_matrix,*,blocks=8):
    """Combinatorially symmetric cross-validation on aligned strategy net excess returns.
    Uses native-frequency Sharpe as score; ties get average rank; zero variance rejected.
    Diagnostic on a frozen complete trial matrix only; never a forward-test substitute.
    """
    if type(blocks) is not int or blocks%2 or not 4<=blocks<=12:raise ValueError('even block count 4–12 required')
    if not isinstance(return_matrix,list) or len(return_matrix)<blocks*20 or len(return_matrix)%blocks:raise ValueError('equal complete blocks required')
    matrix=[[num(v) for v in row] for row in return_matrix];k=len(matrix[0]);n=len(matrix)
    if not 3<=k<=200 or any(len(r)!=k for r in matrix):raise ValueError('rectangular trial matrix required')
    if n*k*math.comb(blocks,blocks//2)>100_000_000:raise ValueError('diagnostic compute ceiling')
    size=n//blocks;logits=[];wins=[]
    for subset in itertools.combinations(range(blocks),blocks//2):
        ins=set(subset);a=[r for i,r in enumerate(matrix) if i//size in ins];b=[r for i,r in enumerate(matrix) if i//size not in ins]
        sa=[_sharpe([r[j] for r in a]) for j in range(k)];sb=[_sharpe([r[j] for r in b]) for j in range(k)]
        # Deterministic tie-break is declared in advance; rank OOS ties by average.
        w=max(range(k),key=lambda j:sa[j]);x=sb[w];rank=1+sum(v<x for v in sb)+(sum(v==x for v in sb)-1)/2;omega=rank/(k+1)
        logits.append(math.log(omega/(1-omega)));wins.append(w)
    return {'status':'CONDITIONAL_DIAGNOSTIC','pbo':sum(x<=0 for x in logits)/len(logits),'splits':len(logits),'blocks':blocks,'trials':k,'observations':n,'input_hash':digest(matrix),'promotion_allowed':False,'can_trade':False,'limitations':['requires full registered trial matrix, PIT and cost provenance','CSCV is overfit diagnostic, not forward performance; temporal dependence and regime instability remain']}
