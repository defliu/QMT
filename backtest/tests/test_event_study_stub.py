# coding: utf-8
"""Tests for event_study paradigm stub (Phase 4b, D6)."""
import pytest

from backtest.paradigms.event_study import run_event_study


def test_run_event_study_raises_not_implemented():
    with pytest.raises(NotImplementedError) as exc_info:
        run_event_study(None, [], [])
    assert "event_study paradigm: V1.0 stub" in str(exc_info.value)
    assert "SPEC" in str(exc_info.value)


def test_run_event_study_rejects_any_args():
    with pytest.raises(NotImplementedError):
        run_event_study(
            reader="dummy",
            events=[{"code": "000001.SZ", "event_date": "2025-01-01"}],
            label_windows=[(1, 5, 10, 20)],
        )
