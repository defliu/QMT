# coding: utf-8
import logging
import pytest
from backtest.data_tools.universe import load_universe


def test_load_basic(tmp_path):
    p = tmp_path / "u.csv"
    p.write_text("code,name,sector,enabled\n000001.SZ,平安银行,银行,true\n", encoding="utf-8")
    out = load_universe(str(p))
    assert out["codes"] == ["000001.SZ"]
    assert out["records"][0]["name"] == "平安银行"


def test_disabled_skipped(tmp_path):
    p = tmp_path / "u.csv"
    p.write_text("code,enabled\n000001.SZ,true\n600000.SH,false\n", encoding="utf-8")
    assert load_universe(str(p))["codes"] == ["000001.SZ"]


def test_dedup_with_warning(tmp_path, caplog):
    caplog.set_level(logging.WARNING)
    p = tmp_path / "u.csv"
    p.write_text("code\n000001.SZ\n000001.SZ\n600000.SH\n", encoding="utf-8")
    out = load_universe(str(p))
    assert out["codes"] == ["000001.SZ", "600000.SH"]
    assert any("duplicate" in r.message.lower() for r in caplog.records)


def test_invalid_format_skipped(tmp_path):
    p = tmp_path / "u.csv"
    p.write_text("code\nABC\n000001.SZ\n", encoding="utf-8")
    out = load_universe(str(p))
    assert out["codes"] == ["000001.SZ"]
    assert "ABC" in out["dropped_codes"]


def test_empty_raises(tmp_path):
    p = tmp_path / "u.csv"
    p.write_text("code\n", encoding="utf-8")
    with pytest.raises(ValueError, match="universe.*empty"):
        load_universe(str(p))


def test_first_column_must_be_code(tmp_path):
    p = tmp_path / "u.csv"
    p.write_text("name,code\n平安,000001.SZ\n", encoding="utf-8")
    with pytest.raises(ValueError, match="first column"):
        load_universe(str(p))
