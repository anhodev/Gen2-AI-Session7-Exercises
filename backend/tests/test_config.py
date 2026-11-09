"""Test cấu hình: ghép URL Supabase, đọc số vòng tool. Không kết nối thật."""

import pytest
from fastapi.testclient import TestClient

from app.core.config import SQLITE_FALLBACK, Settings, build_database_url, get_settings, parse_positive_int
from app.main import create_app

DB_KEYS = ("DB_HOST", "DB_PORT", "DB_USER", "DB_PASSWORD", "DB_DATABASE", "DB_SSLMODE")


def clear_db_env(monkeypatch):
    for key in DB_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_supabase_url_from_env(monkeypatch):
    clear_db_env(monkeypatch)
    monkeypatch.setenv("DB_HOST", "aws-0-ap-southeast-1.pooler.supabase.com")
    monkeypatch.setenv("DB_USER", "postgres.abcxyz")
    monkeypatch.setenv("DB_PASSWORD", "secret")
    assert build_database_url() == (
        "postgresql+psycopg://postgres.abcxyz:secret"
        "@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres?sslmode=require"
    )


def test_password_with_special_characters_is_encoded(monkeypatch):
    clear_db_env(monkeypatch)
    monkeypatch.setenv("DB_HOST", "db.example.com")
    monkeypatch.setenv("DB_USER", "postgres")
    monkeypatch.setenv("DB_PASSWORD", "p@ss/w#rd")
    assert ":p%40ss%2Fw%23rd@db.example.com" in build_database_url()


def test_missing_db_env_falls_back_to_sqlite(monkeypatch):
    clear_db_env(monkeypatch)
    monkeypatch.setenv("DB_HOST", "db.example.com")  # thiếu user/password
    assert build_database_url() == SQLITE_FALLBACK


def test_no_api_key_always_uses_mock():
    assert Settings(openai_api_key="", mock_llm=False).use_mock
    assert not Settings(openai_api_key="sk-test", mock_llm=False).use_mock


def test_max_tool_rounds_from_env(monkeypatch):
    monkeypatch.setenv("MAX_TOOL_ROUNDS", "3")
    get_settings.cache_clear()
    try:
        assert get_settings().max_tool_rounds == 3
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize("value", ["0", "-2", "abc", "2.5"])
def test_bad_max_tool_rounds_is_rejected(value):
    with pytest.raises(ValueError):
        parse_positive_int(value, "MAX_TOOL_ROUNDS")


def test_health_reports_mock_and_sqlite(tmp_path):
    app = create_app(Settings(database_url=f"sqlite:///{tmp_path}/t.db", mock_llm=True))
    with TestClient(app) as client:
        body = client.get("/health").json()
    assert body == {"status": "ok", "llm": "mock", "database": "sqlite", "timezone": "Asia/Ho_Chi_Minh"}
