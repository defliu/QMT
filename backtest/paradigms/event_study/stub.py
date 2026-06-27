# coding: utf-8
"""event_study paradigm stub — V1.0 placeholder.

Interface (Phase 1 freeze):
    run_event_study(reader, events, label_windows, **kwargs)

    reader:        data reader (duck-typed, same as portfolio paradigm)
    events:        list of dicts, each {code, event_date, ...}
    label_windows: list of tuples, each (offset_days, ...)
                   e.g. [(1, 5, 10, 20)] — compute forward returns at these horizons

Returns: event label statistics (schema TBD in Phase 2+).

Does NOT run the T→T+1 daily engine loop; event_study paradigm computes
cross-sectional event labels, not sequential trades/equity.

V1.0: stub only — raises NotImplementedError.
Full implementation deferred to Phase 2+ per SPEC §12.
"""
import warnings


def run_event_study(reader, events, label_windows, **kwargs):
    """Run the event study paradigm.

    Parameters
    ----------
    reader : object
        Data reader with load_window / trading_calendar / coverage methods.
    events : list[dict]
        Event records, each containing at least 'code' and 'event_date' keys.
    label_windows : list[tuple]
        Forward-looking windows, e.g. [(1, 5, 10, 20)] for return horizons.
    **kwargs
        Reserved for future parameters (min_data_days, etc.).

    Raises
    ------
    NotImplementedError
        V1.0 stub — full implementation deferred to Phase 2+.

    See Also
    --------
    SPEC_BACKTEST_FACTORY_V1.0_REFACTOR.md §12 — event_study stub design.
    06_interface_freeze_v10.md §6 — paradigm interface placeholder.
    """
    raise NotImplementedError(
        "event_study paradigm: V1.0 stub, see SPEC §12"
    )
