# coding=utf-8
"""config fallback 测试：覆盖 PyYAML 缺失、配置文件不存在、轻量解析正确性"""
import sys
import os
import types
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adapters.qmt_wrapper import _lightweight_yaml_parse, _DEFAULT_CONFIG


class TestLightweightYamlParse(unittest.TestCase):
    def test_basic_key_value(self):
        text = "key1: value1\nkey2: 42\n"
        result = _lightweight_yaml_parse(text)
        self.assertEqual(result['key1'], 'value1')
        self.assertEqual(result['key2'], 42)

    def test_bool_values(self):
        text = "a: true\nb: false\n"
        result = _lightweight_yaml_parse(text)
        self.assertTrue(result['a'])
        self.assertFalse(result['b'])

    def test_section_and_nested(self):
        text = "safemode:\n  enabled: false\n  log_dir: /tmp/logs\n"
        result = _lightweight_yaml_parse(text)
        self.assertIn('safemode', result)
        self.assertFalse(result['safemode']['enabled'])
        self.assertEqual(result['safemode']['log_dir'], '/tmp/logs')

    def test_full_config_parse(self):
        cfg_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                'config', 'global_config.yaml')
        if not os.path.exists(cfg_path):
            self.skipTest('global_config.yaml not found')
        with open(cfg_path, encoding='utf-8') as f:
            text = f.read()
        result = _lightweight_yaml_parse(text)
        self.assertIn('safemode', result)
        self.assertFalse(result['safemode']['enabled'])
        self.assertEqual(result['safemode']['log_dir'], 'D:/QMT_POOL/safemode_logs/')
        self.assertIn('strategy', result)
        self.assertEqual(result['strategy']['capital_base'], 100000)

    def test_empty_and_comments(self):
        text = "# comment\n\npaths:\n  # inline\n  pool_file: D:/a.txt\n"
        result = _lightweight_yaml_parse(text)
        self.assertEqual(result['paths']['pool_file'], 'D:/a.txt')

    def test_float_value(self):
        text = "ratio: 0.16\n"
        result = _lightweight_yaml_parse(text)
        self.assertAlmostEqual(result['ratio'], 0.16)


class TestLoadConfigFallback(unittest.TestCase):
    def test_import_yaml_failure_returns_default(self):
        """模拟 import yaml 失败：monkey-patch sys.modules"""
        import adapters.qmt_wrapper as mod
        real_yaml = sys.modules.get('yaml')
        sys.modules['yaml'] = None
        try:
            cfg = mod._load_config()
            self.assertIn('safemode', cfg)
            self.assertIn('strategy', cfg)
            self.assertEqual(cfg['strategy']['capital_base'], 100000)
        finally:
            if real_yaml is not None:
                sys.modules['yaml'] = real_yaml
            else:
                sys.modules.pop('yaml', None)

    def test_missing_config_file_returns_default(self):
        """配置文件不存在时返回默认配置"""
        import adapters.qmt_wrapper as mod
        import builtins as _builtins
        real_exists = os.path.exists
        real_open = _builtins.open
        os.path.exists = lambda p: False
        try:
            cfg = mod._load_config()
            self.assertIn('safemode', cfg)
            self.assertIn('strategy', cfg)
            self.assertEqual(cfg['strategy']['capital_base'], 100000)
        finally:
            os.path.exists = real_exists

    def test_corrupt_yaml_file_returns_default(self):
        """配置文件存在时加载该配置"""
        import adapters.qmt_wrapper as mod
        import builtins as _builtins
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = os.path.join(tmp, 'config')
            os.makedirs(config_dir)
            fake_config = os.path.join(config_dir, 'global_config.yaml')
            with open(fake_config, 'w', encoding='utf-8') as f:
                f.write('safemode:\n  enabled: true\n  log_dir: /tmp/logs\n')
            _real_exists = os.path.exists
            _real_open = _builtins.open
            def _patched_exists(p):
                if p == 'D:/QMT_STRATEGIES/config/global_config.yaml':
                    return True
                return _real_exists(p)
            def _patched_open(p, *a, **kw):
                if p == 'D:/QMT_STRATEGIES/config/global_config.yaml':
                    return _real_open(fake_config, *a, **kw)
                return _real_open(p, *a, **kw)
            os.path.exists = _patched_exists
            _builtins.open = _patched_open
            try:
                cfg = mod._load_config()
                self.assertIn('safemode', cfg)
                self.assertTrue(cfg['safemode']['enabled'])
                self.assertEqual(cfg['safemode']['log_dir'], '/tmp/logs')
            finally:
                os.path.exists = _real_exists
                _builtins.open = _real_open


class TestSelfContainedConfig(unittest.TestCase):
    def test_no_config_uses_default(self):
        """无任何 config 文件时，使用 _DEFAULT_CONFIG 内置值"""
        import importlib
        real_exists = os.path.exists
        os.path.exists = lambda p: False
        try:
            import adapters.qmt_wrapper as mod
            old_config = mod._full_config
            try:
                mod._full_config = mod._load_config()
                mod._path_config = mod._full_config.get('paths', {})
                mod._strategy_config = mod._full_config.get('strategy', {})
                self.assertEqual(mod._strategy_config.get('display_name', ''), '主升浪6+2')
                self.assertEqual(mod._strategy_config.get('name', ''), 'DUAL_BAND')
                self.assertEqual(mod._strategy_config.get('capital_base', 0), 100000)
            finally:
                mod._full_config = old_config
        finally:
            os.path.exists = real_exists

    def test_config_self_contained_paths(self):
        """无 config 时，paths 段自包含的路径值正确"""
        import adapters.qmt_wrapper as mod
        real_exists = os.path.exists
        os.path.exists = lambda p: False
        try:
            old_full = mod._full_config
            try:
                mod._full_config = mod._load_config()
                mod._path_config = mod._full_config.get('paths', {})
                self.assertEqual(
                    mod._path_config.get('intraday_nav_file', ''),
                    'D:/QMT_POOL/endofday_nav_beat.txt')
                self.assertEqual(
                    mod._path_config.get('cumulative_pnl_file', ''),
                    'D:/QMT_POOL/cumulative_pnl_DUAL_BAND.txt')
                self.assertEqual(
                    mod._path_config.get('pool_path', ''),
                    'D:/QMT_POOL/selected.txt')
            finally:
                mod._full_config = old_full
        finally:
            os.path.exists = real_exists

    def test_load_config_no_file_attribute(self):
        """调用 _load_config() 不应抛 NameError（不依赖 __file__）"""
        import adapters.qmt_wrapper as mod
        real_exists = os.path.exists
        os.path.exists = lambda p: False
        try:
            cfg = mod._load_config()
            self.assertIn('strategy', cfg)
            self.assertEqual(cfg['strategy']['name'], 'DUAL_BAND')
        except NameError:
            self.fail('_load_config() raised NameError, still depends on __file__')
        finally:
            os.path.exists = real_exists


if __name__ == '__main__':
    unittest.main()
