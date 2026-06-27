# coding: utf-8
"""migrate_yaml_to_v10 —— V1.0 Phase 3 yaml 迁移脚本。

把 v0.4 时代的 yaml 迁到 V1.0 schema：
    顶层 strategy_name: X → strategy: X
    嵌套 strategy: 节（6+2参数）→ strategy_params:
    grid yaml strategy.X → strategy_params.X

转换规则（SPEC §8 / 06_interface_freeze_v10.md §5）:
    1. 顶层 strategy_name: X → 重命名为 strategy: X
    2. 旧 strategy: 块（6+2 参数）→ 整块改键名 strategy_params:
    3. trading_model: 保留位置
    4. grid yaml grid.strategy.X 点号键 → grid.strategy_params.X
    5. 头部注释追加 # V1.0 migrated by migrate_yaml_to_v10.py
    6. 严格模式：迁完扫描，若 yaml 仍含顶层 strategy: 块（非单值）或 strategy_name: → 报错退出

用法:
    py -3.10 backtest/scripts/migrate_yaml_to_v10.py <input.yaml> [output.yaml]
    py -3.10 backtest/scripts/migrate_yaml_to_v10.py --batch <dir>

约束:
    - 做批量
    - 解析嵌套 strategy 节内容
    - 严格模式防漏迁
"""
import os
import re
import sys
import glob as _glob


def _is_top_level_strategy_block(line):
    """Check if line is 'strategy:' as a top-level YAML key (not strategy_name, not indented)."""
    stripped = line.strip()
    if not stripped.startswith("strategy:"):
        return False
    if stripped.startswith("strategy_name:") or stripped.startswith("strategy_params:"):
        return False
    # Must be at column 0 (no leading whitespace)
    if line[0:1] in (" ", "\t"):
        return False
    return True


def _find_strategy_block_end(lines, start_idx):
    """Find the end of a strategy: block starting at start_idx.
    Returns the index of the last line belonging to this block."""
    # Determine indent of first content line
    end = start_idx
    for i in range(start_idx + 1, len(lines)):
        line = lines[i]
        stripped = line.strip()
        if stripped == "" or stripped.startswith("#"):
            end = i
            continue
        # Check indent: must be more indented than strategy: line
        indent = len(line) - len(line.lstrip())
        if indent > 0:
            end = i
        else:
            break
    return end


def _add_migration_header(lines):
    """Add V1.0 migration header comment after # coding: line if not already present."""
    header = "# V1.0 migrated by migrate_yaml_to_v10.py"
    # Check if already has V1.0 header
    for line in lines:
        if "migrate_yaml_to_v10" in line:
            return lines
    # Find insertion point: after # coding: line
    insert_at = 0
    for i, line in enumerate(lines):
        if line.strip().startswith("#") and "coding" in line:
            insert_at = i + 1
            break
    result = lines[:insert_at] + [header] + lines[insert_at:]
    return result


_SKIP_PREFIXES = ("base_ima",)


def _should_skip(path):
    """Check if file should be skipped (research-only configs not in scope)."""
    basename = os.path.basename(path)
    for prefix in _SKIP_PREFIXES:
        if basename.startswith(prefix):
            return True
    return False


def migrate(in_path, out_path):
    """Migrate a single yaml file from v0.4 to V1.0 schema."""
    if _should_skip(in_path):
        print("[migrate] SKIP (research-only): %s" % in_path)
        return
    with open(in_path, "r", encoding="utf-8") as f:
        raw = f.read()
    lines = raw.splitlines(keepends=False)

    # --- Detect current state ---
    has_strategy_name = False
    has_strategy_block = False
    strategy_block_start = -1

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("strategy_name:"):
            if line[0:1] in (" ", "\t"):
                continue
            has_strategy_name = True
        if _is_top_level_strategy_block(line):
            has_strategy_block = True
            strategy_block_start = i

    # --- Already V1.0? ---
    if not has_strategy_name and not has_strategy_block:
        # Check if it has strategy_params: (already migrated)
        for line in lines:
            if line.strip().startswith("strategy_params:") and line[0:1] not in (" ", "\t"):
                print("[migrate] SKIP (already V1.0): %s" % in_path)
                return
        # No strategy block at all — skip (research configs without strategy)
        print("[migrate] SKIP (no strategy block): %s" % in_path)
        return

    if has_strategy_block and not has_strategy_name:
        # Check if it's a single-value strategy: (e.g., strategy: some_name)
        # vs a mapping block (strategy:\n  key: val)
        if strategy_block_start >= 0:
            block_end = _find_strategy_block_end(lines, strategy_block_start)
            if block_end == strategy_block_start:
                # Single value — already V1.0 format
                print("[migrate] SKIP (single-value strategy): %s" % in_path)
                return

    # --- Apply transformations ---
    result = list(lines)
    to_remove = set()

    # Step 1: Find strategy: block and rename to strategy_params:
    if has_strategy_block:
        block_end = _find_strategy_block_end(result, strategy_block_start)
        # Replace the key line
        old_line = result[strategy_block_start]
        result[strategy_block_start] = "strategy_params:" + old_line[len("strategy:"):]

    # Step 2: Handle strategy_name: → strategy:
    if has_strategy_name:
        for i, line in enumerate(result):
            stripped = line.strip()
            if stripped.startswith("strategy_name:") and line[0:1] not in (" ", "\t"):
                # Replace key
                value = stripped[len("strategy_name:"):].strip()
                result[i] = "strategy: " + value
                break

    # Step 3: Add V1.0 header
    result = _add_migration_header(result)

    # Step 4: Strict mode check — scan for leftovers
    out_text = "\n".join(result)
    # Check for leftover strategy_name:
    for i, line in enumerate(result):
        stripped = line.strip()
        if stripped.startswith("strategy_name:") and line[0:1] not in (" ", "\t"):
            raise SystemExit(
                "[migrate] STRICT FAIL: %s still has top-level strategy_name: after migration (line %d)"
                % (in_path, i + 1)
            )
    # Check for leftover strategy: mapping block (not single value)
    for i, line in enumerate(result):
        if _is_top_level_strategy_block(line):
            block_end = _find_strategy_block_end(result, i)
            if block_end > i:
                raise SystemExit(
                    "[migrate] STRICT FAIL: %s still has top-level strategy: block after migration (line %d)"
                    % (in_path, i + 1)
                )

    # --- Write output ---
    out_text = "\n".join(result).rstrip() + "\n"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(out_text)
    print("[migrate] ok: %s -> %s" % (in_path, out_path))


def migrate_grid(in_path, out_path):
    """Migrate a grid experiment yaml: strategy.X → strategy_params.X in grid keys."""
    with open(in_path, "r", encoding="utf-8") as f:
        raw = f.read()

    # Replace grid.strategy. with grid.strategy_params.
    new_raw = re.sub(r'(grid:\s*\n(?:\s+.*\n)*)strategy\.', r'\1strategy_params.', raw)

    if new_raw == raw:
        # Try single-line grid keys: "  strategy.X:" → "  strategy_params.X:"
        new_raw = re.sub(r'^(\s+)strategy\.', r'\1strategy_params.', raw, flags=re.MULTILINE)

    if new_raw != raw:
        new_raw = _add_migration_header(new_raw.splitlines(keepends=False))
        new_raw = "\n".join(new_raw).rstrip() + "\n"
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(new_raw)
        print("[migrate-grid] ok: %s -> %s" % (in_path, out_path))
    else:
        print("[migrate-grid] SKIP (no strategy. keys): %s" % in_path)


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]

    if not argv:
        print("Usage:")
        print("  py -3.10 migrate_yaml_to_v10.py <input.yaml> [output.yaml]")
        print("  py -3.10 migrate_yaml_to_v10.py --batch <dir>")
        return 2

    if argv[0] == "--batch":
        if len(argv) < 2:
            print("Usage: py -3.10 migrate_yaml_to_v10.py --batch <dir>")
            return 2
        batch_dir = argv[1]
        yaml_files = sorted(_glob.glob(os.path.join(batch_dir, "*.yaml")))
        if not yaml_files:
            print("[migrate] no yaml files found in %s" % batch_dir)
            return 1
        ok_count = 0
        skip_count = 0
        for yf in yaml_files:
            try:
                migrate(yf, yf)
                ok_count += 1
            except SystemExit as e:
                print(str(e))
                return 1
        # Also handle grid yamls in experiments/ subdirectory
        exp_dir = os.path.join(batch_dir, "experiments")
        if os.path.isdir(exp_dir):
            grid_files = sorted(_glob.glob(os.path.join(exp_dir, "*.yaml")))
            for gf in grid_files:
                migrate_grid(gf, gf)
        # Handle research/ subdirectory (only backtest-type research configs)
        res_dir = os.path.join(batch_dir, "research")
        if os.path.isdir(res_dir):
            res_files = sorted(_glob.glob(os.path.join(res_dir, "*.yaml")))
            for rf in res_files:
                try:
                    migrate(rf, rf)
                    ok_count += 1
                except SystemExit as e:
                    print(str(e))
                    return 1
        # Skip ima_experiments/ (research-only, different schema)
        print("[migrate] batch done: %d files migrated" % ok_count)
        return 0
    else:
        in_path = argv[0]
        out_path = argv[1] if len(argv) > 1 else in_path
        try:
            migrate(in_path, out_path)
        except SystemExit:
            raise
        return 0


if __name__ == "__main__":
    sys.exit(main())
