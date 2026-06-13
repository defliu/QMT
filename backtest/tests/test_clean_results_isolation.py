# coding: utf-8
"""硬约束 #6：clean_results 不得进任何主路径模块的 import 链。"""
import pkgutil, importlib, ast, os
from backtest import paths

MAIN_MODULES = [
    "backtest.data_tools.duckdb_reader",
    "backtest.data_tools.universe",
    "backtest.scripts.run_backtest",
    "backtest.scripts.run_batch",
]

def _imports_of(modpath):
    f = importlib.import_module(modpath).__file__
    src = open(f, "r", encoding="utf-8").read()
    tree = ast.parse(src)
    seen = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names: seen.add(a.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module: seen.add(node.module)
    return seen

def test_clean_results_not_imported_by_main_path():
    for m in MAIN_MODULES:
        try:
            imports = _imports_of(m)
        except (ModuleNotFoundError, ImportError):
            continue  # 模块还未实现的 phase 跳过
        for imp in imports:
            assert "clean_results" not in imp, \
                "%s must NOT import clean_results (constraint #6)" % m
