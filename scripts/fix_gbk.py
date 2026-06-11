# coding=utf-8
"""
强制将文件转为GBK编码。

用法:
    python scripts/fix_gbk.py <file_path>

自动检测文件编码，尝试转为GBK。
不可转码字符自动替换为 ? 并给出警告。
"""
import sys
import os


def detect_encoding(raw_bytes):
    """检测文件编码，按常见编码顺序尝试解码"""
    for enc in ['utf-8', 'gbk', 'gb2312', 'gb18030', 'utf-16']:
        try:
            text = raw_bytes.decode(enc)
            return text, enc
        except (UnicodeDecodeError, UnicodeError):
            continue
    return None, None


def force_to_gbk(text):
    """强制转GBK，不可转码字符替换为 ?"""
    cleaned = []
    replaced = 0
    for ch in text:
        try:
            ch.encode('gbk')
            cleaned.append(ch)
        except UnicodeEncodeError:
            cleaned.append('?')
            replaced += 1
    return ''.join(cleaned), replaced


def fix_encoding(path):
    if not os.path.exists(path):
        print("文件不存在: %s" % path)
        sys.exit(1)

    raw = open(path, 'rb').read()

    text, detected = detect_encoding(raw)
    if text is None:
        print("无法检测文件编码")
        sys.exit(1)

    print("检测编码: %s" % detected)

    # 强制转GBK（替换不可转码字符为 ?）
    text, replaced = force_to_gbk(text)
    gbk_bytes = text.encode('gbk')

    if replaced > 0:
        print("警告: 已将 %d 个不可转码字符替换为 ?" % replaced)

    # 写出
    with open(path, 'wb') as f:
        f.write(gbk_bytes)
    print("%s -> GBK编码 完成 (%d bytes)" % (path, len(gbk_bytes)))


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("用法: python scripts/fix_gbk.py <file_path>")
        sys.exit(1)
    fix_encoding(sys.argv[1])
