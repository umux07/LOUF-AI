import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes import _attempts
from app.database.base import Base
from app.database.session import get_db
from app.main import app
from app.models import entities  # noqa: F401

test_engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSession = sessionmaker(bind=test_engine, autoflush=False, expire_on_commit=False)


@pytest.fixture
def client():
    _attempts.clear()
    Base.metadata.create_all(test_engine)

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(test_engine)
    _attempts.clear()


def register(client: TestClient, email: str) -> TestClient:
    csrf = client.get("/api/v1/auth/csrf").json()["csrf_token"]
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "a-strong-test-password"},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 201, response.text
    return client
