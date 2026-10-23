"""Opt-in only: operates solely on the local simulator service, port 5433."""

import os
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
import psycopg
from psycopg import sql
import pytest

from simulator import core

pytestmark = pytest.mark.postgres


@pytest.fixture
def postgres_connection():
    if os.environ.get("SENTINELOPS_TEST_POSTGRES") != "1":
        pytest.skip("PostgreSQL integration tests are opt-in: set SENTINELOPS_TEST_POSTGRES=1")
    load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)
    required = ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB")
    if any(not os.environ.get(key) for key in required):
        pytest.skip("PostgreSQL demo test credentials unavailable; configure .env")
    try:
        conn = core.connect()
    except psycopg.OperationalError:
        pytest.skip("PostgreSQL demo test database unavailable at 127.0.0.1:5433")
    with conn:
        yield conn


@pytest.fixture
def db(postgres_connection):
    with postgres_connection.transaction(force_rollback=True):
        yield postgres_connection


@pytest.fixture
def committed_db(postgres_connection, monkeypatch):
    """Commit setup in an owned disposable database for independent readers.

    Requires CREATEDB on the opt-in local test role. The existing demo database
    is never seeded or reset by this fixture.
    """
    name = "sentinelops_test_" + uuid4().hex
    identifier = sql.Identifier(name)
    postgres_connection.execute(
        sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(identifier)
    )
    try:
        monkeypatch.setenv("POSTGRES_DB", name)
        with core.connect() as conn:
            core.seed(conn)
            yield conn
    finally:
        postgres_connection.execute(sql.SQL("DROP DATABASE {}").format(identifier))


def test_full_incident_to_recovery_cycle(db):
    report = core.verify(db, samples=100)
    assert report["results_identical"]
    assert report["sequential_scan_before"]
    assert report["demo_index_used_after"]
    assert report["before"]["result_count"] == 10
    assert report["before"]["sample_count"] == 100
    assert report["after"]["sample_count"] == 100
    assert report["latency_improved"], "No measured improvement; inspect host load and rerun"
    assert report["verified"]
    core.repair(db)  # Idempotent.
    core.reset(db)
    core.reset(db)  # Idempotent.
    assert not core.check_demo_index(db)
    restored = core.benchmark(db, samples=10)
    assert any(n["Node Type"] == "Seq Scan" for n in core.plan_nodes(restored["plan"]))
    assert restored["result_sha256"] == report["before"]["result_sha256"]
    assert core.seed(db)["rows"] == 100_000  # Idempotent seed.


def test_reset_preserves_unrelated_objects_and_all_rows(db):
    core.reset(db)
    core.seed(db)
    db.execute("CREATE INDEX sentinelops_test_status_idx ON sentinelops_demo.orders (status)")
    core.repair(db)
    core.reset(db)
    assert db.execute("SELECT to_regclass('sentinelops_demo.sentinelops_test_status_idx')").fetchone()[0]
    assert db.execute("SELECT count(*) FROM sentinelops_demo.orders").fetchone()[0] == 100_000
    assert db.execute("SELECT to_regclass('sentinelops_demo.orders_pkey')").fetchone()[0]
    assert core.lookup(db, "x'; DROP TABLE sentinelops_demo.orders; --") == []


def test_reset_rejects_index_with_same_name_on_other_column(db):
    core.reset(db)
    core.seed(db)
    db.execute("CREATE INDEX orders_customer_email_demo_idx ON sentinelops_demo.orders (status)")
    with pytest.raises(ValueError, match="another object"):
        core.reset(db)
    assert db.execute("SELECT to_regclass('sentinelops_demo.orders_customer_email_demo_idx')").fetchone()[0]
