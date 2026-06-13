# coding: utf-8
import os
import pytest
from backtest import paths
from backtest.scripts import init_workspace
from backtest.tests.fixtures.build_sample_db import build_sample_db


@pytest.fixture(scope="session", autouse=True)
def _workspace_ready():
    init_workspace.ensure_workspace()
    init_workspace.redirect_tempdir()


@pytest.fixture(scope="session")
def sample_db_path():
    p = paths.SAMPLE_DB_DIR + "/sample_quantifydata.duckdb"
    if not os.path.isfile(p):
        build_sample_db(target=p)
    return p
