from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.main import app
from backend.database import Base, get_db
from backend.vector_index import get_vector_index

# Isolated test database in backend/data/
TEST_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
TEST_DATA_DIR.mkdir(parents=True, exist_ok=True)
TEST_DB_FILE = TEST_DATA_DIR / "test_suite.db"
TEST_DB_URL = f"sqlite:///{TEST_DB_FILE.as_posix()}"

test_engine = create_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(autouse=True)
def setup_and_teardown_db():
    """Ensure clean tables and fresh FAISS index before each test."""
    Base.metadata.create_all(bind=test_engine)
    get_vector_index()._init_faiss_index()
    yield
    Base.metadata.drop_all(bind=test_engine)
    get_vector_index()._init_faiss_index()


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client
