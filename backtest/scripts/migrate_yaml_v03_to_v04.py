# coding: utf-8
"""migrate_yaml_v03_to_v04 —— 一次性 yaml 迁移脚本（Phase 1 / Milestone C）。

把 v0.2 / v0.3 时代的 baseline 类 yaml 迁到 v0.4 schema：
    顶层新增 strategy_name + trading_model
    嵌套 strategy: 节保持不动（v0.4 内部仍读它，作为 strategy_params 过渡）

用法:
    py -3.10 backtest/scripts/migrate_yaml_v03_to_v04.py <input.yaml> <output.yaml>

约束（不长期兼容 SPEC §8.3）:
    - 不做批量
    - 不解析嵌套 strategy 节内容
    - 仅注入两个顶层 key + 头部注释

SPEC: specs/SPEC_BACKTEST_FACTORY_V0.4_GENERALIZATION_PHASE1.md §5.2
"""
import sys


_HEADER_LINES = [
    "# coding: utf-8",
    "# v0.4 migrated by migrate_yaml_v03_to_v04.py (Phase 1 / Milestone C)",
    "# SPEC: specs/SPEC_BACKTEST_FACTORY_V0.4_GENERALIZATION_PHASE1.md",
]

_V04_INJECT = [
    "",
    "# v0.4 Strategy Registry (Phase 1 / Milestone A): 顶层声明",
    "strategy_name: production/ima_uptrend_v31",
    "trading_model: next_open",
    "",
]


def _strip_coding_header(lines):
    """跳过开头的 # coding 行 + 紧邻注释/空行，返回 (header_block, body_block)。"""
    header = []
    body_start = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if i == 0 and stripped.startswith("#") and "coding" in stripped:
            header.append(line)
            continue
        if header and stripped.startswith("#"):
            header.append(line)
            continue
        if header and stripped == "":
            header.append(line)
            continue
        body_start = i
        break
    else:
        body_start = len(lines)
    return header, lines[body_start:]


def migrate(in_path, out_path):
    with open(in_path, "r", encoding="utf-8") as f:
        raw = f.read()
    if "strategy_name:" in raw and "trading_model:" in raw:
        raise SystemExit(
            "[migrate] %s 看上去已是 v0.4 格式（已含 strategy_name 与 trading_model）。"
            % in_path
        )
    lines = raw.splitlines(keepends=False)
    old_header, body = _strip_coding_header(lines)

    out_lines = []
    out_lines.extend(_HEADER_LINES)
    out_lines.extend([ln for ln in old_header if not ln.strip().startswith("# coding")])
    out_lines.extend(_V04_INJECT)
    out_lines.extend(body)

    out_text = "\n".join(out_lines).rstrip() + "\n"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(out_text)
    print("[migrate] ok: %s -> %s" % (in_path, out_path))


def main(argv):
    if len(argv) != 3:
        print("Usage: py -3.10 backtest/scripts/migrate_yaml_v03_to_v04.py <input.yaml> <output.yaml>")
        return 2
    migrate(argv[1], argv[2])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
