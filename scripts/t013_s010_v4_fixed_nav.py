# -*- coding: utf-8 -*-
"""S010优化回测v4: 修正NAV计算(top1000, C3+C4+r10, 无sell engine)

修正NAV: 用真实资金+持仓市值(非简化连乘)
基于归因结论: C3(MA10>MA20)+C4(MA20>MA60)有效正, r10(5日涨幅<10%)防追高
"""
import pandas as pd, numpy as np, math, json
ASTOCK='E:/astock/daily/stock_daily.parquet'
MAXHOLD=5; CAPITAL=100000.0
def log(m): print(m, flush=True)
def ma(s,n): return s.rolling(n).mean()
def get_metrics(hist):
    c=hist['close'];o=hist['open'];l=hist['low']
    m5=ma(c,5);m10=ma(c,10);m20=ma(c,20);m60=ma(c,60)
    cl=c.iloc[-1];op=o.iloc[-1];lo=l.iloc[-1]
    m5v=m5.iloc[-1];m10v=m10.iloc[-1];m20v=m20.iloc[-1];m60v=m60.iloc[-1]
    if any(pd.isna(x) for x in [m5v,m10v,m20v,m60v,cl,op,lo]): return None
    m5p=m5.iloc[-2] if len(m5)>=2 else m5v
    ang=math.degrees(math.atan((m5v/m5p-1)*100)) if m5p and m5p>0 else 0
    ret5=(cl/c.iloc[-6]-1)*100 if len(c)>=6 else 0
    amt=float(hist['amount'].tail(5).sum()) if 'amount' in hist else 0
    return {'C3':m10v>m20v,'C4':m20v>m60v,'r10':ret5<10,
            'ret5d':ret5,'amt5d':amt,'angle':ang}

# 加载
df=pd.read_parquet(ASTOCK).reset_index()
df['trade_date']=pd.to_datetime(df['trade_date']);df['ts_code']=df['ts_code'].astype(str)
df=df.rename(columns={'vol':'volume'})
for col in ['open','high','low','close']: df[col]=df[col]*df['adj_factor']
df=df[(df['trade_date']>='2024-10-01')&(df['trade_date']<='2026-06-22')]
ref=df[(df['trade_date']>='2025-06-01')&(df['trade_date']<='2025-06-30')]
agg=ref.groupby('ts_code')['amount'].mean().reset_index().sort_values('amount',ascending=False).head(1000)
uni=set(agg['ts_code'].tolist())
df=df[df['ts_code'].isin(uni)].sort_values(['ts_code','trade_date']).reset_index(drop=True)
codes=sorted(df['ts_code'].unique())
data={c:df[df['ts_code']==c].set_index('trade_date') for c in codes}
data={c:d for c,d in data.items() if len(d)>=60}
all_dates=sorted(df['trade_date'].unique())
bt_start=all_dates.index(pd.Timestamp('2025-07-01'))
bt_dates=all_dates[bt_start:]
rebal_dates=all_dates[bt_start::5]

# 大盘择时
close_piv=pd.DataFrame({c:data[c]['close'] for c in data})
mkt_nav=(1+close_piv.pct_change().mean(axis=1).fillna(0)).cumprod()
bull=((mkt_nav>mkt_nav.rolling(20).mean())&(mkt_nav.rolling(20).mean()>mkt_nav.rolling(60).mean())).fillna(False)
log(f'universe={len(data)} bt={bt_dates[0].date()}~{bt_dates[-1].date()}')

# 逐日回测(修正NAV: 真实资金+持仓市值)
cash=CAPITAL; holdings={}  # {code:{buy_price,highest,shares}}
nav_curve=[]; trades=[]; exit505=0; bull_days=0
CONDS=['C3','C4','r10']

for d in bt_dates:
    is_bull=bool(bull.loc[d]) if d in bull.index else True
    if is_bull: bull_days+=1
    is_rebal=d in set(rebal_dates)
    if is_rebal:
        # 505失效退出
        for code in list(holdings.keys()):
            sub=data[code]; hist=sub[sub.index<=d]
            if len(hist)<60: continue
            m=get_metrics(hist.tail(120))
            if m is None: continue
            ok=all(m.get(c,False) for c in CONDS)
            if not ok:
                price=float(sub.loc[d,'close']) if d in sub.index else holdings[code]['buy_price']
                sell_val=price*holdings[code]['shares']
                cash+=sell_val
                ret=(price/holdings[code]['buy_price']-1)*100
                trades.append({'code':code,'ret':round(ret,2),'reason':'505失效'})
                del holdings[code]; exit505+=1
        # 选股
        cands=[]
        for code in data:
            if code in holdings: continue
            sub=data[code]; hist=sub[sub.index<=d]
            if len(hist)<60: continue
            m=get_metrics(hist.tail(120))
            if m is None: continue
            ok=all(m.get(c,False) for c in CONDS)
            if not ok: continue
            cands.append((code,m['amt5d']))
        cands.sort(key=lambda x:-x[1])
        slots=MAXHOLD-len(holdings)
        if not is_bull: slots=min(slots,1)
        pos_target=cash/max(1,MAXHOLD-len(holdings)) if is_bull else cash*0.3/max(1,MAXHOLD-len(holdings))
        for code,amt in cands[:slots]:
            sub=data[code]
            if d not in sub.index: continue
            buy_p=float(sub.loc[d,'close'])
            shares=int(pos_target/buy_p/100)*100
            if shares<100: continue
            cost=buy_p*shares
            if cost>cash: shares=int(cash/buy_p/100)*100
            if shares<100: continue
            cost=buy_p*shares; cash-=cost
            holdings[code]={'buy_price':buy_p,'shares':shares}
    # NAV(真实持仓市值)
    nav=cash
    for code,h in holdings.items():
        sub=data[code]
        if d in sub.index: nav+=float(sub.loc[d,'close'])*h['shares']
        else: nav+=h['buy_price']*h['shares']
    nav_curve.append(nav/CAPITAL)
    if len(nav_curve)%50==0:
        log(f'  {d.date()} 持仓={len(holdings)} NAV={nav/CAPITAL:.4f}')

# 指标
arr=np.array(nav_curve); r=np.diff(arr)/arr[:-1]
cum=arr[-1]-1; dd=(arr/np.maximum.accumulate(arr)-1).min()
sh=r.mean()/r.std()*np.sqrt(252) if r.std()>0 else 0
win=sum(1 for t in trades if t['ret']>0)/len(trades)*100 if trades else 0
log(f'\n=== S010 v4 修正NAV(C3+C4+r10, top1000, 无sell engine) ===')
log(f'累计收益: {cum*100:+.2f}%')
log(f'最大回撤: {dd*100:.2f}%')
log(f'夏普: {sh:.3f}')
log(f'交易笔数: {len(trades)} (505失效退出: {exit505})')
log(f'胜率: {win:.1f}%')
log(f'多头占比: {bull_days/len(bt_dates)*100:.1f}%')
results={'cum':round(cum*100,2),'dd':round(dd*100,2),'sharpe':round(sh,3),
         'trades':len(trades),'exit505':exit505,'win':round(win,1),
         'bull':round(bull_days/len(bt_dates)*100,1),
         'conds':'C3+C4+r10','universe':'top1000','sell_engine':'无'}
with open('F:/backtest_workspace/results/t013_s010_v4.json','w') as f:
    json.dump(results,f,ensure_ascii=False,indent=2)
log(f'-> t013_s010_v4.json')
