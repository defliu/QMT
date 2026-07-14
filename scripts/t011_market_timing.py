# -*- coding: utf-8 -*-
"""T011-任务1: 大盘择时验证 - 评分器牛市开/熊市关 是否提升

T007发现评分器牛市弱正/熊市全负。本任务验证: 大盘择时(多头选股/空头空仓)是否避免熊市亏损。
大盘代理: 248池等权指数(每日等权收益累计, 因astock无指数数据)。
择时信号: 大盘>MA20 且 MA20>MA60(多头)。
对比: 全周期ge-60(不择时) vs 择时ge-60(多头选/空头空) vs 买入持有248等权。
2021-2026(含牛熊), 每10天rebal, score_pool, 505(C1-C7)+ge-60等权cap5。
输出: F:/backtest_workspace/results/t011_timing.json
"""
import os, sys, json, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, 'D:/QMT_STRATEGIES')
sys.path.insert(0, 'D:/QMT_STRATEGIES/Project_13_pool白盒化')
import numpy as np
import pandas as pd
from core.scoring.dimension6plus2 import ScoreCalculator6Plus2
from whitebox_pool import check_all_conditions

OUT='F:/backtest_workspace/results'; os.makedirs(OUT, exist_ok=True)
POOL_FILE='D:/QMT_POOL/selectedall.txt'
ASTOCK='E:/astock/daily/stock_daily.parquet'
THRESH=60.0; MAXHOLD=5; REBAL=10
def log(m): print(m, flush=True)

# ── 加载248池+astock(hfq) ──
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
df=df[(df['trade_date']>='2021-01-01')&(df['trade_date']<='2026-06-22')]
df=df.sort_values(['ts_code','trade_date']).reset_index(drop=True)
codes=sorted(df['ts_code'].unique())
data={c:df[df['ts_code']==c].set_index('trade_date')[['open','high','low','close','volume']].dropna() for c in codes}
all_dates=sorted(df['trade_date'].unique())
log(f'池={len(pool)} 股票={len(data)} 交易日={len(all_dates)} ({all_dates[0].date()}~{all_dates[-1].date()})')

# ── 大盘代理: 248池等权指数(向量化, 每日截面等权收益累计) ──
close_piv=pd.DataFrame({c:data[c]['close'] for c in codes})
daily_ret=close_piv.pct_change().mean(axis=1).fillna(0)
mkt_nav=(1+daily_ret).cumprod()
mkt_ma20=mkt_nav.rolling(20).mean(); mkt_ma60=mkt_nav.rolling(60).mean()
# 多头信号: mkt_nav > MA20 且 MA20 > MA60
bull=(mkt_nav>mkt_ma20)&(mkt_ma20>mkt_ma60)
bull=bull.fillna(False)
log(f'大盘2021-2026累计: {float(mkt_nav.iloc[-1]/mkt_nav.iloc[0]-1)*100:+.1f}% | 多头占比: {bull.mean()*100:.1f}%')

# ── 回测: 每10天rebal ──
scorer=ScoreCalculator6Plus2()
rebal_dates=all_dates[::REBAL]
navs={'full_ge60':[1.0],'timing_ge60':[1.0],'buyhold_full':[1.0],'buyhold_timing':[1.0]}
n_picks={'full_ge60':0,'timing_ge60':0}
bull_rebals=0; total_rebals=0

for i,d in enumerate(rebal_dates[:-1]):
    d_end=rebal_dates[i+1]
    total_rebals+=1
    is_bull=bool(bull.loc[d]) if d in bull.index else False
    if is_bull: bull_rebals+=1
    # 评分
    pool_dict={}; fwd_d={}
    for c in codes:
        s=data[c]; hist=s[s.index<=d]
        if len(hist)<60: continue
        fwd=s[(s.index>d)&(s.index<=d_end)]['close']
        if len(fwd)<1: continue
        pool_dict[c]=hist.tail(120); fwd_d[c]=float(fwd.iloc[-1])
    if len(pool_dict)<20:
        for k in navs: navs[k].append(navs[k][-1])
        continue
    try: res=scorer.score_pool(pool_dict)
    except:
        for k in navs: navs[k].append(navs[k][-1]); continue
    scores=res['score_total'].to_dict()
    # 选股: 505(C1-C7)+ge-60, top3等权
    picks=[]
    for c,sc in scores.items():
        if sc<THRESH: continue
        dfc=pool_dict[c]
        if len(dfc)<60: continue
        conds=check_all_conditions(dfc.tail(120))
        if all(conds.get(k) is True for k in ['C1','C2','C3','C4','C5','C6','C7']):
            picks.append((c,sc))
    picks.sort(key=lambda x:-x[1]); picks=picks[:3]
    # 组合收益
    if picks:
        rets=[fwd_d.get(c,0)/(float(pool_dict[c]['close'].iloc[-1]))-1 if c in fwd_d else 0 for c,_ in picks]
        port_ret=np.mean(rets) if rets else 0
    else: port_ret=0
    # full_ge60: 每次都选
    navs['full_ge60'].append(navs['full_ge60'][-1]*(1+port_ret))
    n_picks['full_ge60']+=len(picks)
    # timing_ge60: 多头选, 空头空仓
    navs['timing_ge60'].append(navs['timing_ge60'][-1]*(1+(port_ret if is_bull else 0)))
    if is_bull: n_picks['timing_ge60']+=len(picks)
    # buyhold_full: 248等权持有
    bh=np.mean([fwd_d.get(c,0)/(float(pool_dict[c]['close'].iloc[-1]))-1 if c in fwd_d else 0 for c in pool_dict])
    navs['buyhold_full'].append(navs['buyhold_full'][-1]*(1+bh))
    navs['buyhold_timing'].append(navs['buyhold_timing'][-1]*(1+(bh if is_bull else 0)))
    if i%15==0: log(f'  rebal {i+1}/{len(rebal_dates)-1} {d.date()} bull={is_bull} picks={len(picks)}')

# ── 指标 ──
log('=== 结果 ===')
results={'bull_ratio':round(bull_rebals/total_rebals*100,1),'n_rebal':total_rebals,'groups':{}}
for k in navs:
    nav=np.array(navs[k]); r=np.diff(nav)/nav[:-1]
    cum=nav[-1]/nav[0]-1; dd=(nav/np.maximum.accumulate(nav)-1).min()
    sh=r.mean()/r.std()*np.sqrt(52) if r.std()>0 else 0  # 10天周期年化~25
    results['groups'][k]={'cum_ret':round(cum*100,2),'dd':round(dd*100,2),'sharpe':round(float(sh),3),'trades':n_picks.get(k,0)}
    log(f'  {k:16s} 累计={cum*100:+.2f}% 回撤={dd*100:.2f}% 夏普={sh:.3f}')
t=results['groups']['timing_ge60'];f=results['groups']['full_ge60']
results['timing_vs_full']={'diff':round(t['cum_ret']-f['cum_ret'],2),'verdict':'择时提升' if t['cum_ret']>f['cum_ret'] else '择时未提升'}
log(f"\n择时 vs 全周期: {results['timing_vs_full']['verdict']} (收益差 {results['timing_vs_full']['diff']:+.2f}pp)")
with open(f'{OUT}/t011_timing.json','w',encoding='utf-8') as f2: json.dump(results,f2,ensure_ascii=False,indent=2)
log(f'-> {OUT}/t011_timing.json')
