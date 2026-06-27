# coding: utf-8
"""硬约束 #6（v0.3 扩展）：sync_xtquant_to_duckdb 不得进任何主路径模块的 import 链。

参照 test_clean_results_isolation.py 的 AST 解析模式。
"""
import ast
import importlib
import os

GUARDED_MODULES = [
    "backtest.data_tools.duckdb_reader",
    "backtest.data_tools.universe",
    "backtest.scripts.run_backtest",
    "backtest.scripts.run_batch",
    "backtest.scripts.validate_data",
    "backtest.scripts.validate_universe",
    "backtest.engine.daily_engine",
    "backtest.engine.report",
]

FORBIDDEN_MARKER = "sync_xtquant_to_duckdb"


def _imports_of(modpath):
    f = importlib.import_module(modpath).__file__
    src = open(f, "r", encoding="utf-8").read()
    tree = ast.parse(src)
    seen = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                seen.add(a.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                seen.add(node.module)
    return seen


def test_sync_xtquant_not_imported_by_main_path():
    for m in GUARDED_MODULES:
        try:
            imports = _imports_of(m)
        except (ModuleNotFoundError, ImportError):
            continue
        for imp in imports:
            assert FORBIDDEN_MARKER not in imp, (
                "%s must NOT import %s (constraint #6)" % (m, FORBIDDEN_MARKER))


def test_sync_xtquant_does_not_import_xttrader_or_passorder():
    """sync 脚本只允许碰 xtquant.xtdata，绝不能 import xttrader/xtbp 或调用 passorder。

    检查方式：AST 解析 import 节点 + 调用节点。注释/字符串里出现这些词不算违规
    （脚本顶部边界声明本身就要复述这些禁止项，是文档而非调用）。
    """
    src_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data_tools", "sync_xtquant_to_duckdb.py")
    src = open(src_path, "r", encoding="utf-8").read()
    tree = ast.parse(src)

    forbidden_modules = {"xtquant.xttrader", "xtquant.xtbp"}
    forbidden_module_tails = {"xttrader", "xtbp"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                assert a.name not in forbidden_modules, \
                    "sync script imports forbidden module: " + a.name
                assert a.name.split(".")[-1] not in forbidden_module_tails, \
                    "sync script imports forbidden module tail: " + a.name
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            assert mod not in forbidden_modules, \
                "sync script imports from forbidden module: " + mod
            for a in node.names:
                assert a.name not in forbidden_module_tails, \
                    "sync script imports forbidden name: " + a.name

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            name = getattr(f, "attr", None) or getattr(f, "id", None)
            assert name != "passorder", "sync script must not call passorder()"
