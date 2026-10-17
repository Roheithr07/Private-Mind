import os
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# Dedicated backend/data directory
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_DB_FILE = DATA_DIR / "privatemind.db"
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DEFAULT_DB_FILE.as_posix()}")

# Auto-create parent directory for SQLite files
if DATABASE_URL.startswith("sqlite:///"):
    raw_path = DATABASE_URL[len("sqlite:///"):]
    # Skip in-memory databases like sqlite:///:memory:
    if raw_path != ":memory:" and not raw_path.startswith(":memory:"):
        db_file_path = Path(raw_path)
        if not db_file_path.is_absolute():
            db_file_path = (BASE_DIR / db_file_path).resolve()
        db_file_path.parent.mkdir(parents=True, exist_ok=True)

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    echo=False,
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

Base = declarative_base()


def get_db():
    """Dependency that provides a database session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Creates database tables automatically on startup."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        from . import models  # noqa: F401
    except ImportError:
        import models  # noqa: F401
    Base.metadata.create_all(bind=engine)

    # Ensure schema migrations for existing SQLite databases
    if DATABASE_URL.startswith("sqlite"):
        try:
            with engine.connect() as conn:
                cols = [r[1] for r in conn.exec_driver_sql("PRAGMA table_info(project_notes)").fetchall()]
                if cols and "is_memory" not in cols:
                    conn.exec_driver_sql("ALTER TABLE project_notes ADD COLUMN is_memory BOOLEAN DEFAULT 0")
                    conn.commit()
        except Exception:
            pass
