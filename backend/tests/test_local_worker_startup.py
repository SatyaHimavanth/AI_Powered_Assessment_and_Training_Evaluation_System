from main import should_run_embedded_worker


def test_worker_starts_by_default_in_local_development(monkeypatch):
    monkeypatch.delenv("RUN_WORKER_IN_API", raising=False)
    monkeypatch.setenv("APP_ENV", "development")

    assert should_run_embedded_worker() is True


def test_worker_is_not_embedded_by_default_in_production(monkeypatch):
    monkeypatch.delenv("RUN_WORKER_IN_API", raising=False)
    monkeypatch.setenv("APP_ENV", "production")

    assert should_run_embedded_worker() is False


def test_worker_can_be_enabled_explicitly_in_production(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("RUN_WORKER_IN_API", "true")

    assert should_run_embedded_worker() is True


def test_worker_can_be_explicitly_disabled_for_compose_api_service(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("RUN_WORKER_IN_API", "false")

    assert should_run_embedded_worker() is False
