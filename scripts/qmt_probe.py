# coding=gbk
"""
QMT 探针：打印 get_trade_detail_data 返回对象的属性和示例值
在 QMT 模拟端 Python 策略研究中还行，结果写入 D:\qmt_pool\probe_output.txt
诚哥跑完把 probe_output.txt 发给 CC，CC 据真实属性名写正式导出脚本
"""

import os

ACCOUNT_ID = '67014907'
OUTPUT_DIR = r'D:\qmt_pool'


def init(ContextInfo):
    lines = []

    for data_type in ['deal', 'position', 'account']:
        lines.append('=' * 60)
        lines.append('data_type: %s' % data_type)
        lines.append('=' * 60)

        try:
            data = get_trade_detail_data(ACCOUNT_ID, 'STOCK', data_type)
        except Exception as e:
            lines.append('get_trade_detail_data exception: %s' % e)
            lines.append('')
            continue

        lines.append('count: %d' % len(data))

        for i, obj in enumerate(data[:3]):
            lines.append('--- record %d ---' % i)
            for attr in dir(obj):
                if attr.startswith('_'):
                    continue
                try:
                    val = getattr(obj, attr)
                    if callable(val):
                        continue
                    lines.append('  %s = %r' % (attr, val))
                except Exception as e:
                    lines.append('  %s = <err %s>' % (attr, e))
        lines.append('')

    probe_path = os.path.join(OUTPUT_DIR, 'probe_output.txt')
    try:
        with open(probe_path, 'w', encoding='gbk') as f:
            f.write('\n'.join(lines))
        print('probe output written: %s' % probe_path)
    except Exception as e:
        print('write probe failed: %s' % e)
        print('\n'.join(lines))


def handlebar(ContextInfo):
    pass
