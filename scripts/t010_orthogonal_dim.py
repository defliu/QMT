# -*- coding: utf-8 -*-
"""T010-任务2: 正交新维度IC验证 - 找与C1/C5(均线/突破)正交且正IC的维度

候选(T008未测的基本面/流动性维度, astock有数据): pe_ttm/pb/ps_ttm/dv_ttm/turnover_rate/total_mv/ATR
248池, 2021-2026, 每10天rebal, 5d前向。
每维度: IC(z-score后) + 与8个P0维度共线性 + 牛熊分。
正交定义: |corr|<0.3 且 IC>0.02。
输出: F:/backtest_workspace/results/t010_orthogonal.json
"""
import os, sys, json, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, 'D:/QMT_STRATEGIES')
import numpy as np
import pandas as pd
from core.scoring.dimension6plus2 import ScoreCalculator6Plus2
from core.utils import ma, safe_last

OUT = 'F:/backtest_workspace/results'; os.makedirs(OUT, exist_ok=True)
POOL_FILE = 'D:/QMT_POOL/selectedall.txt'
ASTOCK = 'E:/astock/daily/stock_daily.parquet'
FWD = 5
P0 = ['score_breakout','score_trend','score_consolidation','score_volumeprice','score_macd','score_valuation','score_short_term_momentum','score_sector']
CAND = ['pe_ttm','pb','ps_ttm','dv_ttm','turnover_rate','total_mv','atr_pct']  # atr_pct自算

def log(m): print(m, flush=True)
def spearman(a, b):
    a=np.asarray(a,dtype=float);b=np.asarray(b,dtype=float)
    m=~(np.isnan(a)|np.isnan(b));a=a[m];b=b[m]
    if len(a)<5: return np.nan
    ra=a.argsort().argsort().astype(float);rb=b.argsort().argsort().astype(float)
    ra-=ra.mean();rb-=rb.mean()
    da=np.sqrt((ra**2).sum());db=np.sqrt((rb**2).sum())
    if da==0 or db==0: return np.nan
    return float((ra*rb).sum()/(da*db))
def zscore(a):  # 截面z-score
    a=np.asarray(a,dtype=float);m=np.isnan(a)
    v=a[~m]
    if len(v)<3: return a
    mu,sd=v.mean(),v.std(ddof=0)
    if sd==0: return a
    z=(a-mu)/sd; z[m]=np.nan; return z

# ── 加载池+astock(含基本面, OHLC hfq) ──
import io
raw=io.open(POOL_FILE,'r',encoding='gbk',errors='replace').read()
pool=[]
for l in raw.splitlines():
    p=l.split('\t')
    if len(p)>=1:
        c=p[0].strip()
        if len(c)==6 and c[0] in '036': pool.append(c+('.SH' if c.startswith('6') else '.SZ'))
pool=list(dict.fromkeys(pool))
df=pd.read_parquet(ASTOCK).reset_index()
df['trade_date']=pd.to_datetime(df['trade_date'])
df['ts_code']=df['ts_code'].astype(str)
df=df[df['ts_code'].isin(set(pool))].copy().rename(columns={'vol':'volume'})
for col in ['open','high','low','close']: df[col]=df[col]*df['adj_factor']
df['atr_pct']=(df['high']-df['low']).rolling(14).mean().div(df['close'])  # 简化ATR%
keep=['open','high','low','close','volume','pe_ttm','pb','ps_ttm','dv_ttm','turnover_rate','total_mv','atr_pct']
df=df[['ts_code','trade_date']+keep].sort_values(['ts_code','trade_date']).reset_index(drop=True)
codes=sorted(df['ts_code'].unique())
data={c:df[df['ts_code']==c].set_index('trade_date') for c in codes}
all_dates=sorted(df['trade_date'].unique())
log(f'池={len(pool)} 有效股票={len(data)} 交易日={len(all_dates)}')

scorer=ScoreCalculator6Plus2()
rebal_idx=list(range(0,len(all_dates),10))
pairs=[]
for ri,di in enumerate(rebal_idx):
    if di+FWD>=len(all_dates): break
    d=all_dates[di]
    pool_dict={}; fwd_d={}; cand_vals={c:[] for c in CAND}
    for c in codes:
        sub=data[c]; hist=sub[sub.index<=d]
        if len(hist)<60: continue
        fwd=sub[sub.index>d]['close']
        if len(fwd)<FWD: continue
        dfc=hist.tail(120)
        pool_dict[c]=dfc[['open','high','low','close','volume']]
        fwd_d[c]=float(fwd.iloc[FWD-1]/hist['close'].iloc[-1]-1)
        row=dfc.iloc[-1]
        for k in CAND:
            cand_vals[k].append(float(row[k]) if k in row and pd.notna(row[k]) else np.nan)
    if len(pool_dict)<20: continue
    try: res=scorer.score_pool(pool_dict)
    except: continue
    ch=[c for c in res.index if c in fwd_d]
    if len(ch)<10: continue
    pairs.append({
        'date':str(d.date()),
        'p0':{dim:np.array([float(res.loc[c,dim]) for c in ch]) for dim in P0},
        'cand':{k:zscore(np.array([cand_vals[k][ch_idx] for ch_idx in range(len(ch))])) for k in CAND},
        'fwd':np.array([fwd_d[c] for c in ch]),
    })
    if ri%20==0: log(f'  rebal {ri+1}/{len(rebal_idx)} {d.date()} n={len(ch)}')
log(f'有效rebal: {len(pairs)}')

# ── 每候选维度: IC + 共线性 + 牛熊 ──
log('=== 正交维度IC+共线性 ===')
results={'n_rebal':len(pairs),'candidates':{}}
for k in CAND:
    ics=[spearman(p['cand'][k],p['fwd']) for p in pairs]
    ics=[x for x in ics if not np.isnan(x)]
    bear=[spearman(p['cand'][k],p['fwd']) for p in pairs if p['date']<='2024-12-31']
    bull=[spearman(p['cand'][k],p['fwd']) for p in pairs if p['date']>='2025-01-01']
    bear=[x for x in bear if not np.isnan(x)]; bull=[x for x in bull if not np.isnan(x)]
    mi=float(np.mean(ics)) if ics else 0
    si=float(np.std(ics,ddof=1)) if len(ics)>1 else 0
    # 共线性: 与8 P0维度的截面相关(聚合)
    corr={}
    for dim in P0:
        all_c=np.concatenate([p['cand'][k] for p in pairs])
        all_p=np.concatenate([p['p0'][dim] for p in pairs])
        m=~(np.isnan(all_c)|np.isnan(all_p))
        if m.sum()<20: corr[dim]=0; continue
        cv=np.corrcoef(all_c[m],all_p[m])[0,1]
        corr[dim]=round(float(cv),3) if not np.isnan(cv) else 0
    maxd=max(corr,key=lambda x:abs(corr[x])); maxc=corr[maxd]
    results['candidates'][k]={
        'ic':round(mi,5),'icir':round(mi/si,4) if si>0 else 0,
        'bear_ic':round(float(np.mean(bear)) if bear else 0,5),
        'bull_ic':round(float(np.mean(bull)) if bull else 0,5),
        'corr_max_dim':maxd,'corr_max':maxc,'corr_all':corr,
        'orthogonal':abs(maxc)<0.3,'positive_ic':mi>0.02,
        'verdict':'正交+正IC✅' if (abs(maxc)<0.3 and mi>0.02) else ('正交但IC弱' if abs(maxc)<0.3 else '共线'),
    }
    log(f'  {k:14s} IC={mi:+.5f} ICIR={mi/si if si>0 else 0:+.3f} 牛={np.mean(bull) if bull else 0:+.5f} | max corr={maxd}({maxc}) | {results["candidates"][k]["verdict"]}')

orth=[k for k,v in results['candidates'].items() if v['orthogonal'] and v['positive_ic']]
results['orthogonal_positive']=orth
log(f'\n正交+正IC维度: {orth}')
with open(f'{OUT}/t010_orthogonal.json','w',encoding='utf-8') as f: json.dump(results,f,ensure_ascii=False,indent=2)
log(f'-> {OUT}/t010_orthogonal.json')
