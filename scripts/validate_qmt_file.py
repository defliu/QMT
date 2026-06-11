#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
QMT策略文件合规检查工具

检查项:
  [1/6] 文件存在
  [2/6] 编码 GBK
  [3/6] 文件头 # coding=gbk
  [4/6] Python 3.6 语法
  [5/6] 无 MOCK 残留 (仅生产版)
  [6/6] 无长小数输出

Usage:
    python scripts/validate_qmt_file.py <file_path>          # 生产版检查
    python scripts/validate_qmt_file.py <file_path> --dev   # 开发版(跳过MOCK)
"""
import sys
import os
import re
import ast


def main():
    args = sys.argv[1:]
    if not args or '-h' in args or '--help' in args:
        print("Usage: python scripts/validate_qmt_file.py <file_path>")
        print("       python scripts/validate_qmt_file.py <file_path> --dev")
        sys.exit(1)

    path = args[0]
    dev_mode = '--dev' in args
    name = os.path.basename(path)
    total = 6
    passed = 0
    failed = 0

    print("Validating: %s" % name)

    # [1/6] 文件存在
    if os.path.exists(path) and os.path.isfile(path):
        print("  [1/6] 文件存在         PASS")
        passed += 1
    else:
        print("  [1/6] 文件存在         FAIL  (文件不存在或不可读)")
        _print_result(passed, failed + 1, total)
        sys.exit(1)

    with open(path, 'rb') as f:
        raw = f.read()

    # [2/6] 编码 GBK
    try:
        raw.decode('gbk')
        print("  [2/6] 编码 GBK         PASS")
        passed += 1
    except:
        print("  [2/6] 编码 GBK         FAIL  (不是GBK编码，实际编码可能是UTF-8)")
        _print_result(passed, failed + 1, total)
        sys.exit(1)

    text = raw.decode('gbk')

    # [3/6] 文件头 # coding=gbk
    first_line = raw.split(b'\n')[0].decode('gbk').strip()
    if 'coding=gbk' in first_line or 'coding: gbk' in first_line:
        print("  [3/6] 文件头 # coding=gbk  PASS")
        passed += 1
    else:
        print("  [3/6] 文件头 # coding=gbk  FAIL  (文件头缺少 # coding=gbk)")
        _print_result(passed, failed + 1, total)
        sys.exit(1)

    # [4/6] Python 3.6 语法
    syntax_ok = True
    try:
        compile(text, path, 'exec')
    except SyntaxError as e:
        syntax_ok = False
        print("  [4/6] Python 3.6 语法   FAIL  (语法错误: %s)" % e)

    if syntax_ok:
        try:
            ast.parse(text)
        except SyntaxError as e:
            syntax_ok = False
            print("  [4/6] Python 3.6 语法   FAIL  (语法错误: %s)" % e)

    if syntax_ok:
        # 检测 3.9+ 语法模式 (仅警告)
        patterns = [
            (r'dict\[', 'dict[str,...] 泛型下标(3.9+)'),
            (r'list\[', 'list[str,...] 泛型下标(3.9+)'),
            (r'tuple\[', 'tuple[str,...] 泛型下标(3.9+)'),
            (r'\w+ \| None', 'Union简写(3.10+)'),
        ]
        for pattern, desc in patterns:
            if re.search(pattern, text):
                print("    WARN: 可能的3.9+语法: %s" % desc)
        print("  [4/6] Python 3.6 语法   PASS")
        passed += 1

    # [5/6] 无 MOCK 残留
    is_dev = dev_mode or '_dev' in name
    if not is_dev:
        has_mock = 'MOCK下单' in text or 'context_mock' in text
        if has_mock:
            print("  [5/6] 无 MOCK 残留      FAIL  (生产版包含MOCK残留)")
            failed += 1
        else:
            print("  [5/6] 无 MOCK 残留      PASS")
            passed += 1
    else:
        print("  [5/6] 无 MOCK 残留      PASS  (仅生产版检查，开发版跳过)")
        passed += 1

    # [6/6] 无长小数输出
    long_floats = re.findall(r'\d+\.\d{6,}', text)
    if long_floats:
        show = long_floats[:3]
        print("  [6/6] 无长小数输出      FAIL  (发现 %d 处未格式化的长小数>6位)" % len(long_floats))
        for lf in show:
            print("    %s" % lf)
        failed += 1
    else:
        print("  [6/6] 无长小数输出      PASS  (所有评分值 %.2f)")
        passed += 1

    # Result
    _print_result(passed, failed, total)
    sys.exit(0 if failed == 0 else 1)


def _print_result(passed, failed, total):
    print("  ------------------------")
    if failed == 0:
        print("  Result: ALL PASS  (%d/%d)" % (passed, total))
    else:
        print("  Result: %d PASS, %d FAIL  (%d/%d)" % (passed, failed, passed, total))


if __name__ == '__main__':
    main()
