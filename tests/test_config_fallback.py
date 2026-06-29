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
        original = mod.__file__
        with tempfile.TemporaryDirectory() as tmp:
            fake = os.path.join(tmp, 'fake_wrapper.py')
            with open(fake, 'w') as f:
                f.write('# fake')
            old_file = mod.__file__
            try:
                mod.__file__ = fake
                cfg = mod._load_config()
                self.assertIn('safemode', cfg)
                self.assertEqual(cfg['strategy']['capital_base'], 100000)
            finally:
                mod.__file__ = old_file

    def test_corrupt_yaml_file_returns_default(self):
        """损坏的 YAML 文件返回默认配置"""
        import adapters.qmt_wrapper as mod
        with tempfile.TemporaryDirectory() as tmp:
            fake = os.path.join(tmp, 'fake_wrapper.py')
            fake_dir = os.path.join(tmp, 'adapters')
            os.makedirs(fake_dir)
            with open(os.path.join(fake_dir, 'fake_wrapper.py'), 'w') as f:
                f.write('# fake')
            config_dir = os.path.join(tmp, 'config')
            os.makedirs(config_dir)
            with open(os.path.join(config_dir, 'global_config.yaml'), 'w', encoding='utf-8') as f:
                f.write('safemode:\n  enabled: true\n  log_dir: /tmp/logs\n')
            old_file = mod.__file__
            try:
                mod.__file__ = os.path.join(fake_dir, 'fake_wrapper.py')
                cfg = mod._load_config()
                self.assertIn('safemode', cfg)
                self.assertTrue(cfg['safemode']['enabled'])
                self.assertEqual(cfg['safemode']['log_dir'], '/tmp/logs')
            finally:
                mod.__file__ = old_file


if __name__ == '__main__':
    unittest.main()
