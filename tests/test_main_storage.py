import os

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("DB_USER", "test-user")
os.environ.setdefault("DB_PASS", "test-pass")
os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_NAME", "test-db")

import main


class DummyRedisStorage:
    @staticmethod
    def from_url(url: str):
        return {"kind": "redis", "url": url}


def test_create_fsm_storage_redis_success(monkeypatch):
    monkeypatch.setattr(main.config, "FSM_STORAGE", "redis")
    monkeypatch.setattr(main.config, "REDIS_URL", "redis://redis:6379/0")
    monkeypatch.setattr(main, "RedisStorage", DummyRedisStorage)

    storage = main.create_fsm_storage()

    assert storage == {"kind": "redis", "url": "redis://redis:6379/0"}


def test_create_fsm_storage_redis_fallback_when_import_missing(monkeypatch):
    monkeypatch.setattr(main.config, "FSM_STORAGE", "redis")
    monkeypatch.setattr(main, "RedisStorage", None)

    storage = main.create_fsm_storage()

    assert isinstance(storage, main.MemoryStorage)


def test_create_fsm_storage_memory(monkeypatch):
    monkeypatch.setattr(main.config, "FSM_STORAGE", "memory")

    storage = main.create_fsm_storage()

    assert isinstance(storage, main.MemoryStorage)
