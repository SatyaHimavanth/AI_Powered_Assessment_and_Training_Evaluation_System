import pytest

from db.database import (
    _pool_options,
    _resolve_async_database_url,
    _resolve_database_url,
    _validate_connection_budget,
)


def test_database_pool_defaults_are_bounded(monkeypatch):
    monkeypatch.delenv("DB_POOL_SIZE", raising=False)
    monkeypatch.delenv("DB_MAX_OVERFLOW", raising=False)
    monkeypatch.delenv("DB_POOL_TIMEOUT_SECONDS", raising=False)

    options = _pool_options()

    assert options["pool_size"] == 5
    assert options["max_overflow"] == 5
    assert options["pool_timeout"] == 30


def test_database_pool_values_are_configurable(monkeypatch):
    monkeypatch.setenv("DB_POOL_SIZE", "3")
    monkeypatch.setenv("DB_MAX_OVERFLOW", "2")
    monkeypatch.setenv("DB_POOL_TIMEOUT_SECONDS", "12")

    options = _pool_options()

    assert options["pool_size"] == 3
    assert options["max_overflow"] == 2
    assert options["pool_timeout"] == 12


@pytest.mark.parametrize("key", ["DATABASE_URL_ASYNC", "ASYNC_DATABASE_URL"])
def test_async_database_url_accepts_documented_names(monkeypatch, key):
    monkeypatch.delenv("DATABASE_URL_ASYNC", raising=False)
    monkeypatch.delenv("ASYNC_DATABASE_URL", raising=False)
    monkeypatch.setenv(key, "postgresql+asyncpg://app:secret@db/assessment")

    assert _resolve_async_database_url("postgresql://app:secret@db/assessment") == (
        "postgresql+asyncpg://app:secret@db/assessment"
    )


def test_async_database_url_infers_asyncpg(monkeypatch):
    monkeypatch.delenv("DATABASE_URL_ASYNC", raising=False)
    monkeypatch.delenv("ASYNC_DATABASE_URL", raising=False)

    assert _resolve_async_database_url("postgresql://app@db/assessment") == (
        "postgresql+asyncpg://app@db/assessment"
    )


def test_pool_rejects_invalid_capacity(monkeypatch):
    monkeypatch.setenv("DB_POOL_SIZE", "0")

    with pytest.raises(RuntimeError, match="DB_POOL_SIZE"):
        _pool_options()


def test_database_url_is_required_in_production():
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        _resolve_database_url("production", None)


def test_local_database_url_fallback_is_development_only():
    assert _resolve_database_url("development", None).endswith(
        "@localhost:5432/assessment_db"
    )


def test_connection_budget_includes_both_pools_and_all_replicas(monkeypatch):
    monkeypatch.setenv("DB_POOL_SIZE", "2")
    monkeypatch.setenv("DB_MAX_OVERFLOW", "1")
    monkeypatch.setenv("DB_REPLICA_COUNT", "2")
    monkeypatch.setenv("DB_WORKER_PROCESSES", "2")
    monkeypatch.setenv("DB_CONNECTION_RESERVE", "5")
    monkeypatch.setenv("DB_SERVER_MAX_CONNECTIONS", "53")
    assert _validate_connection_budget() == 24


def test_connection_budget_fails_closed_when_capacity_is_exceeded(monkeypatch):
    monkeypatch.setenv("DB_POOL_SIZE", "5")
    monkeypatch.setenv("DB_MAX_OVERFLOW", "5")
    monkeypatch.setenv("DB_REPLICA_COUNT", "2")
    monkeypatch.setenv("DB_WORKER_PROCESSES", "2")
    monkeypatch.setenv("DB_CONNECTION_RESERVE", "10")
    monkeypatch.setenv("DB_SERVER_MAX_CONNECTIONS", "70")
    with pytest.raises(RuntimeError, match="may use 80 connections"):
        _validate_connection_budget()
