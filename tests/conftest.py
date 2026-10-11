import pytest
from fastapi.testclient import TestClient

from app import models  # noqa: F401  (registers tables)
from app.config import settings
from app.database import Base, SessionLocal, make_engine
from app.main import app


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path, monkeypatch):
    """Every test gets its own SQLite file and output folder, and jobs are
    processed synchronously so results are available right after POST."""
    engine = make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    SessionLocal.configure(bind=engine)

    monkeypatch.setattr(settings, "output_dir", tmp_path / "certificates")
    monkeypatch.setattr(settings, "sync_processing", True)
    yield
    engine.dispose()


@pytest.fixture
def client() -> TestClient:
    # Not used as a context manager, so the app's startup hook (which targets
    # the real database) does not run.
    return TestClient(app)


@pytest.fixture
def db():
    with SessionLocal() as session:
        yield session


def make_payload(count: int = 3, **overrides) -> dict:
    payload = {
        "course_name": "Python Bootcamp",
        "issue_date": "2026-10-01",
        "issuer": "Acme Academy",
        "recipients": [
            {"name": f"Student {i}", "email": f"student{i}@example.com"} for i in range(count)
        ],
    }
    payload.update(overrides)
    return payload
