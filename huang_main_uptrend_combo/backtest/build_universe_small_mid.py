# coding=utf-8
"""构造中小盘股池: 流通市值 < 100亿 (1,000,000 万元) 的活股.
取最近一日的市值快照, 过滤 ST/退市股, 写到 backtest/data/universe/huang_small_mid_<date>.csv.

边界:
- read_only huicexitong
- 写到 D:/QMT_STRATEGIES/backtest/data/universe/ (源码区, 与现有 core_100.csv 同位)
- 不下单 / 不接 QMT
"""
import sys, os, argparse
from datetime import datetime
sys.path.insert(0, 'D:/QMT_STRATEGIES')

import duckdb
import pandas as pd

from backtest.data_tools._huicexitong_names import T_DAILY, C_CODE, C_DATE

HUICE_DB = 'E:/huicexitong/runtime/sj/gpsj.duckdb'
UNIVERSE_DIR = 'D:/QMT_STRATEGIES/backtest/data/universe'

_C_MV_FLOAT = '\u6d41\u901a\u5e02\u503c(\u4e07\u5143)'  # 流通市值(万元)
_C_ST = 'ST'


def build(mv_max_wan=1000000, snapshot_date=None):
    """mv_max_wan: 流通市值上限 (万元), 默认 100 亿 = 1,000,000 万元.
    snapshot_date: 取此日的市值快照, None = 用 daily 表最大日.
    """
    con = duckdb.connect(HUICE_DB, read_only=True)
    try:
        if snapshot_date is None:
            snapshot_date = con.execute(
                'SELECT MAX("%s") FROM daily_data."%s"' % (C_DATE, T_DAILY)
            ).fetchone()[0]
        print('snapshot date:', snapshot_date)
        q = (
            'SELECT "%s" AS code, "%s" AS mv '
            'FROM daily_data."%s" '
            'WHERE "%s" = ? AND "%s" > 0 AND "%s" < ? '
            '  AND ("%s" = 0 OR "%s" IS NULL) '
            'ORDER BY "%s"'
        ) % (
            C_CODE, _C_MV_FLOAT,
            T_DAILY,
            C_DATE, _C_MV_FLOAT, _C_MV_FLOAT,
            _C_ST, _C_ST,
            C_CODE,
        )
        rows = con.execute(q, [snapshot_date, mv_max_wan]).fetchall()
    finally:
        con.close()

    df = pd.DataFrame(rows, columns=['code', 'mv_wan'])
    df['name'] = ''
    df['sector'] = ''
    df['enabled'] = True
    df = df[['code', 'name', 'sector', 'enabled']]
    snap_str = snapshot_date.strftime('%Y%m%d') if hasattr(snapshot_date, 'strftime') else str(snapshot_date).replace('-', '')
    out_path = os.path.join(UNIVERSE_DIR, 'huang_small_mid_%s.csv' % snap_str)
    df.to_csv(out_path, index=False, encoding='utf-8')
    print('wrote', len(df), 'codes to', out_path)
    return out_path, len(df)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--mv-max-wan', type=int, default=1000000,
                   help='流通市值上限 (万元), 默认 1,000,000 万 = 100 亿')
    args = p.parse_args()
    build(mv_max_wan=args.mv_max_wan)
