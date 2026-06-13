# coding: utf-8
from backtest.engine.hashing import compute_data_hash, compute_universe_hash


def test_universe_hash_order_invariant():
    assert compute_universe_hash(["b", "a"]) == compute_universe_hash(["a", "b"])


def test_data_hash_stable():
    args = dict(db_path="x", db_mtime="2026-05-06T23:59:00", adjustment="hfq",
                requested_start="2025-09-01", requested_end="2026-02-27",
                actual_min="2025-09-01", actual_max="2026-02-27",
                n_codes=5197, n_rows_after_dedup=701352, dedup_count=18620,
                universe_hash="u1")
    assert compute_data_hash(**args) == compute_data_hash(**args)


def test_data_hash_changes_on_any_field():
    base = dict(db_path="x", db_mtime="t1", adjustment="hfq",
                requested_start="a", requested_end="b",
                actual_min="a", actual_max="b",
                n_codes=1, n_rows_after_dedup=1, dedup_count=0, universe_hash="u")
    base_h = compute_data_hash(**base)
    for k in list(base.keys()):
        mut = dict(base)
        mut[k] = "ZZ" if isinstance(base[k], str) else 999
        assert compute_data_hash(**mut) != base_h, "field %s must affect hash" % k
