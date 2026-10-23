"""Real PostgreSQL, deterministic model (not a live LLM), rollback-only DDL."""
from contextlib import nullcontext

import pytest

from simulator import core
from simulator.tests.test_postgres import (
    db, committed_db, postgres_connection,  # Shared opt-in fixtures and dependencies.
)
from backend.app.agent_tools import DatabaseTools, metrics_summary, plan_summary
from backend.app.agent import Agent
from backend.app.agent_state import Store
from backend.tests.test_agent import Model, run, sequence

pytestmark = pytest.mark.postgres


def test_agent_real_verified_recovery(db, tmp_path, monkeypatch):
    core.reset(db)
    core.seed(db)

    class TransactionFixtureTools(DatabaseTools):
        def read(self, name):
            # Fixture already owns a rollback-only write transaction for setup.
            if name == "metrics":
                return metrics_summary(core.benchmark(db))
            if name == "explain":
                return plan_summary(core.explain(db))
            if name == "schema":
                return core.inspect_schema(db)
            raise ValueError(name)

    monkeypatch.setattr(core, "connect", lambda: nullcontext(db))
    agent = Agent(Store(tmp_path / "integration.sqlite3"), Model(sequence()), TransactionFixtureTools())
    identifier = agent.create()["incident_id"]
    state = run(agent.investigate(identifier))
    assert state["status"] == "awaiting_approval"
    assert not core.check_demo_index(db)
    result = run(agent.decide(identifier, True))
    assert result["status"] == "resolved"
    assert result["recovery"]["results_identical"]
    assert result["recovery"]["demo_index_used_after"]
    assert result["recovery"]["p95_speedup"] > 1


def test_failed_verification_rolls_back_index(db, monkeypatch):
    core.reset(db)
    core.seed(db)
    monkeypatch.setattr(core, "connect", lambda: nullcontext(db))
    original = core.compare_benchmarks
    monkeypatch.setattr(core, "compare_benchmarks", lambda a, b: {**original(a, b), "verified": False})
    report = DatabaseTools().recover(core.REPAIR_ACTION)
    assert not report["verified"]
    assert not core.check_demo_index(db)


def test_production_read_tools_on_local_database(committed_db):
    # Separate production connections must see committed, isolated fixture data.
    tools = DatabaseTools()
    assert tools.read("metrics")["result_count"] == 10
    assert isinstance(tools.read("explain")["sequential_scan"], bool)
    assert tools.read("schema")["expected_columns_present"]
