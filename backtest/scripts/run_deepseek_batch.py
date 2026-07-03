# coding: utf-8
"""DeepSeek 批量编排：跑剩余 V 版本 + 参数扫描，控制并行度防 OOM。

Usage:
    py -3.10 -m backtest.scripts.run_deepseek_batch --phase v23      # 跑 V2 V3
    py -3.10 -m backtest.scripts.run_deepseek_batch --phase scan     # 跑参数扫描
    py -3.10 -m backtest.scripts.run_deepseek_batch --phase scan --parallel 2
"""
import argparse
import glob
import os
import subprocess
import sys
import time

PY = r"C:\Users\Administrator\AppData\Local\Programs\Python\Python310\python.exe"
CONFIG_DIR = "D:/QMT_STRATEGIES/backtest/configs"
LOG_DIR = "D:/QMT_STRATEGIES/worklog/deepseek_batch"
if not os.path.isdir(LOG_DIR):
    os.makedirs(LOG_DIR, exist_ok=True)


def run_one(cfg_path, log_path):
    """启动一个回测子进程，返回 Popen。"""
    return subprocess.Popen(
        [PY, "-m", "backtest.scripts.run_deepseek", "--config", cfg_path],
        stdout=open(log_path, "w"), stderr=subprocess.STDOUT,
        cwd="D:/QMT_STRATEGIES")


def run_pool(configs, parallel):
    """以 parallel 并行度跑完所有 configs。"""
    running = []  # [(Popen, name, log)]
    todo = list(configs)
    done = 0
    while todo or running:
        # 补满并行槽
        while todo and len(running) < parallel:
            cfg = todo.pop(0)
            name = os.path.splitext(os.path.basename(cfg))[0]
            log = os.path.join(LOG_DIR, name + ".log")
            p = run_one(cfg, log)
            running.append((p, name, log))
            print("[launch] %s -> %s" % (name, log), flush=True)
        # 轮询完成
        still = []
        for p, name, log in running:
            rc = p.poll()
            if rc is None:
                still.append((p, name, log))
            else:
                done += 1
                print("[done %d/%d] %s rc=%d" % (done, len(configs), name, rc), flush=True)
        running = still
        if running:
            time.sleep(10)
    print("[all done] %d configs" % len(configs), flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True, choices=["v23", "scan", "all"])
    ap.add_argument("--parallel", type=int, default=2)
    args = ap.parse_args()

    if args.phase == "all":
        # 先跑 V0-V4（3 并行），再跑参数扫描（2 并行）
        v_cfgs = [os.path.join(CONFIG_DIR, "deepseek_v%d.yaml" % v) for v in (0, 1, 2, 3, 4)]
        scan_cfgs = sorted(glob.glob(os.path.join(CONFIG_DIR, "deepseek_scan_*.yaml")))
        print("=== PHASE 1: V0-V4 (parallel=3) ===", flush=True)
        run_pool(v_cfgs, 3)
        print("=== PHASE 2: param scan (parallel=2) ===", flush=True)
        run_pool(scan_cfgs, 2)
        print("=== ALL DONE ===", flush=True)
        return

    if args.phase == "v23":
        configs = [os.path.join(CONFIG_DIR, "deepseek_v%d.yaml" % v) for v in (2, 3)]
    else:
        configs = sorted(glob.glob(os.path.join(CONFIG_DIR, "deepseek_scan_*.yaml")))

    print("phase=%s configs=%d parallel=%d" % (args.phase, len(configs), args.parallel), flush=True)
    run_pool(configs, args.parallel)


if __name__ == "__main__":
    main()
