# coding: utf-8
"""临时：跑 305 池 V0-V4（2 并行），让 4 项优化边际贡献同池可比。"""
import glob, os, subprocess, time

PY = r"C:\Users\Administrator\AppData\Local\Programs\Python\Python310\python.exe"
CONFIG_DIR = "D:/QMT_STRATEGIES/backtest/configs"
LOG_DIR = "D:/QMT_STRATEGIES/worklog/deepseek_batch"
configs = [os.path.join(CONFIG_DIR, "deepseek_305_v%d.yaml" % v) for v in range(5)]

running = []
todo = list(configs)
done = 0
while todo or running:
    while todo and len(running) < 2:
        cfg = todo.pop(0)
        name = os.path.splitext(os.path.basename(cfg))[0]
        log = os.path.join(LOG_DIR, name + ".log")
        p = subprocess.Popen([PY, "-m", "backtest.scripts.run_deepseek", "--config", cfg],
                             stdout=open(log, "w"), stderr=subprocess.STDOUT,
                             cwd="D:/QMT_STRATEGIES")
        running.append((p, name))
        print("[launch] %s" % name, flush=True)
    still = []
    for p, name in running:
        if p.poll() is None:
            still.append((p, name))
        else:
            done += 1
            print("[done %d/5] %s rc=%d" % (done, name, p.returncode), flush=True)
    running = still
    if running:
        time.sleep(10)
print("[ALL DONE 305 V0-V4]", flush=True)
