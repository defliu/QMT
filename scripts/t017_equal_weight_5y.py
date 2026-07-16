# -*- coding: utf-8 -*-
"""等权持仓5年回测(t017): C3+C4全部通过股等权持有 vs t016的5只版

逐日循环, 每日检查:
1. sell engine: 止损-8%/止盈+20%/移动止盈-10%(从最高点回撤)
2. 505条件失效退出(每rebal时检查持仓C3+C4)
3. 选股: C3+C4全部通过, 等权持有(不选top5)
4. MA20/60择时(BEAR限仓30%)
5. 交易成本: 买*1.0051 卖*0.9939
输出: F:/backtest_workspace/results/t017_equal_weight_5y.json
"""
import os, sys, json, math, warnings
warnings.filterwarnings('ignore')
import numpy as np, pandas as pd

ASTOCK='E:/astock/daily/stock_daily.parquet'
CAPITAL=100000.0; REBAL=5
STOP_LOSS=-0.08; TAKE_PROFIT=0.20; TRAILING=-0.10
BUY_F=1.0051; SELL_F=0.9939
def log(m): print(m, flush=True)

def check_c3_c4(hist):
    if len(hist)<60: return False,0,0
    c=hist['close']
    ma10=c.rolling(10).mean(); ma20=c.rolling(20).mean(); ma60=c.rolling(60).mean()
    m10=ma10.iloc[-1]; m20=ma20.iloc[-1]; m60=ma60.iloc[-1]
    if any(pd.isna(x) for x in [m10,m20,m60]): return False,0,0
    c3=m10>m20; c4=m20>m60
    cl=c.iloc[-1]
    ret5=(cl/c.iloc[-6]-1)*100 if len(c)>=6 else 0
    amt=float(hist['amount'].tail(5).sum()) if 'amount' in hist.columns else 0
    return c3 and c4, ret5, amt

df=pd.read_parquet(ASTOCK).reset_index()
df['trade_date']=pd.to_datetime(df['trade_date']); df['ts_code']=df['ts_code'].astype(str)
df=df.rename(columns={'vol':'volume'})
for col in ['open','high','low','close']: df[col]=df[col]*df['adj_factor']
df=df[(df['trade_date']>='2020-12-01')&(df['trade_date']<='2026-06-30')]
ref=df[(df['trade_date']>='2020-12-01')&(df['trade_date']<='2020-12-31')]
agg=ref.groupby('ts_code')['amount'].mean().reset_index().sort_values('amount',ascending=False).head(1000)
uni=set(agg['ts_code'].tolist())
df=df[df['ts_code'].isin(uni)].sort_values(['ts_code','trade_date']).reset_index(drop=True)
codes=sorted(df['ts_code'].unique())
data={c:df[df['ts_code']==c].set_index('trade_date')[['open','high','low','close','volume','amount']].dropna() for c in codes}
data={c:d for c,d in data.items() if len(d)>=60}
all_dates=sorted(df['trade_date'].unique())
bt_start=all_dates.index(pd.Timestamp('2021-07-01'))
bt_dates=all_dates[bt_start:]
rebal_set=set(all_dates[bt_start::REBAL])
log(f'universe={len(data)} bt={bt_dates[0].date()}~{bt_dates[-1].date()} ({len(bt_dates)}d) rebal={len(rebal_set)}')

close_piv=pd.DataFrame({c:data[c]['close'] for c in data})
mkt_nav=(1+close_piv.pct_change().mean(axis=1).fillna(0)).cumprod()
ma20_mkt=mkt_nav.rolling(20).mean(); ma60_mkt=mkt_nav.rolling(60).mean()
bull=((mkt_nav>ma20_mkt)&(ma20_mkt>ma60_mkt)).fillna(False)

cash=CAPITAL; holdings={}
nav_curve=[]; trades=[]; exit_stats={'止损':0,'止盈':0,'移动止盈':0,'505失效':0}
rebal_count=0; bull_days=0; maxhold_label=''

for d in bt_dates:
    is_bull=bool(bull.loc[d]) if d in bull.index else True
    if is_bull: bull_days+=1
    is_rebal=d in rebal_set

    for code in list(holdings.keys()):
        sub=data[code]
        if d not in sub.index: continue
        price=float(sub.loc[d,'close'])
        h=holdings[code]
        h['highest']=max(h['highest'],price)
        ret=(price-h['buy_price'])/h['buy_price']
        reason=None
        if ret<=STOP_LOSS: reason='止损'
        elif ret>=TAKE_PROFIT: reason='止盈'
        elif price<h['highest'] and (price-h['highest'])/h['highest']<=TRAILING: reason='移动止盈'
        if reason:
            sell_amt=price*SELL_F*h['shares']
            cash+=sell_amt
            final_ret=(price*SELL_F)/(h['buy_price']*BUY_F)-1
            trades.append({'code':code,'buy':str(h['buy_date'].date()),'sell':str(d.date()),
                           'ret':round(final_ret*100,2),'reason':reason})
            del holdings[code]; exit_stats[reason]+=1

    if is_rebal:
        rebal_count+=1
        for code in list(holdings.keys()):
            sub=data[code]; hist=sub[sub.index<=d]
            if len(hist)<60: continue
            ok,_,_=check_c3_c4(hist.tail(120))
            if not ok:
                price=float(sub.loc[d,'close']) if d in sub.index else holdings[code]['buy_price']
                sell_amt=price*SELL_F*holdings[code]['shares']
                cash+=sell_amt
                final_ret=(price*SELL_F)/(holdings[code]['buy_price']*BUY_F)-1
                trades.append({'code':code,'buy':str(holdings[code]['buy_date'].date()),
                               'sell':str(d.date()),'ret':round(final_ret*100,2),'reason':'505失效'})
                del holdings[code]; exit_stats['505失效']+=1

        cands=[]
        for code in data:
            if code in holdings: continue
            sub=data[code]; hist=sub[sub.index<=d]
            if len(hist)<60: continue
            ok,ret5,amt=check_c3_c4(hist.tail(120))
            if not ok or ret5>=10.0: continue
            cands.append((code,ret5,amt))

        n_new=len(cands)
        n_hold=len(holdings)
        if n_new>0:
            if is_bull:
                pos_target=cash/n_new
            else:
                max_new=max(1,int(n_hold*0.3))-n_hold
                if max_new<=0: max_new=1
                pos_target=cash*0.3/max_new
                cands=cands[:max_new]

            for code,ret5,amt in cands:
                sub=data[code]
                if d not in sub.index: continue
                buy_price=float(sub.loc[d,'close'])
                shares=int(pos_target/(buy_price*BUY_F)/100)*100
                if shares<100: continue
                cost=buy_price*BUY_F*shares
                if cost>cash: shares=int(cash/(buy_price*BUY_F)/100)*100
                if shares<100: continue
                cost=buy_price*BUY_F*shares; cash-=cost
                holdings[code]={'buy_price':buy_price,'buy_date':d,'highest':buy_price,'shares':shares}

        maxhold_label='等权%d' % len(holdings)

    nav=cash
    for code,h in holdings.items():
        sub=data[code]
        if d in sub.index: nav+=float(sub.loc[d,'close'])*h['shares']
        else: nav+=h['buy_price']*h['shares']
    nav_curve.append(nav/CAPITAL)
    if len(nav_curve)%250==0:
        log(f'  {d.date()} 持仓={len(holdings)} NAV={nav/CAPITAL:.4f}')

nav_arr=np.array(nav_curve); rets=np.diff(nav_arr)/nav_arr[:-1]
cum=nav_arr[-1]-1; dd=(nav_arr/np.maximum.accumulate(nav_arr)-1).min()
sh=rets.mean()/rets.std()*np.sqrt(252) if rets.std()>0 else 0
win=[t for t in trades if t['ret']>0]
win_rate=len(win)/len(trades)*100 if trades else 0

annual_returns={}
for yr in range(2021,2027):
    yr_dates=[i for i,d in enumerate(bt_dates) if d.year==yr]
    if len(yr_dates)<2: continue
    i0,i1=yr_dates[0],yr_dates[-1]
    yr_nav=[nav_arr[i] for i in yr_dates]
    yr_ret=yr_nav[-1]/yr_nav[0]-1
    annual_returns[str(yr)]=round(yr_ret*100,2)

results={
    'cum':round(cum*100,2),'dd':round(dd*100,1),'sharpe':round(float(sh),3),
    'trades':len(trades),'win':round(win_rate),
    'exit_stats':exit_stats,
    'bull':round(bull_days/len(bt_dates)*100,1),
    'final':round(float(nav_arr[-1]),2),
    'period':f'{bt_dates[0].date()}~{bt_dates[-1].date()}',
    'maxhold':maxhold_label,
    'annual_returns':annual_returns,
}
os.makedirs('F:/backtest_workspace/results',exist_ok=True)
with open('F:/backtest_workspace/results/t017_equal_weight_5y.json','w',encoding='utf-8') as f:
    json.dump(results,f,ensure_ascii=False,indent=2)
log(f'\n=== 等权持仓5年回测 ===')
log(f'累计: {cum*100:+.2f}%  回撤: {dd*100:.1f}%  夏普: {sh:.3f}')
log(f'交易: {len(trades)}笔  胜率: {win_rate:.0f}%  退出: {exit_stats}')
log(f'持仓: {maxhold_label}  多头: {bull_days/len(bt_dates)*100:.1f}%')
log(f'年度: {annual_returns}')
log(f'-> F:/backtest_workspace/results/t017_equal_weight_5y.json')
