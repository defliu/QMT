# -*- coding: utf-8 -*-
"""S010完整策略近1年回测v2: 逐日+sell engine+505失效退出+成本+择时

逐日循环(非5天), 每日检查:
1. sell engine: 止损-8%/止盈+20%/移动止盈-5%(从最高点回撤)
2. 505条件失效退出(每5天rebal时检查持仓C1-C7)
3. 每5天rebal: 505选股+B+C排序+买入
4. MA60择时(BEAR限仓30%)
5. 交易成本: 买*1.0051 卖*0.9939
输出: F:/backtest_workspace/results/t013_s010_v2.json
"""
import os, sys, json, math, warnings
warnings.filterwarnings('ignore')
import numpy as np, pandas as pd

POOL_FILE='D:/QMT_POOL/selectedall.txt'; ASTOCK='E:/astock/daily/stock_daily.parquet'
MAXHOLD=5; REBAL=5; CAPITAL=100000.0
STOP_LOSS=-0.08; TAKE_PROFIT=0.20; TRAILING=-0.05
BUY_F=1.0051; SELL_F=0.9939
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

# 加载
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
log(f'池={len(pool)} 股票={len(data)} 日期={all_dates[0].date()}~{all_dates[-1].date()}')

# 大盘代理+择时
close_piv=pd.DataFrame({c:data[c]['close'] for c in codes})
mkt_nav=(1+close_piv.pct_change().mean(axis=1).fillna(0)).cumprod()
ma20_mkt=mkt_nav.rolling(20).mean(); ma60_mkt=mkt_nav.rolling(60).mean()
bull=((mkt_nav>ma20_mkt)&(ma20_mkt>ma60_mkt)).fillna(False)
start_idx=max(0,all_dates.index(pd.Timestamp('2025-07-01')))
bt_dates=all_dates[start_idx:]
rebal_set=set(all_dates[start_idx::REBAL])
log(f'回测: {bt_dates[0].date()}~{bt_dates[-1].date()} ({len(bt_dates)}日)')

# 逐日回测
cash=CAPITAL; holdings={}  # {code:{buy_price,buy_date,highest,shares}}
nav_curve=[]; trades=[]; exit_stats={'止损':0,'止盈':0,'移动止盈':0,'505失效':0}
rebal_count=0; bull_days=0

for d in bt_dates:
    is_bull=bool(bull.loc[d]) if d in bull.index else True
    if is_bull: bull_days+=1
    is_rebal=d in rebal_set
    # 1. 每日: sell engine(止损/止盈/移动止盈)
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
            trades.append({'code':code,'buy':str(h['buy_date'].date()),'sell':str(d.date()),'ret':round(final_ret*100,2),'reason':reason})
            del holdings[code]; exit_stats[reason]+=1
    # 2. 每5天rebal: 505失效退出 + 选股买入
    if is_rebal:
        rebal_count+=1
        # 505失效退出
        for code in list(holdings.keys()):
            sub=data[code]; hist=sub[sub.index<=d]
            if len(hist)<60: continue
            ok,_,_=check_505(hist.tail(120))
            if not ok:
                price=float(sub.loc[d,'close']) if d in sub.index else holdings[code]['buy_price']
                sell_amt=price*SELL_F*holdings[code]['shares']
                cash+=sell_amt
                final_ret=(price*SELL_F)/(holdings[code]['buy_price']*BUY_F)-1
                trades.append({'code':code,'buy':str(holdings[code]['buy_date'].date()),'sell':str(d.date()),'ret':round(final_ret*100,2),'reason':'505失效'})
                del holdings[code]; exit_stats['505失效']+=1
        # 选股: 505 C1-C7 + 防追高 + 成交额排序
        candidates=[]
        for code in codes:
            if code in holdings: continue
            sub=data[code]; hist=sub[sub.index<=d]
            if len(hist)<60: continue
            ok,ret5,amt=check_505(hist.tail(120))
            if not ok or ret5>=20.0: continue
            candidates.append((code,ret5,amt))
        candidates.sort(key=lambda x:-x[2])
        slots=MAXHOLD-len(holdings)
        if not is_bull: slots=min(slots,1)  # BEAR限仓
        pos_target=cash/max(1,MAXHOLD-len(holdings)) if is_bull else cash*0.3/max(1,MAXHOLD-len(holdings))
        for code,ret5,amt in candidates[:slots]:
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
    # 3. NAV
    nav=cash
    for code,h in holdings.items():
        sub=data[code]
        if d in sub.index: nav+=float(sub.loc[d,'close'])*h['shares']
        else: nav+=h['buy_price']*h['shares']
    nav_curve.append(nav/CAPITAL)

# 指标
nav_arr=np.array(nav_curve); rets=np.diff(nav_arr)/nav_arr[:-1]
cum=nav_arr[-1]-1; dd=(nav_arr/np.maximum.accumulate(nav_arr)-1).min()
sh=rets.mean()/rets.std()*np.sqrt(252) if rets.std()>0 else 0
win=[t for t in trades if t['ret']>0]
log(f'\n=== S010 v2 逐日+sell engine 回测结果 ===')
log(f'累计收益: {cum*100:+.2f}%')
log(f'最大回撤: {dd*100:.2f}%')
log(f'夏普: {sh:.3f}')
log(f'交易笔数: {len(trades)}')
log(f'胜率: {len(win)/len(trades)*100:.1f}%' if trades else '无交易')
log(f'退出统计: {exit_stats}')
log(f'多头占比: {bull_days/len(bt_dates)*100:.1f}%')
log(f'rebal次数: {rebal_count}')
results={
    'cum_return_pct':round(cum*100,2),'max_drawdown_pct':round(dd*100,2),
    'sharpe':round(float(sh),3),'n_trades':len(trades),
    'win_rate':round(len(win)/len(trades)*100,1) if trades else 0,
    'exit_stats':exit_stats,'bull_ratio':round(bull_days/len(bt_dates)*100,1),
    'n_rebal':rebal_count,'period':f'{bt_dates[0].date()}~{bt_dates[-1].date()}',
    'cost':'买*1.0051 卖*0.9939(滑点0.5%+佣金万1+印花税千1)',
    'sell_engine':f'止损{STOP_LOSS*100}% 止盈+{TAKE_PROFIT*100}% 移动止盈{TRAILING*100}%',
}
with open('F:/backtest_workspace/results/t013_s010_v2.json','w',encoding='utf-8') as f:
    json.dump(results,f,ensure_ascii=False,indent=2)
log(f'\n-> F:/backtest_workspace/results/t013_s010_v2.json')
