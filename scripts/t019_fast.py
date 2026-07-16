# -*- coding: utf-8 -*-
"""S010优化v6快速版: 预计算因子+4组回测对比(5年)
基于5年全因子归因: atr_lt6(+0.313%) + turnover_1to8(+0.158%) 最强
"""
import pandas as pd, numpy as np, json

CAPITAL=100000.0; MAXHOLD=5; REBAL=5
STOP_LOSS=-0.08; TAKE_PROFIT=0.20; TRAILING=-0.10
BUY_F=1.0051; SELL_F=0.9939

# 加载预计算因子
print('加载预计算因子...', flush=True)
import pickle
with open('F:/tmp/factors.pkl','rb') as f:
    factors=pickle.load(f)
dates=sorted(set(d for c in factors for d in factors[c].index))
print(f'加载: {len(factors)}只 {len(dates)}日', flush=True)

# 回测区间
bt_start=dates.index(pd.Timestamp('2021-07-01'))
bt_dates=dates[bt_start:]
rebal_set=set(range(bt_start, len(dates), REBAL))
# 大盘择时(用因子里的close算等权大盘)
close_df=pd.DataFrame({c:factors[c]['close'] for c in list(factors.keys())[:500]})  # 500只算大盘(够快)
mkt_nav=(1+close_df.pct_change().mean(axis=1).fillna(0)).cumprod()
bull_arr=((mkt_nav>mkt_nav.rolling(20).mean())&(mkt_nav.rolling(20).mean()>mkt_nav.rolling(60).mean())).fillna(False).values

def run_bt(conds_fn, sort_fn, label):
    cash=CAPITAL; holdings={}; nav_curve=[]; trades=[]; exit_s={'止损':0,'止盈':0,'移动止盈':0,'失效':0}
    bull_days=0
    for i in range(bt_start, len(dates)):
        d=dates[i]; is_bull=bool(bull_arr[i]) if i<len(bull_arr) else True
        if is_bull: bull_days+=1
        is_rebal=i in rebal_set
        # sell engine
        for code in list(holdings.keys()):
            if code not in factors or d not in factors[code].index: continue
            price=float(factors[code].loc[d,'close']); h=holdings[code]
            h['hi']=max(h['hi'],price); ret=(price-h['buy'])/h['buy']
            reason=None
            if ret<=STOP_LOSS: reason='止损'
            elif ret>=TAKE_PROFIT: reason='止盈'
            elif price<h['hi'] and (price-h['hi'])/h['hi']<=TRAILING: reason='移动止盈'
            if reason:
                cash+=price*SELL_F*h['sh']; fr=(price*SELL_F)/(h['buy']*BUY_F)-1
                trades.append(round(fr*100,2)); del holdings[code]; exit_s[reason]+=1
        if is_rebal:
            # 失效退出
            for code in list(holdings.keys()):
                if code not in factors or d not in factors[code].index: continue
                m=factors[code].loc[d]
                if not conds_fn(m):
                    price=float(m['close'])
                    cash+=price*SELL_F*holdings[code]['sh']
                    fr=(price*SELL_F)/(holdings[code]['buy']*BUY_F)-1
                    trades.append(round(fr*100,2)); del holdings[code]; exit_s['失效']+=1
            # 选股
            cands=[]
            for code in factors:
                if code in holdings: continue
                if d not in factors[code].index: continue
                m=factors[code].loc[d]
                if conds_fn(m): cands.append((code, sort_fn(m)))
            cands.sort(key=lambda x:-x[1])
            slots=MAXHOLD-len(holdings)
            if not is_bull: slots=min(slots,1)
            pos=cash/max(1,MAXHOLD-len(holdings)) if is_bull else cash*0.3/max(1,MAXHOLD-len(holdings))
            for code,_ in cands[:slots]:
                price=float(factors[code].loc[d,'close'])
                sh=int(pos/(price*BUY_F)/100)*100
                if sh<100: continue
                cost=price*BUY_F*sh
                if cost>cash: sh=int(cash/(price*BUY_F)/100)*100
                if sh<100: continue
                cash-=price*BUY_F*sh; holdings[code]={'buy':price,'hi':price,'sh':sh}
        nav=cash
        for code,h in holdings.items():
            if code in factors and d in factors[code].index:
                nav+=float(factors[code].loc[d,'close'])*h['sh']
            else: nav+=h['buy']*h['sh']
        nav_curve.append(nav/CAPITAL)
    arr=np.array(nav_curve); r=np.diff(arr)/arr[:-1]
    cum=arr[-1]-1; dd=(arr/np.maximum.accumulate(arr)-1).min()
    sh=r.mean()/r.std()*np.sqrt(252) if r.std()>0 else 0
    win=sum(1 for t in trades if t>0)/len(trades)*100 if trades else 0
    # 年度
    annual={}; prev=1.0
    for j,d in enumerate(bt_dates):
        y=d.year
        if y not in annual: annual[y]=[nav_curve[j]]
        else: annual[y].append(nav_curve[j])
    ann={}
    for y in sorted(annual):
        yr=annual[y][-1]/prev-1; ann[y]=round(yr*100,1); prev=annual[y][-1]
    print(f'{label}:', flush=True)
    print(f'  cum={cum*100:+.2f}% dd={dd*100:.1f}% sh={sh:.3f} trades={len(trades)} win={win:.0f}% bull={bull_days/len(bt_dates)*100:.0f}%', flush=True)
    print(f'  退出: {exit_s}', flush=True)
    print(f'  年度: {ann}', flush=True)
    print(f'  终值: {CAPITAL*arr[-1]:.0f}元', flush=True)
    return {'label':label,'cum':round(cum*100,2),'dd':round(dd*100,1),'sharpe':round(sh,3),
            'trades':len(trades),'win':round(win),'exit':exit_s,'annual':ann,'final':round(CAPITAL*arr[-1],0)}

# 1. atr<6% + 换手1-8% + 成交额排序
r1=run_bt(lambda m: m['atr_pct']<6.0 and 1.0<=m['turnover']<=8.0,
          lambda m: m['amt5d'], '1.atr<6%+换手1-8%+成交额')
# 2. 纯atr<6% + 成交额排序
r2=run_bt(lambda m: m['atr_pct']<6.0,
          lambda m: m['amt5d'], '2.纯atr<6%+成交额')
# 3. atr<6% + 换手1-8% + 低波动排序
r3=run_bt(lambda m: m['atr_pct']<6.0 and 1.0<=m['turnover']<=8.0,
          lambda m: -m['atr_pct'], '3.atr<6%+换手1-8%+低波动排序')
# 4. 无选股基线(纯择时+成交额top5)
r4=run_bt(lambda m: True,
          lambda m: m['amt5d'], '4.无选股+成交额(基线)')

with open('F:/backtest_workspace/results/t019_optimal_5y.json','w') as f:
    json.dump([r1,r2,r3,r4],f,ensure_ascii=False,indent=2)
print(f'\n-> t019_optimal_5y.json', flush=True)
