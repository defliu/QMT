# -*- coding: utf-8 -*-
"""T012-任务3: 成本校准(内嵌, 用正确trades) - top/ge-60/ge-70

读 t003_{top,ge60,ge70}_trades.csv, 每笔应用成本(buy*1.0051, sell*0.9939),
重构equity curve(等权1/MAXHOLD持仓, 连乘), 算扣非后累计/回撤/夏普/胜率。
补T001缺口(trades CSV失效) + 内嵌成本(非post-hoc)。
输出: F:/backtest_workspace/results/t012_cost_recalib.json
"""
import os, sys, json
import numpy as np, pandas as pd
OUT='F:/backtest_workspace/results'; os.makedirs(OUT, exist_ok=True)
MAXHOLD=5; CAP=100000.0
BUY_F=1.0051; SELL_F=0.9939  # 滑点0.5%+佣金万1(买); +印花税千1(卖)
def log(m): print(m, flush=True)

def backtest_equity(tr, apply_cost):
    """sum(pnl)/CAP 方法(与T001/backtest对齐). raw用backtest的pnl列, cost重算."""
    if apply_cost:
        pnl=((tr['sell_price']*SELL_F)-(tr['buy_price']*BUY_F))*tr['shares']
        rets=(tr['sell_price']*SELL_F)/(tr['buy_price']*BUY_F)-1
    else:
        pnl=tr['pnl']  # backtest已算的raw pnl
        rets=tr['return']/100.0  # return列是%
    cum=pnl.sum()/CAP
    # 回撤/夏普: 用单笔ret序列近似(无完整equity curve)
    nav=np.cumprod(1+rets); mdd=(nav/np.maximum.accumulate(nav)-1).min() if len(nav)>0 else 0
    sh=rets.mean()/rets.std()*np.sqrt(len(rets)) if rets.std()>0 else 0
    win=(rets>0).mean()*100
    return {'cum_ret':round(float(cum)*100,2),'dd':round(float(mdd)*100,2),
            'sharpe':round(float(sh),3),'win_rate':round(float(win),1),
            'n_trades':len(rets),'avg_ret':round(float(rets.mean()*100),2)}

results={}
for tag in ['top','ge60','ge70']:
    f=f'D:/QMT_STRATEGIES/data/t003_{tag}_trades.csv'
    if not os.path.exists(f):
        log(f'{tag}: {f} 不存在'); continue
    tr=pd.read_csv(f)
    raw=backtest_equity(tr, False); cost=backtest_equity(tr, True)
    results[tag]={'raw':raw,'cost':cost,
        'drag':round(raw['cum_ret']-cost['cum_ret'],2)}
    log(f"{tag}: raw {raw['cum_ret']}% -> cost {cost['cum_ret']}% (drag {raw['cum_ret']-cost['cum_ret']:+.2f}pp) 夏普{raw['sharpe']}->{cost['sharpe']} 胜率{raw['win_rate']}%->{cost['win_rate']}%")

# P0基线成本校准(用19b921a pre-6+2评分器的trades, 若有)
p0csv='D:/QMT_STRATEGIES/data/t003_p0_trades.csv'
if os.path.exists(p0csv):
    tr=pd.read_csv(p0csv); raw=backtest_equity(tr,False); cost=backtest_equity(tr,True)
    results['p0_baseline']={'raw':raw,'cost':cost,'drag':round(raw['cum_ret']-cost['cum_ret'],2)}
    log(f"p0: raw {raw['cum_ret']}% -> cost {cost['cum_ret']}%")
else:
    results['p0_baseline']={'note':'未生成(需跑19b921a评分器存trades)'}

with open(f'{OUT}/t012_cost_recalib.json','w',encoding='utf-8') as f2: json.dump(results,f2,ensure_ascii=False,indent=2)
log(f'-> {OUT}/t012_cost_recalib.json')
