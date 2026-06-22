# coding=gbk
# QMT 账户字段诊断脚本 v2
# 用法: QMT 新建策略 -> 加载本文件 -> 运行 -> 等待 15 秒 -> 把日志输出贴回给 CC

import time


def init(ContextInfo):
    acct_id = '67014907'

    print('=' * 60)
    print(u'[诊断] 账户ID: %s' % acct_id)
    print('=' * 60)

    # 等待交易通道连接 (最多等 15 秒)
    print(u'\n[等待] 交易通道连接中...')
    ok = False
    for i in range(15):
        try:
            accounts = get_trade_detail_data(acct_id, 'STOCK', 'account')
            if accounts is not None:
                ok = True
                print(u'[等待] 第 %d 次尝试: 通道就绪' % (i + 1))
                break
            else:
                print(u'[等待] 第 %d 次尝试: 返回 None, 再等 1 秒' % (i + 1))
                time.sleep(1)
        except Exception as e:
            print(u'[等待] 第 %d 次尝试: 异常 %s, 再等 1 秒' % (i + 1, e))
            time.sleep(1)

    if not ok:
        print(u'[失败] 15 秒内交易通道未就绪, 请确认:')
        print(u'  1. QMT 已登录交易端')
        print(u'  2. 账户 67014907 在交易端可见')
        print(u'  3. 模拟模式已启动 (日志看到 start simulation mode)')
        print(u'  4. 策略运行模式是 [实盘] 不是 [回测]')
        return

    print(u'\n----- [1] account 对象全部属性 -----')
    try:
        accounts = get_trade_detail_data(acct_id, 'STOCK', 'account')
        print(u'返回对象数: %d' % len(accounts))
        if accounts:
            acct = accounts[0]
            print(u'对象类型: %s' % type(acct).__name__)
            attrs = [a for a in dir(acct) if not a.startswith('_')]
            print(u'属性总数: %d' % len(attrs))
            print('-' * 60)
            for a in attrs:
                try:
                    val = getattr(acct, a)
                    if callable(val):
                        continue
                    print(u'  %-30s = %s' % (a, val))
                except Exception as e:
                    print(u'  %-30s = [读取失败] %s' % (a, e))
        else:
            print(u'[警告] accounts 为空列表')
    except Exception as e:
        print(u'[错误] account 查询失败: %s' % e)

    print(u'\n----- [2] position 对象全部属性 -----')
    try:
        positions = get_trade_detail_data(acct_id, 'STOCK', 'position')
        print(u'返回持仓数: %d' % len(positions))
        if positions:
            pos = positions[0]
            print(u'对象类型: %s' % type(pos).__name__)
            attrs = [a for a in dir(pos) if not a.startswith('_')]
            print(u'属性总数: %d' % len(attrs))
            print('-' * 60)
            for a in attrs:
                try:
                    val = getattr(pos, a)
                    if callable(val):
                        continue
                    print(u'  %-30s = %s' % (a, val))
                except Exception as e:
                    print(u'  %-30s = [读取失败] %s' % (a, e))
    except Exception as e:
        print(u'[错误] position 查询失败: %s' % e)

    print(u'\n----- [3] 已知字段名直接探测 -----')
    try:
        accounts = get_trade_detail_data(acct_id, 'STOCK', 'account')
        if accounts:
            acct = accounts[0]
            candidates = ['m_dTotalAsset', 'totalAsset', 'm_dTotal', 'm_dBalance', 'm_dAsset', 'm_dNav', 'm_dAvailable', 'm_dMarketValue', 'm_dFrozenCash', 'm_dFetchBalance', 'm_dFetchAvailable']
            for name in candidates:
                val = getattr(acct, name, u'<不存在>')
                print(u'  %-25s = %s' % (name, val))
    except Exception as e:
        print(u'[错误] 字段探测失败: %s' % e)

    print(u'\n' + '=' * 60)
    print(u'[诊断完成] 把以上全部输出贴回给 CC')
    print('=' * 60)


def handlebar(ContextInfo):
    pass
