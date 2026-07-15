# -*- coding: utf-8 -*-
"""S010回测v3: 成交额top1000 universe + 无sell engine(纯505失效退出+择时)

universe: astock近20日均成交额top1000活跃股(替代中证1000)
近1年(2025-07~2026-06), 每5天rebal, 505 C1-C7+B+C排序+505失效退出+MA60择时
无sell engine(止损/止盈/移动止盈), 纯505失效退出
输出: F:/backtest_workspace/results/t013_s010_v3.json
"""
import os, sys, json, math, warnings
warnings.filterwarnings('ignore')
import numpy as np, pandas as pd

ASTOCK='E:/astock/daily/stock_daily.parquet'
MAXHOLD=5; REBAL=5; CAPITAL=100000.0
def log(m): print(m, flush=True)

def check_505(hist):
    if len(hist)<60: return False,0,0
    c=hist['close'];o=hist['open'];l=hist['low']
    ma5=c.rolling(5).mean();ma10=c.rolling(10).mean();ma20=c.rolling(20).mean();ma60=c.rolling(60).mean()
    cl=c.iloc[-1];op=o.iloc[-1];lo=l.iloc[-1]
    m5=ma5.iloc[-1];m10=ma10.iloc[-1];m20=ma20.iloc[-1];m60=ma60.iloc[-1]
    if any(pd.isna(x) for x in [m5,m10,m20,m60,cl,op,lo]): return False,0,0
    c1=cl>m5;c2=m5>m10;c3=m10>m20;c4=m20>m60;c5=cl>op;c6=lo>=m5*0.98
    m5p=ma5.iloc[-2] if len(ma5)>=2 else m5
    ang=math.degrees(math.atan((m5/m5p-1)*100)) if m5p and m5p>0 else 0
    c7=ang>=45.0
    ok=c1 and c2 and c3 and c4 and c5 and c6 and c7
    ret5=(cl/c.iloc[-6]-1)*100 if len(c)>=6 else 0
    amt=float(hist['amount'].tail(5).sum()) if 'amount' in hist.columns else 0
    return ok,ret5,amt

# 加载astock + 取成交额top1000
log('加载astock...')
df=pd.read_parquet(ASTOCK).reset_index()
df['trade_date']=pd.to_datetime(df['trade_date']);df['ts_code']=df['ts_code'].astype(str)
df=df.rename(columns={'vol':'volume'})
for col in ['open','high','low','close']: df[col]=df[col]*df['adj_factor']
df=df[(df['trade_date']>='2024-10-01')&(df['trade_date']<='2026-06-22')]  # 多取前置数据(MA60)
# universe: 近20日均成交额top1000(用2025-06-30截面选)
log('选universe: 成交额top1000...')
ref=df[(df['trade_date']>='2025-06-01')&(df['trade_date']<='2025-06-30')]
agg=ref.groupby('ts_code')['amount'].mean().reset_index()
agg=agg.sort_values('amount',ascending=False).head(1000)
universe=agg['ts_code'].tolist()
log(f'universe: {len(universe)} 只(成交额top1000)')
df=df[df['ts_code'].isin(set(universe))].sort_values(['ts_code','trade_date']).reset_index(drop=True)
codes=sorted(df['ts_code'].unique())
data={c:df[df['ts_code']==c].set_index('trade_date')[['open','high','low','close','volume','amount']].dropna() for c in codes}
data={c:d for c,d in data.items() if len(d)>=60}
all_dates=sorted(df['trade_date'].unique())
log(f'有效股票={len(data)} 日期={all_dates[0].date()}~{all_dates[-1].date()}')

# 大盘代理+择时
close_piv=pd.DataFrame({c:data[c]['close'] for c in data})
mkt_nav=(1+close_piv.pct_change().mean(axis=1).fillna(0)).cumprod()
ma20_mkt=mkt_nav.rolling(20).mean(); ma60_mkt=mkt_nav.rolling(60).mean()
bull=((mkt_nav>ma20_mkt)&(ma20_mkt>ma60_mkt)).fillna(False)
start_idx=max(0,all_dates.index(pd.Timestamp('2025-07-01')))
bt_dates=all_dates[start_idx:]
rebal_set=set(all_dates[start_idx::REBAL])
log(f'回测: {bt_dates[0].date()}~{bt_dates[-1].date()} ({len(bt_dates)}日, {len(rebal_set)} rebal)')

# 回测(无sell engine, 纯505失效退出+择时)
nav=1.0; nav_curve=[1.0]; holdings={}; trades=[]; exit_505=0; bull_count=0
for d in bt_dates:
    is_bull=bool(bull.loc[d]) if d in bull.index else True
    if is_bull: bull_count+=1
    if d not in rebal_set:
        # 非rebal日: 只记NAV
        v=nav
        nav_curve.append(v)
        continue
    # rebal日: 505失效退出 + 选股买入
    # 1. 505失效退出
    for code in list(holdings.keys()):
        sub=data[code]; hist=sub[sub.index<=d]
        if len(hist)<60: continue
        ok,_,_=check_505(hist.tail(120))
        if not ok:
            price=float(sub.loc[d,'close']) if d in sub.index else holdings[code]
            ret=(price/holdings[code]-1)*100
            trades.append({'code':code,'ret':round(ret,2),'reason':'505失效'})
            nav*=(1+ret/100/MAXHOLD)
            del holdings[code]; exit_505+=1
    # 2. 选股
    candidates=[]
    for code in data:
        if code in holdings: continue
        sub=data[code]; hist=sub[sub.index<=d]
        if len(hist)<60: continue
        ok,ret5,amt=check_505(hist.tail(120))
        if not ok or ret5>=20.0: continue
        candidates.append((code,ret5,amt))
    candidates.sort(key=lambda x:-x[2])
    slots=MAXHOLD-len(holdings)
    if not is_bull: slots=min(slots,1)
    for code,ret5,amt in candidates[:slots]:
        sub=data[code]
        if d not in sub.index: continue
        buy_p=float(sub.loc[d,'close'])
        holdings[code]=buy_p
        trades.append({'code':code,'ret':0,'reason':'505持有'})
    # 3. NAV(持仓市值)
    port_val=0
    for code,buy_p in holdings.items():
        sub=data[code]
        cur=float(sub.loc[d,'close']) if d in sub.index else buy_p
        port_val+=cur/buy_p  # 等权, 每只占1/MAXHOLD
    nav_curve.append(nav*(1+(port_val-len(holdings))/MAXHOLD))  # 简化NAV
    if len(nav_curve)%20==0:
        log(f'  {d.date()} 持仓={len(holdings)} 退出505={exit_505} NAV={nav_curve[-1]:.4f}')

# 指标
nav_arr=np.array(nav_curve); rets=np.diff(nav_arr)/nav_arr[:-1]
cum=nav_arr[-1]-1; dd=(nav_arr/np.maximum.accumulate(nav_arr)-1).min()
sh=rets.mean()/rets.std()*np.sqrt(52) if rets.std()>0 else 0
log(f'\n=== S010 v3 top1000 无sell engine ===')
log(f'累计收益: {cum*100:+.2f}%')
log(f'最大回撤: {dd*100:.2f}%')
log(f'夏普: {sh:.3f}')
log(f'交易笔数: {len(trades)} (505失效退出: {exit_505})')
log(f'多头占比: {bull_count/len(bt_dates)*100:.1f}%')
results={'cum_return_pct':round(cum*100,2),'max_drawdown_pct':round(dd*100,2),
         'sharpe':round(float(sh),3),'n_trades':len(trades),'exit_505':exit_505,
         'bull_ratio':round(bull_count/len(bt_dates)*100,1),'universe':'top1000成交额',
         'sell_engine':'无(纯505失效退出)','period':f'{bt_dates[0].date()}~{bt_dates[-1].date()}'}
with open('F:/backtest_workspace/results/t013_s010_v3.json','w',encoding='utf-8') as f:
    json.dump(results,f,ensure_ascii=False,indent=2)
log(f'-> F:/backtest_workspace/results/t013_s010_v3.json')
