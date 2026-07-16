# -*- coding: utf-8 -*-
"""全因子5年归因: 30+候选因子(均线/量价/动量/波动/形态/RSI/MACD/换手/PE)
top1000, 2021-07~2026-06, 每5天rebal, 算spread(通过组-未通过组5d收益)
"""
import pandas as pd, numpy as np, math, json
ASTOCK='E:/astock/daily/stock_daily.parquet'
df=pd.read_parquet(ASTOCK).reset_index()
df['trade_date']=pd.to_datetime(df['trade_date']); df['ts_code']=df['ts_code'].astype(str)
df=df.rename(columns={'vol':'volume'})
for col in ['open','high','low','close']: df[col]=df[col]*df['adj_factor']
df=df[(df['trade_date']>='2020-06-01')&(df['trade_date']<='2026-06-22')]
ref=df[(df['trade_date']>='2020-12-01')&(df['trade_date']<='2020-12-31')]
agg=ref.groupby('ts_code')['amount'].mean().reset_index().sort_values('amount',ascending=False).head(1000)
uni=set(agg['ts_code'].tolist())
df=df[df['ts_code'].isin(uni)].sort_values(['ts_code','trade_date']).reset_index(drop=True)
codes=sorted(df['ts_code'].unique())
data={c:df[df['ts_code']==c].set_index('trade_date') for c in codes}
data={c:d for c,d in data.items() if len(d)>=60}
all_dates=sorted(df['trade_date'].unique())
bt_start=all_dates.index(pd.Timestamp('2021-07-01'))
bt_dates=all_dates[bt_start::5]

def ma(s,n): return s.rolling(n).mean()

def calc_factors(hist):
    c=hist['close'];o=hist['open'];l=hist['low'];h=hist['high'];v=hist['volume']
    if len(c)<60: return None
    m5=ma(c,5);m10=ma(c,10);m20=ma(c,20);m60=ma(c,60)
    cl=c.iloc[-1];op=o.iloc[-1];lo=l.iloc[-1];hi=h.iloc[-1]
    m5v=m5.iloc[-1];m10v=m10.iloc[-1];m20v=m20.iloc[-1];m60v=m60.iloc[-1]
    if any(pd.isna(x) for x in [m5v,m10v,m20v,m60v,cl,op,lo,hi]): return None
    f={}
    # 均线
    f['ma_bull']=m5v>m10v and m10v>m20v
    f['ma10_gt_ma20']=m10v>m20v
    f['ma20_gt_ma60']=m20v>m60v
    f['close_gt_ma20']=cl>m20v
    f['close_gt_ma60']=cl>m60v
    # 量价
    vol_ma5=v.rolling(5).mean()
    vol_ratio=float(v.iloc[-1]/vol_ma5.iloc[-1]) if vol_ma5.iloc[-1]>0 else 1.0
    f['vol_ratio_gt1']=vol_ratio>1.0
    f['vol_ratio_1to2']=1.0<=vol_ratio<=2.0
    vol_ma20=v.rolling(20).mean()
    vol_trend=float(vol_ma5.iloc[-1]/vol_ma20.iloc[-1]) if vol_ma20.iloc[-1]>0 else 1.0
    f['vol_trend_up']=vol_trend>1.0
    ret1=float(c.iloc[-1]/c.iloc[-2]-1) if len(c)>=2 else 0
    f['up_with_vol']=ret1>0 and vol_ratio>1.0
    f['up_with_vol_trend']=ret1>0 and vol_trend>1.0
    # 动量
    ret5=(cl/c.iloc[-6]-1)*100 if len(c)>=6 else 0
    ret10=(cl/c.iloc[-11]-1)*100 if len(c)>=11 else 0
    ret20=(cl/c.iloc[-21]-1)*100 if len(c)>=21 else 0
    f['ret5_0to10']=0<ret5<=10
    f['ret5_0to15']=0<ret5<=15
    f['ret10_pos']=ret10>0
    f['ret20_0to20']=0<ret20<=20
    # 波动率
    tr=pd.concat([h-l,(h-c.shift(1)).abs(),(l-c.shift(1)).abs()],axis=1).max(axis=1)
    atr_pct=float(tr.rolling(14).mean().iloc[-1]/cl*100) if len(tr)>=14 else 999
    f['atr_lt5']=atr_pct<5.0
    f['atr_lt6']=atr_pct<6.0
    f['atr_3to7']=3.0<=atr_pct<=7.0
    daily_ret=c.pct_change().tail(20)
    vol20=float(daily_ret.std()*100) if len(daily_ret)>=10 else 999
    f['vol20_lt3']=vol20<3.0
    # 形态
    upper_shadow=(hi-max(cl,op))/(hi-lo+0.001) if hi>lo else 0
    f['short_upper_shadow']=upper_shadow<0.3
    body=abs(cl-op)/(op+0.001)
    f['solid_bullish']=cl>op and body>0.005
    high20=h.rolling(20).max().iloc[-1] if len(h)>=20 else hi
    f['near_high20']=cl>=high20*0.97
    high60=h.rolling(60).max().iloc[-1] if len(h)>=60 else hi
    f['near_high60']=cl>=high60*0.95
    # RSI
    delta=c.diff()
    gain=delta.where(delta>0,0).rolling(14).mean()
    loss=(-delta.where(delta<0,0)).rolling(14).mean()
    rs=float(gain.iloc[-1]/loss.iloc[-1]) if loss.iloc[-1]>0 else 999
    rsi=100-100/(1+rs) if rs<999 else 100
    f['rsi_40to70']=40<=rsi<=70
    f['rsi_50to70']=50<=rsi<=70
    # MACD
    ema12=c.ewm(span=12).mean(); ema26=c.ewm(span=26).mean()
    dif=ema12-ema26; dea=dif.ewm(span=9).mean()
    f['macd_dif_gt_dea']=float(dif.iloc[-1])>float(dea.iloc[-1])
    f['macd_dif_pos']=float(dif.iloc[-1])>0
    # 换手率
    if 'turnover_rate' in hist.columns:
        tr_rate=float(hist['turnover_rate'].iloc[-1])
        f['turnover_1to8']=1.0<=tr_rate<=8.0
        f['turnover_2to10']=2.0<=tr_rate<=10.0
    else:
        f['turnover_1to8']=False; f['turnover_2to10']=False
    # PE
    if 'pe_ttm' in hist.columns:
        pe=float(hist['pe_ttm'].iloc[-1])
        f['pe_10to60']=10<=pe<=60 if pe>0 else False
    else:
        f['pe_10to60']=False
    f['_fwd']=0; f['_amt']=float(hist['amount'].tail(5).sum()) if 'amount' in hist else 0
    return f

factor_names=[k for k in calc_factors(data[codes[0]].tail(120)) if not k.startswith('_')]
spreads={f:[] for f in factor_names}; passrates={f:[] for f in factor_names}
print(f'因子数: {len(factor_names)} universe={len(data)} bt={bt_dates[0].date()}~{bt_dates[-1].date()}', flush=True)

for i,d in enumerate(bt_dates[:-1]):
    d_end=bt_dates[i+1]
    pairs=[]
    for code in data:
        sub=data[code]; hist=sub[sub.index<=d]
        if len(hist)<60: continue
        fwd=sub[(sub.index>d)&(sub.index<=d_end)]['close']
        if len(fwd)<1: continue
        r=calc_factors(hist.tail(120))
        if r is None: continue
        r['_fwd']=float(fwd.iloc[-1]/hist['close'].iloc[-1]-1); pairs.append(r)
    if len(pairs)<50: continue
    for fn in factor_names:
        pr=[p['_fwd'] for p in pairs if p.get(fn,False)]
        fr=[p['_fwd'] for p in pairs if not p.get(fn,False)]
        if pr and fr:
            spreads[fn].append(np.mean(pr)-np.mean(fr))
            passrates[fn].append(len(pr)/len(pairs))
    if i%30==0: print(f'rebal {i+1}/{len(bt_dates)-1} {d.date()} n={len(pairs)}',flush=True)

print('\n=== 全因子5年归因(top1000, 2021-07~2026-06) ===',flush=True)
print(f"{'因子':<25}{'spread%':<12}{'pass_rate':<12}{'判定'}",flush=True)
results={}
for fn in factor_names:
    sps=spreads[fn]; prs=passrates[fn]
    if not sps: continue
    ms=np.mean(sps)*100; pr=np.mean(prs)
    v='有效正' if ms>0.15 else ('负' if ms<-0.15 else '中性')
    results[fn]={'spread':round(ms,3),'pass_rate':round(pr,3),'verdict':v}
    print(f'{fn:<25}{ms:>+.3f}%      {pr:.3f}      {v}',flush=True)

positive=[(fn,results[fn]['spread'],results[fn]['pass_rate']) for fn in results if results[fn]['verdict']=='有效正']
positive.sort(key=lambda x:-x[1])
print(f'\n=== 有效正因子(排序) ===',flush=True)
for fn,sp,pr in positive:
    print(f'  {fn:<25} spread={sp:+.3f}% pass_rate={pr:.3f}',flush=True)

with open('F:/backtest_workspace/results/t018_factor_screen_5y.json','w') as f:
    json.dump(results,f,ensure_ascii=False,indent=2)
print(f'\n-> t018_factor_screen_5y.json',flush=True)
