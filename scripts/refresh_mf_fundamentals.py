# coding=utf-8
"""生成多因子IC策略所需的「最新基本面快照」到 QMT_POOL。

供 qmt_mf_strategy.py（独立 QMT 部署文件）在运行时加载：
  - mf_fundamentals.csv : 每个票「当前」估值/市值/ST 状态（元单位）
  - mf_financials.csv   : 每个票「季度」ROE/毛利率序列（供 fin_ffill 重建+45天滞后）

数据来源：E:/astock（与 research/multi_factor_ic 回测同源）。
单位约定（与 qmt_mf_strategy.py 的常量对齐）：
  - circ_mv 以「元」存储（astock 原始为万元，×1e4）
  - amount 走历史行情（xtdata 返回，已是元），此处不产出
刷新频率：建议每日盘前跑一次（基本面季度变，日更足够）。
"""
import os
import sys

import pandas as pd
import numpy as np

PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJ_ROOT not in sys.path:
    sys.path.insert(0, PROJ_ROOT)

from research.multi_factor_ic.config import DAILY_PATH, FINANCE_PATH

POOL_DIR = "D:/QMT_POOL/"
FUND_CSV = POOL_DIR + "mf_fundamentals.csv"
FIN_CSV = POOL_DIR + "mf_financials.csv"


def build_fundamentals():
    """当前基本面快照（取最近「数据完整」的交易日，避开占位日）。

    astock 最新一日常为占位（行数骤减、is_st 全 NaN）。故在最近 10 个
    交易日里挑 is_st 填充最完整的一天作快照日。circ_mv 转元。
    """
    print("[refresh] 读取日线 %s ..." % DAILY_PATH)
    daily = pd.read_parquet(DAILY_PATH)
    idx = daily.index
    dates = sorted(idx.get_level_values("trade_date").unique())
    recent = dates[-10:]
    best, best_cnt = None, -1
    for dt in recent:
        cnt = int(daily.loc[idx.get_level_values("trade_date") == dt, "is_st"].notna().sum())
        if cnt > best_cnt:
            best_cnt, best = cnt, dt
    latest_date = best
    mask = idx.get_level_values("trade_date") == latest_date
    latest = daily.loc[mask].copy()
    print("[refresh] 快照交易日=%s (最近完整日, 候选=%d)" % (latest_date, len(latest)))

    is_st_raw = latest["is_st"]
    # 正确转 bool：NaN/0 -> False，仅明确非0 -> True
    # （注意：pandas astype(bool) 会把 NaN 判成 True，禁用）
    is_st_flag = (is_st_raw.notna() & (is_st_raw != 0)).values

    out = pd.DataFrame({
        "ts_code": latest.index.get_level_values("ts_code"),
        "pe_ttm": latest["pe_ttm"].values,
        "pb": latest["pb"].values,
        "dv_ratio": latest["dv_ratio"].values,
        # astock circ_mv 单位为万元 -> 转元
        "circ_mv": latest["circ_mv"].fillna(0).values * 1e4,
        "is_st": is_st_flag,
        "suspend_type": latest["suspend_type"].fillna("N").astype(str).values,
    })
    out = out.dropna(subset=["ts_code"])
    return out, latest_date


def build_financials():
    """季度财务序列（ROE/毛利率），长表。"""
    print("[refresh] 读取财务 %s ..." % FINANCE_PATH)
    fin = pd.read_parquet(FINANCE_PATH)
    keep = fin[["ts_code", "end_date", "roe", "grossprofit_margin"]].copy()
    keep["end_date"] = pd.to_datetime(keep["end_date"], format="%Y%m%d")
    # 同一 (ts_code, end_date) 取最后一条，避免重复
    keep = keep.sort_values(["ts_code", "end_date"]).groupby(
        ["ts_code", "end_date"], as_index=False).last()
    keep["end_date"] = keep["end_date"].dt.strftime("%Y%m%d")
    return keep


def main():
    fund, latest_date = build_fundamentals()
    fin = build_financials()
    os.makedirs(POOL_DIR, exist_ok=True)
    fund.to_csv(FUND_CSV, index=False, encoding="utf-8")
    fin.to_csv(FIN_CSV, index=False, encoding="utf-8")
    print("[refresh] 写盘完成:")
    print("  %s  (%d 票, 截至 %s)" % (FUND_CSV, len(fund), latest_date))
    print("  %s  (%d 行季度财务)" % (FIN_CSV, len(fin)))
    # 基本健全性检查
    n_st = int(fund["is_st"].sum())
    n_susp = int(fund["suspend_type"].isin(["S", "R", "R&S"]).sum())
    n_circ = int((fund["circ_mv"] > 0).sum())
    n_roe = int(fin["roe"].notna().sum())
    print("[refresh] 健全性: 非ST=%d ST=%d 停牌=%d 有市值=%d 有ROE=%d"
          % (len(fund) - n_st, n_st, n_susp, n_circ, n_roe))


if __name__ == "__main__":
    main()
