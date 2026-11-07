"""Isolated SQLite and FastAPI fixtures for backend behavior tests."""

from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

import app.models  # noqa: F401 - register all mappings
from app.core.config import Settings, get_settings
from app.database.migrations import migrate
from app.database.session import build_engine, get_db
from app.main import create_app
from app.secrets.codec import new_keyring, write_keyring


@pytest.fixture(autouse=True)
def private_keyring(tmp_path, monkeypatch):
    path = tmp_path / "keyring.json"
    write_keyring(path, new_keyring())
    monkeypatch.setenv("SECRET_KEYRING_FILE", str(path))
    get_settings.cache_clear()
    yield path
    get_settings.cache_clear()


@pytest.fixture
def test_engine(tmp_path: Path) -> Generator[Engine, None, None]:
    engine = build_engine(f"sqlite:///{tmp_path / 'sentinel-test.db'}")
    migrate(engine, "upgrade")
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def session_factory(test_engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(
        bind=test_engine,
        autoflush=False,
        expire_on_commit=False,
    )


@pytest.fixture
def db_session(
    session_factory: sessionmaker[Session],
) -> Generator[Session, None, None]:
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def api_app(
    test_engine: Engine,
    session_factory: sessionmaker[Session],
):
    settings = Settings(
        database_url="sqlite://",
        cors_origins="http://localhost:3000",
    )
    application = create_app(settings, database_engine=test_engine)

    def override_db() -> Generator[Session, None, None]:
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    application.dependency_overrides[get_db] = override_db
    return application


@pytest.fixture
def api_client(api_app) -> Generator[TestClient, None, None]:
    with TestClient(api_app) as client:
        yield client


@pytest.fixture
def valid_target_payload() -> dict[str, Any]:
    return {
        "name": "Support Assistant",
        "endpoint_url": "http://demo-target:8001/chat",
        "http_method": "POST",
        "api_key": "fake-test-key",
        "request_template": {"payload": {"messages": [{"content": ""}]}},
        "prompt_field": "payload.messages.0.content",
        "response_field": "result.answer",
    }


@pytest.fixture
def demo_app(monkeypatch):
    """Load the demo under a private package name; both services own `app`."""
    import importlib.util
    import sys

    directory = Path(__file__).resolve().parents[2] / "demo_target/app"
    spec = importlib.util.spec_from_file_location(
        "sentinel_demo_fixture",
        directory / "main.py",
        submodule_search_locations=[str(directory)],
    )
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module.app
