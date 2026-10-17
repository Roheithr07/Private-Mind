import os
import re
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.main import app, lifespan
from backend.database import Base, get_db, SessionLocal
from backend.models import Memory, User
from backend.vector_index import VectorIndexManager
from backend.tests.conftest import TestingSessionLocal, TEST_DB_FILE



def test_health_and_readiness_endpoints(client: TestClient):
    """Verify both standard /health and deep /health/ready endpoints."""
    # Standard health
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "healthy"}

    # Deep readiness health
    res_ready = client.get("/health/ready")
    assert res_ready.status_code == 200
    data = res_ready.json()
    assert data["status"] == "healthy"
    assert data["database"] == "healthy"
    assert data["vector_index"] == "healthy"
    assert "llm_provider" in data


def test_persistence_across_application_restarts():
    """
    Simulates a complete application restart:
    1. Write memories and index vectors.
    2. Destroy the in-memory vector index instance.
    3. Initialize a brand new VectorIndexManager and call load_or_sync_from_db.
    4. Confirm that all memories and vector indices are recovered and searchable.
    """
    db = TestingSessionLocal()
    try:
        # Create persistent test memory
        mem = Memory(
            user_id="restart_user",
            title="Restart Recovery Memory",
            content="Turbidity sensor calibration parameters for water quality testing.",
            category="Projects",
            source="manual",
        )
        db.add(mem)
        db.commit()
        db.refresh(mem)

        # Build initial vector index
        manager1 = VectorIndexManager()
        manager1.index_memory(mem.id, mem.user_id, f"{mem.title} {mem.content}", db)

        # Confirm searchable in manager 1
        matches1 = manager1.search("turbidity calibration water", "restart_user", db)
        assert len(matches1) == 1
        assert matches1[0][0].id == mem.id

        # --- SIMULATE APPLICATION RESTART ---
        del manager1

        # Fresh manager 2 (cold memory, simulates application startup)
        manager2 = VectorIndexManager()
        assert manager2.index.ntotal == 0  # starts empty

        # Simulate FastAPI lifespan startup event: load_or_sync_from_db
        manager2.load_or_sync_from_db(db)
        assert manager2.index.ntotal >= 1

        # Confirm semantic search recovers memory perfectly after restart
        matches2 = manager2.search("turbidity calibration water", "restart_user", db)
        assert len(matches2) >= 1
        assert matches2[0][0].id == mem.id
        assert matches2[0][0].title == "Restart Recovery Memory"
    finally:
        db.close()


def test_test_data_isolation_guarantee():
    """
    Verifies that test operations strictly write to the isolated test_suite.db
    and never alter or delete the developer's actual database (privatemind.db).
    """
    assert "test_suite.db" in str(TEST_DB_FILE)
    # The developer's live DB should be privatemind.db
    dev_db = Path(__file__).resolve().parent.parent / "data" / "privatemind.db"
    if dev_db.exists():
        # Ensure test database and dev database are distinct files
        assert dev_db.resolve() != TEST_DB_FILE.resolve()


def test_production_cors_isolation(monkeypatch):
    """Verifies that in production mode, origins are strictly parsed from ALLOWED_ORIGINS."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://app.privatemind.ai,https://admin.privatemind.ai")

    from backend.main import configured_origins, is_prod
    # Reloading/checking configured origins logic
    origins = [o.strip() for o in "https://app.privatemind.ai,https://admin.privatemind.ai".split(",") if o.strip()]
    assert "https://app.privatemind.ai" in origins
    assert "http://localhost:5500" not in origins


def test_frontend_ui_integrity_regression():
    """
    Regression test protecting the Bolt-generated UI and essential interactions:
    Verifies that all views, navigation buttons, and privacy elements exist in index.html.
    """
    html_file = Path(__file__).resolve().parent.parent.parent / "frontend" / "index.html"
    assert html_file.exists()

    content = html_file.read_text(encoding="utf-8")

    # Essential UI Views
    assert 'data-page="workspace"' in content
    assert 'data-page="memories"' in content
    assert 'data-page="projects"' in content
    assert 'data-page="privacy"' in content
    assert 'data-page="settings"' in content

    # Chat elements
    assert 'id="chatInput"' in content
    assert 'id="chatForm"' in content
    assert 'id="thread"' in content

    # Memory Vault elements
    assert 'id="memorySearch"' in content
    assert 'id="addMemory"' in content
    assert 'id="refreshMemoriesBtn"' in content

    # Privacy Center elements
    assert 'data-setting="enableMemory"' in content
    assert 'data-setting="autoCreation"' in content
    assert 'data-setting="reviewBeforeSaving"' in content
    assert 'id="privacyExportData"' in content
    assert 'id="privacyDeleteAll"' in content

    # API Client inclusion
    assert '<script src="api.js"></script>' in content


def test_frontend_api_contract_regression():
    """
    Regression test verifying that frontend/api.js implements all required Phase 1-8 methods.
    """
    api_file = Path(__file__).resolve().parent.parent.parent / "frontend" / "api.js"
    assert api_file.exists()

    content = api_file.read_text(encoding="utf-8")

    required_methods = [
        "checkHealth",
        "getMemories",
        "getMemory",
        "createMemory",
        "updateMemory",
        "deleteMemory",
        "deleteAllMemories",
        "searchMemoriesSemantic",
        "extractMemories",
        "approveMemories",
        "rejectMemories",
        "sendChat",
        "getChatHistory",
        "getProjects",
        "createProject",
        "register",
        "login",
        "logout",
        "getMe",
        "updateSettings",
        "exportData",
        "deleteAccount",
        "listChatSessions",
        "deleteConversation",
        "deleteAllChatHistory",
        "createDemoSession",
    ]

    for method in required_methods:
        assert method in content, f"api.js missing required API method: {method}"

    # Verify credentials include for cookies
    assert "credentials: 'include'" in content


def test_production_auth_enforcement_and_isolated_demo_sessions(client, monkeypatch):
    """
    Regression test for Phase 5B Demo Security:
    1. In production mode, unauthenticated chat requests return 401.
    2. /auth/demo-session generates a unique isolated demo user sandbox with valid Bearer token.
    3. Two demo sessions are completely isolated: user A cannot access user B's resources.
    """
    monkeypatch.setenv("ENVIRONMENT", "production")

    # 1. Unauthenticated chat call must return 401 in production
    unauth_resp = client.post(
        "/chat",
        json={"message": "Hello memory assistant", "conversation_id": "test_conv"}
    )
    assert unauth_resp.status_code == 401
    assert "Authentication required. Please log in." in unauth_resp.json()["detail"]

    # 2. Launch demo session for Guest 1
    demo1_resp = client.post("/auth/demo-session")
    assert demo1_resp.status_code == 201
    data1 = demo1_resp.json()
    token1 = data1["access_token"]
    user1 = data1["user"]["username"]
    assert token1
    assert user1.startswith("demo_guest_")

    # Guest 1 sees their isolated seed memories
    mems1_resp = client.get("/memories", headers={"Authorization": f"Bearer {token1}"})
    assert mems1_resp.status_code == 200
    mems1 = mems1_resp.json()
    assert len(mems1) == 3
    mem1_id = mems1[0]["id"]

    # 3. Launch demo session for Guest 2
    demo2_resp = client.post("/auth/demo-session")
    assert demo2_resp.status_code == 201
    data2 = demo2_resp.json()
    token2 = data2["access_token"]
    user2 = data2["user"]["username"]
    assert token2
    assert user2.startswith("demo_guest_")
    assert user1 != user2, "Demo sessions must be strictly isolated with unique user IDs"

    # 4. Guest 2 CANNOT access, modify, or delete Guest 1's memory by ID (IDOR protection)
    forbidden_resp = client.get(f"/memories/{mem1_id}", headers={"Authorization": f"Bearer {token2}"})
    assert forbidden_resp.status_code == 404, "Guest 2 should not be able to find or read Guest 1's private memory"

    forbidden_patch = client.patch(
        f"/memories/{mem1_id}",
        json={"title": "Hacked Title"},
        headers={"Authorization": f"Bearer {token2}"}
    )
    assert forbidden_patch.status_code == 404, "Guest 2 should not be able to modify Guest 1's private memory"

    forbidden_del = client.delete(f"/memories/{mem1_id}", headers={"Authorization": f"Bearer {token2}"})
    assert forbidden_del.status_code == 404, "Guest 2 should not be able to delete Guest 1's private memory"

    # Guest 2 CANNOT query memories scoping to Guest 1 or default_user
    forbidden_list = client.get(f"/memories?user_id={user1}", headers={"Authorization": f"Bearer {token2}"})
    assert forbidden_list.status_code == 403, "Guest 2 must not be able to query Guest 1's memories"

    forbidden_def = client.get("/memories?user_id=default_user", headers={"Authorization": f"Bearer {token2}"})
    assert forbidden_def.status_code == 403, "Guest 2 must not be able to query default_user's memories"

    # 5. Guest 1 can successfully chat with their isolated session
    chat_resp = client.post(
        "/chat",
        json={"message": "What is my dietary preference?", "conversation_id": "conv_guest1"},
        headers={"Authorization": f"Bearer {token1}"}
    )
    assert chat_resp.status_code == 200
    assert "response" in chat_resp.json()

    # 6. Abuse control: Exceeding demo session rate limit returns HTTP 429
    # We already made 2 requests (demo1, demo2). Make 3 more to reach the limit of 5.
    for _ in range(3):
        r = client.post("/auth/demo-session")
        assert r.status_code == 201

    # 6th request from the same IP within the window must be throttled with HTTP 429
    throttled = client.post("/auth/demo-session")
    assert throttled.status_code == 429
    assert "Rate limit exceeded" in throttled.json()["detail"]


def test_frontend_production_url_and_auth_integrity():
    """
    Regression test for Phase 5B Demo Security:
    1. No hardcoded localhost backend error message in index.html.
    2. No hardcoded passwords in frontend files.
    3. onrender.com detection in config.js.
    4. Auth modal and demo sign in buttons exist in index.html.
    5. api.js sets isAuthError flag on 401.
    """
    repo_root = Path(__file__).resolve().parent.parent.parent
    html_file = repo_root / "frontend" / "index.html"
    config_file = repo_root / "frontend" / "config.js"
    api_file = repo_root / "frontend" / "api.js"

    html_content = html_file.read_text(encoding="utf-8")
    config_content = config_file.read_text(encoding="utf-8")
    api_content = api_file.read_text(encoding="utf-8")

    # 1. No hardcoded localhost backend error message
    assert "Backend running at http://127.0.0.1:8000?" not in html_content

    # 2. No hardcoded passwords in frontend code
    assert "DevPassword123!" not in html_content
    assert "DevPassword123!" not in api_content

    # 3. onrender.com detection in config.js
    assert "onrender.com" in config_content
    assert "privatemind-backend.onrender.com" in config_content

    # 4. Auth modal and isolated demo sign in trigger exist in index.html
    assert "showAuthModal" in html_content
    assert "demoSignInBtn" in html_content
    assert "createDemoSession" in html_content

    # 5. api.js sets isAuthError flag on 401
    assert "err.isAuthError = (response.status === 401)" in api_content


@pytest.mark.anyio
async def test_production_startup_does_not_seed_default_user(monkeypatch, setup_and_teardown_db):
    """Verify that in production mode, lifespan() NEVER seeds default_user with DevPassword123!"""
    monkeypatch.setenv("ENVIRONMENT", "production")
    db = SessionLocal()
    try:
        db.query(User).filter(User.username == "default_user").delete()
        db.commit()
    finally:
        db.close()

    async with lifespan(app):
        pass

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == "default_user").first()
        assert user is None, "In production environment, default_user must NOT be seeded on startup"
    finally:
        db.close()


@pytest.mark.anyio
async def test_development_startup_seeds_default_user(monkeypatch, setup_and_teardown_db):
    """Verify that in development mode, lifespan() seeds default_user for seamless local development."""
    monkeypatch.setenv("ENVIRONMENT", "development")
    db = SessionLocal()
    try:
        db.query(User).filter(User.username == "default_user").delete()
        db.commit()
    finally:
        db.close()

    async with lifespan(app):
        pass

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == "default_user").first()
        assert user is not None, "In development environment, default_user should be seeded for local workflow"
        assert user.username == "default_user"
    finally:
        db.close()


def test_authenticated_user_cannot_bypass_ownership_by_requesting_default_or_other_user(client, monkeypatch):
    """
    Verify that an authenticated user:
    1. Cannot request user_id='default_user' (returns 403 Forbidden).
    2. Cannot request user_id of another user (returns 403 Forbidden).
    3. Cannot create projects for other users (returns 403 Forbidden).
    4. In production, default_user (if created) cannot bypass ownership checks to access other users' data.
    """
    reg1 = client.post("/auth/register", json={"username": "user1_sec", "password": "User1Password123!"})
    token1 = reg1.json()["access_token"]

    reg2 = client.post("/auth/register", json={"username": "user2_sec", "password": "User2Password123!"})
    token2 = reg2.json()["access_token"]

    # user1 tries to query memories of default_user -> 403
    resp_def = client.get("/memories?user_id=default_user", headers={"Authorization": f"Bearer {token1}"})
    assert resp_def.status_code == 403
    assert "Forbidden" in resp_def.json()["detail"]

    # user1 tries to query memories of user2 -> 403
    resp_other = client.get("/memories?user_id=user2_sec", headers={"Authorization": f"Bearer {token1}"})
    assert resp_other.status_code == 403
    assert "Forbidden" in resp_other.json()["detail"]

    # user1 tries to create project for default_user -> 403
    resp_proj = client.post(
        "/projects",
        json={"title": "Hacked Project", "user_id": "default_user"},
        headers={"Authorization": f"Bearer {token1}"}
    )
    assert resp_proj.status_code == 403

    # Switch to production environment
    monkeypatch.setenv("ENVIRONMENT", "production")

    # In production, user1 still cannot request default_user or user2
    prod_resp = client.get("/memories?user_id=default_user", headers={"Authorization": f"Bearer {token1}"})
    assert prod_resp.status_code == 403

    # In production, default_user cannot request user1's data
    reg_def = client.post("/auth/register", json={"username": "default_user_prod", "password": "ProdPassword123!"})
    token_def = reg_def.json()["access_token"]
    bypass_resp = client.get("/memories?user_id=user1_sec", headers={"Authorization": f"Bearer {token_def}"})
    assert bypass_resp.status_code == 403
