# -*- coding: utf-8 -*-
"""S010优化v6: 基于5年全因子归因最优组合回测

5年归因发现:
- atr_lt6(ATR%<6%低波动) spread+0.313% pass_rate90% 最强
- turnover_1to8(换手率1-8%) spread+0.158% pass_rate58% 第二
- 均线/量价/动量/形态 全中性或负

3组对比:
1. atr_lt6 + turnover_1to8 + 成交额排序top5
2. atr_lt6 + 成交额排序top5(纯低波动)
3. atr_lt6 + turnover_1to8 + 低ATR排序(波动率最低top5)
"""
import pandas as pd, numpy as np, math, json
ASTOCK='E:/astock/daily/stock_daily.parquet'
MAXHOLD=5; CAPITAL=100000.0; REBAL=5
STOP_LOSS=-0.08; TAKE_PROFIT=0.20; TRAILING=-0.10
BUY_F=1.0051; SELL_F=0.9939

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
bt_dates=all_dates[bt_start:]
rebal_dates=all_dates[bt_start::REBAL]
close_piv=pd.DataFrame({c:data[c]['close'] for c in data})
mkt_nav=(1+close_piv.pct_change().mean(axis=1).fillna(0)).cumprod()
bull=((mkt_nav>mkt_nav.rolling(20).mean())&(mkt_nav.rolling(20).mean()>mkt_nav.rolling(60).mean())).fillna(False)
print(f'universe={len(data)} bt={bt_dates[0].date()}~{bt_dates[-1].date()}', flush=True)

def ma(s,n): return s.rolling(n).mean()
def get_factors(hist):
    c=hist['close'];o=hist['open'];l=hist['low'];h=hist['high'];v=hist['volume']
    if len(c)<60: return None
    cl=c.iloc[-1]
    # ATR%
    tr=pd.concat([h-l,(h-c.shift(1)).abs(),(l-c.shift(1)).abs()],axis=1).max(axis=1)
    atr_pct=float(tr.rolling(14).mean().iloc[-1]/cl*100) if len(tr)>=14 else 999
    # 换手率
    tr_rate=float(hist['turnover_rate'].iloc[-1]) if 'turnover_rate' in hist.columns else 0
    # 成交额
    amt=float(hist['amount'].tail(5).sum()) if 'amount' in hist else 0
    return {'atr_pct':atr_pct,'turnover':tr_rate,'amt5d':amt,'close':cl}

def run_bt(conds_fn, sort_fn, label):
    cash=CAPITAL; holdings={}; nav_curve=[]; trades=[]
    exit_stats={'止损':0,'止盈':0,'移动止盈':0,'条件失效':0}; bull_days=0
    for d in bt_dates:
        is_bull=bool(bull.loc[d]) if d in bull.index else True
        if is_bull: bull_days+=1
        is_rebal=d in set(rebal_dates)
        # sell engine
        for code in list(holdings.keys()):
            sub=data[code]
            if d not in sub.index: continue
            price=float(sub.loc[d,'close']); h=holdings[code]
            h['highest']=max(h['highest'],price); ret=(price-h['buy'])/h['buy']
            reason=None
            if ret<=STOP_LOSS: reason='止损'
            elif ret>=TAKE_PROFIT: reason='止盈'
            elif price<h['highest'] and (price-h['highest'])/h['highest']<=TRAILING: reason='移动止盈'
            if reason:
                cash+=price*SELL_F*h['shares']
                fr=(price*SELL_F)/(h['buy']*BUY_F)-1
                trades.append({'ret':round(fr*100,2),'reason':reason})
                del holdings[code]; exit_stats[reason]+=1
        if is_rebal:
            # 条件失效退出
            for code in list(holdings.keys()):
                sub=data[code]; hist=sub[sub.index<=d]
                if len(hist)<60: continue
                m=get_factors(hist.tail(120))
                if m and not conds_fn(m):
                    price=float(sub.loc[d,'close']) if d in sub.index else holdings[code]['buy']
                    cash+=price*SELL_F*holdings[code]['shares']
                    fr=(price*SELL_F)/(holdings[code]['buy']*BUY_F)-1
                    trades.append({'ret':round(fr*100,2),'reason':'条件失效'})
                    del holdings[code]; exit_stats['条件失效']+=1
            # 选股
            cands=[]
            for code in data:
                if code in holdings: continue
                sub=data[code]; hist=sub[sub.index<=d]
                if len(hist)<60: continue
                m=get_factors(hist.tail(120))
                if m and conds_fn(m): cands.append((code,sort_fn(m)))
            cands.sort(key=lambda x:-x[1])
            slots=MAXHOLD-len(holdings)
            if not is_bull: slots=min(slots,1)
            pos=cash/max(1,MAXHOLD-len(holdings)) if is_bull else cash*0.3/max(1,MAXHOLD-len(holdings))
            for code,_ in cands[:slots]:
                sub=data[code]
                if d not in sub.index: continue
                bp=float(sub.loc[d,'close'])
                sh=int(pos/(bp*BUY_F)/100)*100
                if sh<100: continue
                cost=bp*BUY_F*sh
                if cost>cash: sh=int(cash/(bp*BUY_F)/100)*100
                if sh<100: continue
                cash-=bp*BUY_F*sh; holdings[code]={'buy':bp,'highest':bp,'shares':sh}
        nav=cash
        for code,h in holdings.items():
            sub=data[code]
            nav+=(float(sub.loc[d,'close']) if d in sub.index else h['buy'])*h['shares']
        nav_curve.append(nav/CAPITAL)
    arr=np.array(nav_curve); r=np.diff(arr)/arr[:-1]
    cum=arr[-1]-1; dd=(arr/np.maximum.accumulate(arr)-1).min()
    sh=r.mean()/r.std()*np.sqrt(252) if r.std()>0 else 0
    win=sum(1 for t in trades if t['ret']>0)/len(trades)*100 if trades else 0
    # 年度
    years={}; prev=1.0
    for i,d in enumerate(bt_dates):
        y=d.year
        if y not in years: years[y]=[nav_curve[i]]
        else: years[y].append(nav_curve[i])
    annual={}
    for y in sorted(years):
        yr=years[y][-1]/prev-1; annual[y]=round(yr*100,1); prev=years[y][-1]
    print(f'{label}: cum={cum*100:+.2f}% dd={dd*100:.1f}% sh={sh:.3f} trades={len(trades)} win={win:.0f}% bull={bull_days/len(bt_dates)*100:.0f}%', flush=True)
    print(f'  退出: {exit_stats}', flush=True)
    print(f'  年度: {annual}', flush=True)
    return {'label':label,'cum':round(cum*100,2),'dd':round(dd*100,1),'sharpe':round(sh,3),
            'trades':len(trades),'win':round(win),'exit':exit_stats,'annual':annual}

# 1. atr_lt6 + turnover_1to8 + 成交额排序
r1=run_bt(lambda m: m['atr_pct']<6.0 and 1.0<=m['turnover']<=8.0,
          lambda m: m['amt5d'], '1.atr<6%+换手1-8%+成交额排序')
# 2. 纯低波动 atr_lt6 + 成交额排序
r2=run_bt(lambda m: m['atr_pct']<6.0,
          lambda m: m['amt5d'], '2.纯atr<6%+成交额排序')
# 3. atr_lt6 + turnover_1to8 + 低ATR排序(波动率最低优先)
r3=run_bt(lambda m: m['atr_pct']<6.0 and 1.0<=m['turnover']<=8.0,
          lambda m: -m['atr_pct'], '3.atr<6%+换手1-8%+低波动排序')
# 4. 基线: C3+C4(原均线, 5年归因中性)
r4=run_bt(lambda m: True,  # 不加条件(全买成交额top5, 纯择时基准)
          lambda m: m['amt5d'], '4.无选股+成交额排序(基线)')

with open('F:/backtest_workspace/results/t019_optimal_5y.json','w') as f:
    json.dump([r1,r2,r3,r4],f,ensure_ascii=False,indent=2)
print(f'\n-> t019_optimal_5y.json', flush=True)
