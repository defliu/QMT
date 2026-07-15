# -*- coding: utf-8 -*-
"""S010优化回测: 4个组合参数搜索, top1000, 无sell engine

基于top1000归因结论:
- C3(MA10>MA20) +0.366% 有效正
- C4(MA20>MA60) +0.538% 有效正(最强)
- C1/C5/C6 负或中性 -> 可去掉
- C7角度 负 -> 去掉
- r10(5日涨幅<10%) 中性偏正 -> 保留防追高

4组组合:
1. 原版505 C1-C7(基线)
2. 精简C3+C4(只留有效正的)
3. C3+C4+r10(加防追高)
4. C3+C4+成交额排序top3(集中持仓)
"""
import pandas as pd, numpy as np, math, json
ASTOCK='E:/astock/daily/stock_daily.parquet'
MAXHOLD=5; REBAL=5
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
    return {'C1':cl>m5v,'C2':m5v>m10v,'C3':m10v>m20v,'C4':m20v>m60v,
            'C5':cl>op,'C6':lo>=m5v*0.98,'C7':ang>=45,
            'r10':ret5<10,'r20':ret5<20,
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
rebal_set=set(all_dates[bt_start::REBAL])

# 大盘择时
close_piv=pd.DataFrame({c:data[c]['close'] for c in data})
mkt_nav=(1+close_piv.pct_change().mean(axis=1).fillna(0)).cumprod()
bull=((mkt_nav>mkt_nav.rolling(20).mean())&(mkt_nav.rolling(20).mean()>mkt_nav.rolling(60).mean())).fillna(False)
log(f'universe={len(data)} bt={bt_dates[0].date()}~{bt_dates[-1].date()}')

def run_backtest(conds, sort_key, max_hold, rebal_days, label):
    """跑一组参数"""
    rebal_dates=all_dates[bt_start::rebal_days]
    nav=1.0; curve=[1.0]; holdings={}; trades=[]; exit505=0; bull_c=0
    for d in rebal_dates[:-1]:
        d_end=rebal_dates[rebal_dates.index(d)+1]
        is_bull=bool(bull.loc[d]) if d in bull.index else True
        if is_bull: bull_c+=1
        # 505失效退出
        for code in list(holdings.keys()):
            sub=data[code]; hist=sub[sub.index<=d]
            if len(hist)<60: continue
            m=get_metrics(hist.tail(120))
            if m is None: continue
            ok=all(m.get(c,False) for c in conds)
            if not ok:
                price=float(sub.loc[d,'close']) if d in sub.index else holdings[code]
                ret=(price/holdings[code]-1)*100
                trades.append(ret); nav*=(1+ret/100/max_hold)
                del holdings[code]; exit505+=1
        # 选股
        cands=[]
        for code in data:
            if code in holdings: continue
            sub=data[code]; hist=sub[sub.index<=d]
            if len(hist)<60: continue
            m=get_metrics(hist.tail(120))
            if m is None: continue
            ok=all(m.get(c,False) for c in conds)
            if not ok: continue
            cands.append((code,m.get(sort_key,0),m.get('amt5d',0)))
        cands.sort(key=lambda x:-x[2])  # 成交额排序
        slots=max_hold-len(holdings)
        if not is_bull: slots=min(slots,1)
        for code,_,_ in cands[:slots]:
            sub=data[code]
            if d not in sub.index: continue
            holdings[code]=float(sub.loc[d,'close'])
        # NAV
        pv=0
        for code,bp in holdings.items():
            sub=data[code]
            cur=float(sub.loc[d,'close']) if d in sub.index else bp
            pv+=cur/bp
        nav*=(1+(pv-len(holdings))/max_hold)
        curve.append(nav)
    arr=np.array(curve); r=np.diff(arr)/arr[:-1]
    cum=arr[-1]-1; dd=(arr/np.maximum.accumulate(arr)-1).min()
    sh=r.mean()/r.std()*np.sqrt(52) if r.std()>0 else 0
    win=sum(1 for t in trades if t>0)/len(trades)*100 if trades else 0
    log(f'{label}: cum={cum*100:+.2f}% dd={dd*100:.1f}% sh={sh:.3f} trades={len(trades)} exit505={exit505} win={win:.0f}% bull={bull_c/len(rebal_dates)*100:.0f}%')
    return {'label':label,'cum':round(cum*100,2),'dd':round(dd*100,1),'sharpe':round(sh,3),
            'trades':len(trades),'exit505':exit505,'win':round(win),'bull':round(bull_c/len(rebal_dates)*100)}

# 4组组合
results=[]
# 1. 原版505 C1-C7
results.append(run_backtest(['C1','C2','C3','C4','C5','C6','C7'],'amt5d',5,5,'1.原版505(C1-C7)'))
# 2. 精简C3+C4
results.append(run_backtest(['C3','C4'],'amt5d',5,5,'2.精简C3+C4'))
# 3. C3+C4+r10防追高
results.append(run_backtest(['C3','C4','r10'],'amt5d',5,5,'3.C3+C4+r10'))
# 4. C3+C4+集中top3
results.append(run_backtest(['C3','C4'],'amt5d',3,5,'4.C3+C4 top3集中'))
# 5. C3+C4+10天rebal
results.append(run_backtest(['C3','C4'],'amt5d',5,10,'5.C3+C4 10天rebal'))
# 6. C3+C4+r10+10天
results.append(run_backtest(['C3','C4','r10'],'amt5d',5,10,'6.C3+C4+r10 10天'))

with open('F:/backtest_workspace/results/top1000_param_search.json','w') as f:
    json.dump(results,f,ensure_ascii=False,indent=2)
log('\n-> top1000_param_search.json')
