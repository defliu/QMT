# coding=utf-8
"""一键配置 xtquant 到当前 Python 环境

用法:
    python scripts/setup_xtquant.py

自动完成:
    1. 搜索 QMT 模拟端安装目录 (D:\\国金QMT*模拟* 或 D:\\QMT*模拟*)
    2. 定位 xtquant 包路径 (...\\bin.x64\\Lib\\site-packages\\xtquant\\)
    3. 复制 xtquant 到当前 Python 的 site-packages
    4. 验证: from xtquant import xtdata; print('OK')

注意: 本脚本只匹配模拟端目录，正式版路径已被排除。
"""

import os
import sys
import shutil
import glob
import site


def find_xtquant_source():
    """在 QMT 安装目录中搜索 xtquant 包路径。"""
    search_roots = []

    # 搜索 D:\ 下以 QMT 开头且包含"模拟"的目录（排除正式版）
    try:
        for item in os.listdir('D:\\'):
            item_path = os.path.join('D:\\', item)
            if not os.path.isdir(item_path):
                continue
            upper = item.upper()
            if 'QMT' in upper and '模拟' in item:
                search_roots.append(item_path)
    except PermissionError:
        pass

    # 在候选目录中搜索 xtquant
    candidates = []
    for root in search_roots:
        for dirpath, dirnames, _ in os.walk(root):
            if 'xtquant' in dirnames:
                full = os.path.join(dirpath, 'xtquant')
                # 确认包含核心 pyd 文件
                if any(f.endswith('.pyd') for f in os.listdir(full)):
                    candidates.append(full)
            # 限制搜索深度
            if dirpath.count(os.sep) > 8:
                dirnames.clear()

    if not candidates:
        return None

    # 优先选择 cp310 版本的 (匹配当前 Python 3.10)
    py_ver = f'cp{sys.version_info.major}{sys.version_info.minor}'
    for c in candidates:
        if any(py_ver in f for f in os.listdir(c)):
            return c

    return candidates[0]


def get_site_packages():
    """获取当前 Python 的 site-packages 路径。"""
    paths = site.getsitepackages()
    for p in paths:
        if 'site-packages' in p:
            return p
    return paths[0] if paths else None


def main():
    print("=" * 60)
    print("xtquant 环境配置工具")
    print("=" * 60)

    # Step 1: 查找 xtquant 源路径
    print("\n[1/4] 搜索 QMT 安装目录中的 xtquant ...")
    src = find_xtquant_source()
    if not src:
        print("  未找到 xtquant 包。请确认已安装 QMT 模拟端。")
        print("  期待路径: D:\\国金QMT交易端模拟\\bin.x64\\Lib\\site-packages\\xtquant\\")
        sys.exit(1)
    print(f"  找到: {src}")

    # Step 2: 确定目标路径
    print("\n[2/4] 确定目标 site-packages ...")
    sp = get_site_packages()
    if not sp:
        print("  无法确定 Python site-packages 路径")
        sys.exit(1)
    dst = os.path.join(sp, 'xtquant')
    print(f"  目标: {dst}")

    # Step 3: 复制
    print("\n[3/4] 复制 xtquant ...")
    if os.path.exists(dst):
        print("  目标已存在，先移除旧版本 ...")
        shutil.rmtree(dst)

    shutil.copytree(src, dst, ignore=shutil.ignore_patterns('__pycache__'))
    print(f"  已复制: {src} -> {dst}")

    # Step 4: 验证
    print("\n[4/4] 验证导入 ...")
    sys.path.insert(0, sp)
    try:
        import xtquant
        ver = getattr(xtquant, '__version__', 'unknown')
        print(f"  xtquant 版本: {ver}")
        from xtquant import xtdata
        print(f"  xtdata 导入成功: {xtdata.__name__}")
        print("\nOK 配置完成! xtquant 已可用。")
    except ImportError as e:
        print(f"\n导入失败: {e}")
        print("请手动检查 site-packages 路径。")
        sys.exit(1)


if __name__ == '__main__':
    main()
