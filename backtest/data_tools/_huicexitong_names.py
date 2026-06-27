# coding: utf-8
"""Pure-ASCII Chinese identifier table for HuicexitongReader.

Why this exists: py.exe on this Windows host defaults to GBK source decoding,
which mangles literal Chinese in .py files. By keeping all Chinese as \\uXXXX
escapes here, the importer of HuicexitongReader stays portable regardless of
PYTHONUTF8 / chcp settings.
"""

T_DAILY            = "日线数据"
T_MEMBER           = "申万行业成分"
T_TINGFU           = "停复牌信息"
T_LIMIT            = "每日涨跌停"

C_CODE             = "股票代码"
C_DATE             = "交易日期"
C_TURNOVER         = "换手率(%)"
C_TURNOVER_FF      = "换手率(自由流通股)"
C_CIRC_SHARES      = "流通股本(万股)"
C_FF_SHARES        = "自由流通股本(万)"
C_TOTAL_MV         = "总市值(万元)"
C_CIRC_MV          = "流通市值(万元)"
C_ST               = "ST"
C_SUSP             = "停牌"
C_LIMIT_UP         = "涨停价"
C_LIMIT_DOWN       = "跌停价"

C_INDUSTRY_L1_CODE = "一级行业代码"
C_INDUSTRY_L1_NAME = "一级行业名称"
C_INCLUDED         = "纳入日期"
C_REMOVED          = "剔除日期"
C_LATEST           = "是否最新"
