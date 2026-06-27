# coding: utf-8
"""
Path constants for backtest factory v0.2.
ALL write paths MUST reference these constants. No hard-coded paths in other modules.

Disk partition policy (decision J):
  D: code only      -> D:/QMT_STRATEGIES/backtest/
  F: large products -> F:/backtest_workspace/
  C: NO writes      -> backtest products forbidden on C drive
  E:/金策智算/      -> READ-ONLY data source (NVMe SSD; switched from F: HDD on 2026-06-14)
"""
import os

# F drive workspace
WORKSPACE_ROOT  = "F:/backtest_workspace"
RESULTS_DIR     = WORKSPACE_ROOT + "/results"
ARCHIVE_DIR     = WORKSPACE_ROOT + "/results_archive"
BATCH_DIR       = WORKSPACE_ROOT + "/batch_summary"
SAMPLE_DB_DIR   = WORKSPACE_ROOT + "/sample_db"
CACHE_DIR       = WORKSPACE_ROOT + "/cache"
LOGS_DIR        = WORKSPACE_ROOT + "/logs"

# Read-only data source (decision I; relocated to E: SSD on 2026-06-14 for read perf)
JINCE_DB_PATH   = "E:/金策智算/_internal/databases/duckdb/quantifydata.duckdb"

# v0.3 project-owned DuckDB path (resolved per D10 / OQ-1 closure)
PROJECT_MARKET_DB = "F:/backtest_workspace/data/duckdb/qmt_market_data.duckdb"

# D drive code paths
BACKTEST_ROOT   = os.path.dirname(os.path.abspath(__file__))
UNIVERSE_DIR    = BACKTEST_ROOT + "/data/universe"
CONFIGS_DIR     = BACKTEST_ROOT + "/configs"

WORKSPACE_SUBDIRS = [RESULTS_DIR, ARCHIVE_DIR, BATCH_DIR, SAMPLE_DB_DIR, CACHE_DIR, LOGS_DIR]
WORKSPACE_README = WORKSPACE_ROOT + "/README.txt"
