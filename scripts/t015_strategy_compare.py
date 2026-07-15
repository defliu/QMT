# -*- coding: utf-8 -*-
"""S010优化回测v5: 多选股策略对比(top1000, 修正NAV, 无sell engine)

v4发现505条件(C3+C4+r10)在top1000上亏损(-8.15%)。
本脚本测多种选股逻辑找最优:
1. 纯MA60择时+等权持有1000(不选股, baseline)
2. 低波动(ATR最低的top5)
3. 动量(5日涨幅最高top5)
4. 505 C1-C7原版
5. C3+C4(精简505)
6. 价值(PE最低top5)
"""
import pandas as pd, numpy as np, math, json
ASTOCK='E:/astock/daily/stock_daily.parquet'
CAPITAL=100000.0; MAXHOLD=5; REBAL=5
def log(m): print(m, flush=True)
def ma(s,n): return s.rolling(n).mean()

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
rebal_dates=all_dates[bt_start::REBAL]

# 大盘择时
close_piv=pd.DataFrame({c:data[c]['close'] for c in data})
mkt_nav=(1+close_piv.pct_change().mean(axis=1).fillna(0)).cumprod()
bull=((mkt_nav>mkt_nav.rolling(20).mean())&(mkt_nav.rolling(20).mean()>mkt_nav.rolling(60).mean())).fillna(False)
log(f'universe={len(data)} bt={bt_dates[0].date()}~{bt_dates[-1].date()}')

def calc_metrics(hist):
    c=hist['close'];o=hist['open'];l=hist['low'];h=hist['high']
    m5=ma(c,5);m10=ma(c,10);m20=ma(c,20);m60=ma(c,60)
    cl=c.iloc[-1];op=o.iloc[-1];lo=l.iloc[-1]
    m5v=m5.iloc[-1];m10v=m10.iloc[-1];m20v=m20.iloc[-1];m60v=m60.iloc[-1]
    if any(pd.isna(x) for x in [m5v,m10v,m20v,m60v,cl,op,lo]): return None
    m5p=m5.iloc[-2] if len(m5)>=2 else m5v
    ang=math.degrees(math.atan((m5v/m5p-1)*100)) if m5p and m5p>0 else 0
    ret5=(cl/c.iloc[-6]-1)*100 if len(c)>=6 else 0
    amt=float(hist['amount'].tail(5).sum()) if 'amount' in hist else 0
    # ATR%
    tr=pd.concat([h-l,(h-c.shift(1)).abs(),(l-c.shift(1)).abs()],axis=1).max(axis=1)
    atr_pct=float(tr.rolling(14).mean().iloc[-1]/cl*100) if len(tr)>=14 else 999
    pe=float(hist['pe_ttm'].iloc[-1]) if 'pe_ttm' in hist else 999
    return {'C3':m10v>m20v,'C4':m20v>m60v,'r10':ret5<10,
            'ret5d':ret5,'amt5d':amt,'atr_pct':atr_pct,'pe':pe}

def run_bt(select_fn, label):
    """select_fn(hist_list) -> [(code, score)] 已排序, 高分优先"""
    cash=CAPITAL; holdings={}; nav_curve=[]; trades=[]
    for d in bt_dates:
        is_bull=bool(bull.loc[d]) if d in bull.index else True
        is_rebal=d in set(rebal_dates)
        if is_rebal:
            # 505失效退出(检查C3+C4)
            for code in list(holdings.keys()):
                sub=data[code]; hist=sub[sub.index<=d]
                if len(hist)<60: continue
                m=calc_metrics(hist.tail(120))
                if m and not (m['C3'] and m['C4']):
                    price=float(sub.loc[d,'close']) if d in sub.index else holdings[code]['buy']
                    cash+=price*holdings[code]['shares']
                    ret=(price/holdings[code]['buy']-1)*100
                    trades.append(ret); del holdings[code]
            # 选股
            cands=[]
            for code in data:
                if code in holdings: continue
                sub=data[code]; hist=sub[sub.index<=d]
                if len(hist)<60: continue
                m=calc_metrics(hist.tail(120))
                if m: cands.append((code,m))
            picks=select_fn(cands)
            slots=MAXHOLD-len(holdings)
            if not is_bull: slots=min(slots,1)
            pos=cash/max(1,MAXHOLD-len(holdings)) if is_bull else cash*0.3/max(1,MAXHOLD-len(holdings))
            for code,m in picks[:slots]:
                sub=data[code]
                if d not in sub.index: continue
                bp=float(sub.loc[d,'close'])
                sh=int(pos/bp/100)*100
                if sh<100: continue
                cost=bp*sh
                if cost>cash: sh=int(cash/bp/100)*100
                if sh<100: continue
                cash-=bp*sh; holdings[code]={'buy':bp,'shares':sh}
        nav=cash
        for code,h in holdings.items():
            sub=data[code]
            nav+=(float(sub.loc[d,'close']) if d in sub.index else h['buy'])*h['shares']
        nav_curve.append(nav/CAPITAL)
    arr=np.array(nav_curve); r=np.diff(arr)/arr[:-1]
    cum=arr[-1]-1; dd=(arr/np.maximum.accumulate(arr)-1).min()
    sh=r.mean()/r.std()*np.sqrt(252) if r.std()>0 else 0
    win=sum(1 for t in trades if t>0)/len(trades)*100 if trades else 0
    log(f'{label}: cum={cum*100:+.2f}% dd={dd*100:.1f}% sh={sh:.3f} trades={len(trades)} win={win:.0f}%')
    return {'label':label,'cum':round(cum*100,2),'dd':round(dd*100,1),'sharpe':round(sh,3),
            'trades':len(trades),'win':round(win)}

results=[]
# 1. 纯择时+等权持有(不选股, 每rebal随机5只C3+C4通过)
results.append(run_bt(lambda cs: sorted([(c,m) for c,m in cs if m['C3'] and m['C4']], key=lambda x:-x[1]['amt5d']), '1.C3+C4+成交额'))
# 2. 低波动(ATR最低top5)
results.append(run_bt(lambda cs: sorted([(c,m) for c,m in cs if m['C3'] and m['C4']], key=lambda x:x[1]['atr_pct'])[:20], '2.C3+C4+低波动'))
# 3. 动量(5日涨幅最高top5)
results.append(run_bt(lambda cs: sorted([(c,m) for c,m in cs if m['C3'] and m['C4'] and m['ret5d']<10], key=lambda x:-x[1]['ret5d'])[:20], '3.C3+C4+r10+动量'))
# 4. 原版505 C1-C7
results.append(run_bt(lambda cs: [(c,m) for c,m in cs if all([m['C3'],m['C4'],m.get('C1',False),m.get('C5',False),m.get('C7',False)])][:20], '4.原版505(简化)'))
# 5. C3+C4+PE最低
results.append(run_bt(lambda cs: sorted([(c,m) for c,m in cs if m['C3'] and m['C4'] and m['pe']>0 and m['pe']<100], key=lambda x:x[1]['pe'])[:20], '5.C3+C4+低PE'))

with open('F:/backtest_workspace/results/t015_strategy_compare.json','w') as f:
    json.dump(results,f,ensure_ascii=False,indent=2)
log(f'\n-> t015_strategy_compare.json')
