# coding: utf-8
"""
clean_results.py - results retention helper (decision §2.6, 建议 #1).

ISOLATION CONTRACT (硬约束 #6):
  - This script is STAND-ALONE. It MUST NOT be imported by any reader / engine /
    run_backtest / run_batch module. It only runs as `python -m backtest.scripts.clean_results`.
  - Default: dry-run; archives runs older than 30 days; deletes archived runs older
    than 90 days only when --apply --delete-archived is given.
"""
import argparse
import sys

def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--delete-archived", action="store_true")
    parser.add_argument("--archive-days", type=int, default=30)
    parser.add_argument("--delete-days",  type=int, default=90)
    args = parser.parse_args(argv)
    # Phase 5 fills in actual archive/delete logic.
    print("clean_results stub:", args)
    return 0

if __name__ == "__main__":
    sys.exit(main())
