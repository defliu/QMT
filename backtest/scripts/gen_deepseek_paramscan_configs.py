# coding: utf-8
"""DeepSeek 参数扫描配置生成器。

生成单参数扫描配置（基于 V4，仅改一个参数），用 305 只 PIT 池子加速。
生成后用 run_deepseek.py 逐个跑，结果目录名含 deepseek_scan_ 前缀，
供 gen_deepseek_report.py --paramscan 收集。

Usage:
    py -3.10 -m backtest.scripts.gen_deepseek_paramscan_configs
"""
import os
import yaml

CONFIG_DIR = "D:/QMT_STRATEGIES/backtest/configs"
BASE = "deepseek_v4.yaml"

# 扫描网格（SPEC §4.1）
GRID = {
    "slope_thresh":  [1.5, 2.0, 2.5, 3.0, 3.5],
    "turnover_low":  [1.0, 2.0, 3.0, 4.0],
    "turnover_high": [8.0, 10.0, 12.0, 15.0],
    "mv_low":        [30.0, 50.0, 80.0, 100.0],
    "mv_high":       [300.0, 500.0, 800.0, 1000.0],
    "gain_limit":    [20.0, 30.0, 40.0, 50.0],
}


def main():
    with open(os.path.join(CONFIG_DIR, BASE), "r", encoding="utf-8") as f:
        base_text = f.read()

    cfg = yaml.safe_load(base_text)
    # 扫描用 305 池子加速
    cfg["universe"]["csv"] = "backtest/data/universe/p2_1b_full_a_pit_union_305.csv"

    generated = []
    for param, values in GRID.items():
        for val in values:
            c = yaml.safe_load(base_text)  # 从原始 V4 复制（保留 huang 小中盘→下面换）
            c["universe"]["csv"] = "backtest/data/universe/p2_1b_full_a_pit_union_305.csv"
            tag = "%s_%s" % (param, str(val).replace(".", "p"))
            name = "deepseek_scan_" + tag
            c["backtest"]["name"] = name
            c["strategy_params"][param] = val
            out = os.path.join(CONFIG_DIR, name + ".yaml")
            with open(out, "w", encoding="utf-8") as f:
                f.write("# coding: utf-8\n# param scan: %s=%s (V4 base, 305 pool)\n" % (param, val))
                yaml.safe_dump(c, f, allow_unicode=True, sort_keys=False)
            generated.append(name)
    print("generated %d configs:" % len(generated))
    for n in generated:
        print("  " + n)


if __name__ == "__main__":
    main()
