# -*- coding: utf-8 -*-
"""S010完整策略近一年回测: 505选股+B+C排序+505失效退出+MA60择时

模拟S010全流程:
1. 505 C1-C7筛选(248池代理全市场)
2. 5日涨幅<20%防追高(B)
3. 成交额排序选top5(C)
4. 等权持有
5. 505条件失效退出(每rebal检查持仓C1-C7,不满足卖出)
6. MA60择时(BEAR限仓30%)
近1年(2025-07~2026-06), 每5天rebalance。
输出: F:/backtest_workspace/results/t013_s010_1y.json
"""
import os, sys, json, math, warnings
warnings.filterwarnings('ignore')
import numpy as np, pandas as pd

POOL_FILE='D:/QMT_POOL/selectedall.txt'
ASTOCK='E:/astock/daily/stock_daily.parquet'
MAXHOLD=5; REBAL=5; FWD=REBAL
def log(m): print(m, flush=True)

def check_505(hist):
    """505 C1-C7条件, 返回(bool通过, ret_5d, amount_5d)"""
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

# 加载248池+astock(hfq)
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
df['trade_date']=pd.to_datetime(df['trade_date']);df['ts_code']=df['ts_code'].astype(str)
df=df[df['ts_code'].isin(set(pool))].copy().rename(columns={'vol':'volume'})
for col in ['open','high','low','close']: df[col]=df[col]*df['adj_factor']
df=df[(df['trade_date']>='2025-01-01')&(df['trade_date']<='2026-06-22')]
df=df.sort_values(['ts_code','trade_date']).reset_index(drop=True)
codes=sorted(df['ts_code'].unique())
data={c:df[df['ts_code']==c].set_index('trade_date')[['open','high','low','close','volume','amount']].dropna() for c in codes}
all_dates=sorted(df['trade_date'].unique())
log(f'池={len(pool)} 股票={len(data)} 日期={all_dates[0].date()}~{all_dates[-1].date()} ({len(all_dates)}日)')

# 大盘代理(248等权) + MA60择时
close_piv=pd.DataFrame({c:data[c]['close'] for c in codes})
mkt_nav=(1+close_piv.pct_change().mean(axis=1).fillna(0)).cumprod()
ma20_mkt=mkt_nav.rolling(20).mean(); ma60_mkt=mkt_nav.rolling(60).mean()
bull=((mkt_nav>ma20_mkt)&(ma20_mkt>ma60_mkt)).fillna(False)
# 近1年rebal日期(从2025-07开始,确保MA60有数据)
start_idx=max(0,all_dates.index(pd.Timestamp('2025-07-01')))
rebal_dates=all_dates[start_idx::REBAL]
log(f'rebal点: {len(rebal_dates)} (从{rebal_dates[0].date()})')

# 回测
nav=1.0; nav_curve=[1.0]; dates_rec=[rebal_dates[0]]
holdings={}  # {code: buy_price}
trades=[]; bull_count=0; exit_505_count=0; exit_sell_count=0
for i,d in enumerate(rebal_dates[:-1]):
    d_end=rebal_dates[i+1]
    is_bull=bool(bull.loc[d]) if d in bull.index else True
    if is_bull: bull_count+=1
    # 1. 505条件失效退出: 检查持仓是否还满足C1-C7
    to_exit=[]
    for code in list(holdings.keys()):
        sub=data[code]
        hist=sub[sub.index<=d]
        if len(hist)<60: continue
        ok,_,_=check_505(hist.tail(120))
        if not ok:
            to_exit.append(code)
    for code in to_exit:
        buy_p=holdings[code]
        sub=data[code]
        fwd=sub[(sub.index>d)&(sub.index<=d_end)]['close']
        sell_p=float(fwd.iloc[0]) if len(fwd)>0 else buy_p  # 次日开盘卖(简化用当日close)
        ret=(sell_p/buy_p-1)*100
        trades.append({'code':code,'buy_date':str(d.date()),'sell_date':str(d_end.date()),'ret':round(ret,2),'reason':'505失效'})
        nav*=(1+ret/100/MAXHOLD)
        del holdings[code]
        exit_505_count+=1
    # 2. 选股: 505 C1-C7 + 防追高 + 成交额排序
    candidates=[]
    for code in codes:
        if code in holdings: continue
        sub=data[code]; hist=sub[sub.index<=d]
        if len(hist)<60: continue
        ok,ret5,amt=check_505(hist.tail(120))
        if not ok: continue
        if ret5>=20.0: continue  # B防追高
        candidates.append((code,ret5,amt))
    candidates.sort(key=lambda x:-x[2])  # C成交额排序
    # 3. 买入(等权, cap max_hold, 择时限仓)
    slots=MAXHOLD-len(holdings)
    if not is_bull: slots=min(slots, 1)  # BEAR限仓(最多买1只, 即30%仓位)
    for code,ret5,amt in candidates[:slots]:
        sub=data[code]
        fwd=sub[(sub.index>d)&(sub.index<=d_end)]['close']
        if len(fwd)<1: continue
        buy_p=float(sub[sub.index<=d]['close'].iloc[-1])
        sell_p=float(fwd.iloc[-1])
        ret=(sell_p/buy_p-1)*100
        holdings[code]=buy_p  # 临时记(下rebal检查失效)
        trades.append({'code':code,'buy_date':str(d.date()),'sell_date':str(d_end.date()),'ret':round(ret,2),'reason':'505持有'})
        nav*=(1+ret/100/MAXHOLD)
    # 清理本rebal临时holdings(模拟持有到下次rebal)
    # 实际上holdings在下次rebal检查失效,这里简化: holdings保留到下次rebal
    nav_curve.append(nav)
    dates_rec.append(d_end)
    if i%10==0:
        log(f'  rebal {i+1}/{len(rebal_dates)-1} {d.date()} bull={is_bull} 持仓={len(holdings)} 退出={len(to_exit)} 新买={slots} NAV={nav:.4f}')

# 指标
nav_arr=np.array(nav_curve)
rets=np.diff(nav_arr)/nav_arr[:-1]
cum=nav_arr[-1]/nav_arr[0]-1
dd=(nav_arr/np.maximum.accumulate(nav_arr)-1).min()
sharpe=rets.mean()/rets.std()*np.sqrt(52) if rets.std()>0 else 0
win_trades=[t for t in trades if t['ret']>0]
log(f'\n=== S010近1年回测结果 ===')
log(f'累计收益: {cum*100:+.2f}%')
log(f'最大回撤: {dd*100:.2f}%')
log(f'夏普: {sharpe:.3f}')
log(f'交易笔数: {len(trades)} (其中505失效退出: {exit_505_count})')
log(f'胜率: {len(win_trades)/len(trades)*100:.1f}%' if trades else '无交易')
log(f'多头占比: {bull_count/(len(rebal_dates)-1)*100:.1f}%')
results={
    'cum_return_pct':round(cum*100,2),'max_drawdown_pct':round(dd*100,2),
    'sharpe':round(float(sharpe),3),'n_trades':len(trades),
    'exit_505_count':exit_505_count,'win_rate':round(len(win_trades)/len(trades)*100,1) if trades else 0,
    'bull_ratio':round(bull_count/(len(rebal_dates)-1)*100,1),
    'period':f'{rebal_dates[0].date()}~{rebal_dates[-1].date()}',
    'n_rebal':len(rebal_dates)-1,
}
with open('F:/backtest_workspace/results/t013_s010_1y.json','w',encoding='utf-8') as f:
    json.dump(results,f,ensure_ascii=False,indent=2)
log(f'\n-> F:/backtest_workspace/results/t013_s010_1y.json')
