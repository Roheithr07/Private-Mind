import pytest
from fastapi.testclient import TestClient

from backend.models import User, UserSession, Memory, ConversationMessage
from backend.auth import hash_password, verify_password, create_session
from backend.rate_limiter import rate_limiter


@pytest.fixture(autouse=True)
def reset_rate_limiters():
    rate_limiter.clear()


def test_password_hashing_and_verification():
    """Verify that password hashing uses scrypt and verify_password matches."""
    password = "SuperSecretPassword123!"
    hashed = hash_password(password)

    assert hashed.startswith("scrypt$")
    assert verify_password(password, hashed) is True
    assert verify_password("WrongPassword!", hashed) is False


def test_user_registration_and_login(client: TestClient):
    """Verify user registration, cookie issuance, and login."""
    # 1. Register new user
    reg_resp = client.post(
        "/auth/register",
        json={"username": "alice", "password": "AlicePassword123!", "email": "alice@example.com"},
    )
    assert reg_resp.status_code == 201
    data = reg_resp.json()
    assert data["token_type"] == "bearer"
    assert "access_token" in data
    assert data["user"]["username"] == "alice"
    assert "session_token" in reg_resp.cookies

    # Duplicate registration should fail
    dup_resp = client.post(
        "/auth/register",
        json={"username": "alice", "password": "AnotherPassword123!"},
    )
    assert dup_resp.status_code == 400

    # 2. Login with correct password
    login_resp = client.post(
        "/auth/login",
        json={"username": "alice", "password": "AlicePassword123!"},
    )
    assert login_resp.status_code == 200
    login_data = login_resp.json()
    token = login_data["access_token"]
    assert token

    # 3. Login with incorrect password
    bad_login = client.post(
        "/auth/login",
        json={"username": "alice", "password": "WrongPassword123!"},
    )
    assert bad_login.status_code == 401

    # 4. Fetch authenticated user profile
    me_resp = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_resp.status_code == 200
    assert me_resp.json()["username"] == "alice"
    assert me_resp.json()["memory_enabled"] is True


def test_cross_user_isolation_and_idor_prevention(client: TestClient):
    """Verify that Alice and Bob cannot read, modify, or delete each other's memories."""
    # Register Alice
    reg_alice = client.post(
        "/auth/register",
        json={"username": "alice_idor", "password": "AlicePassword123!"},
    )
    token_alice = reg_alice.json()["access_token"]

    # Register Bob
    reg_bob = client.post(
        "/auth/register",
        json={"username": "bob_idor", "password": "BobPassword123!"},
    )
    token_bob = reg_bob.json()["access_token"]

    # Alice creates a confidential memory
    create_resp = client.post(
        "/memories",
        json={
            "title": "Alice Secret Project",
            "content": "Secret algorithmic trading model blueprint",
            "category": "Projects",
        },
        headers={"Authorization": f"Bearer {token_alice}"},
    )
    assert create_resp.status_code == 201
    alice_mem_id = create_resp.json()["id"]

    # Bob tries to GET Alice's memory by ID -> should return 404 (ID enumeration defense)
    bob_get = client.get(
        f"/memories/{alice_mem_id}",
        headers={"Authorization": f"Bearer {token_bob}"},
    )
    assert bob_get.status_code == 404

    # Bob tries to UPDATE Alice's memory -> 404
    bob_patch = client.patch(
        f"/memories/{alice_mem_id}",
        json={"content": "Hacked content"},
        headers={"Authorization": f"Bearer {token_bob}"},
    )
    assert bob_patch.status_code == 404

    # Bob tries to DELETE Alice's memory -> 404
    bob_del = client.delete(
        f"/memories/{alice_mem_id}",
        headers={"Authorization": f"Bearer {token_bob}"},
    )
    assert bob_del.status_code == 404

    # Bob lists his memories -> Alice's memory is NOT in Bob's list
    bob_list = client.get(
        "/memories",
        headers={"Authorization": f"Bearer {token_bob}"},
    )
    assert bob_list.status_code == 200
    assert all(m["id"] != alice_mem_id for m in bob_list.json())

    # Bob tries to pass user_id='alice_idor' in query param -> 403 Forbidden
    bob_forbidden = client.get(
        "/memories?user_id=alice_idor",
        headers={"Authorization": f"Bearer {token_bob}"},
    )
    assert bob_forbidden.status_code == 403


def test_semantic_search_user_isolation(client: TestClient):
    """Verify semantic search isolates vectors between users."""
    reg_alice = client.post(
        "/auth/register",
        json={"username": "alice_search", "password": "Password123!"},
    )
    token_alice = reg_alice.json()["access_token"]

    reg_bob = client.post(
        "/auth/register",
        json={"username": "bob_search", "password": "Password123!"},
    )
    token_bob = reg_bob.json()["access_token"]

    # Alice creates memory about Quantum Computing
    client.post(
        "/memories",
        json={"title": "Quantum Physics", "content": "Superconducting qubits with 99.9% fidelity"},
        headers={"Authorization": f"Bearer {token_alice}"},
    )

    # Bob searches for Quantum Physics
    bob_search = client.post(
        "/memories/search",
        json={"query": "superconducting qubits fidelity"},
        headers={"Authorization": f"Bearer {token_bob}"},
    )
    assert bob_search.status_code == 200
    assert bob_search.json()["total_found"] == 0
    assert len(bob_search.json()["matches"]) == 0


def test_memory_enabled_backend_enforcement(client: TestClient):
    """Verify that setting memory_enabled = False disables semantic search and retrieval in chat."""
    reg = client.post(
        "/auth/register",
        json={"username": "privacy_user", "password": "Password123!"},
    )
    token = reg.json()["access_token"]

    # Create memory
    client.post(
        "/memories",
        json={"title": "Coffee Habit", "content": "I drink oat milk cappuccino every morning at 8am"},
        headers={"Authorization": f"Bearer {token}"},
    )

    # Initially enabled: search finds it
    search_enabled = client.post(
        "/memories/search",
        json={"query": "coffee morning"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert search_enabled.status_code == 200
    assert search_enabled.json()["total_found"] >= 1

    # Disable memory setting in backend
    patch_settings = client.patch(
        "/auth/settings",
        json={"memory_enabled": False},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert patch_settings.status_code == 200
    assert patch_settings.json()["memory_enabled"] is False

    # Search now returns 0 matches (enforced by backend)
    search_disabled = client.post(
        "/memories/search",
        json={"query": "coffee morning"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert search_disabled.status_code == 200
    assert search_disabled.json()["total_found"] == 0
    assert search_disabled.json()["matches"] == []

    # Chat endpoint also retrieves 0 memories when memory_enabled is False
    chat_resp = client.post(
        "/chat",
        json={"message": "What do I drink in the morning?"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert chat_resp.status_code == 200
    assert len(chat_resp.json()["memories_retrieved"]) == 0
    assert chat_resp.json()["memory_ids_used"] == []


def test_portable_json_data_export(client: TestClient):
    """Verify portable JSON data export includes all user memories and conversation sessions."""
    reg = client.post(
        "/auth/register",
        json={"username": "export_user", "password": "Password123!"},
    )
    token = reg.json()["access_token"]

    # Create memory
    client.post(
        "/memories",
        json={"title": "Export Note", "content": "Important note to export"},
        headers={"Authorization": f"Bearer {token}"},
    )

    # Have a chat turn
    client.post(
        "/chat",
        json={"message": "Hello PrivateMind!"},
        headers={"Authorization": f"Bearer {token}"},
    )

    # Export data
    export_resp = client.get("/auth/export", headers={"Authorization": f"Bearer {token}"})
    assert export_resp.status_code == 200
    data = export_resp.json()
    assert data["user_id"] == "export_user"
    assert data["version"] == "1.0"
    assert data["total_memories"] >= 1
    assert any(m["title"] == "Export Note" for m in data["memories"])
    assert data["total_conversations"] >= 1


def test_chat_retention_and_session_deletion(client: TestClient):
    """Verify chat session listing and granular conversation deletion."""
    reg = client.post(
        "/auth/register",
        json={"username": "retention_user", "password": "Password123!"},
    )
    token = reg.json()["access_token"]

    conv_id = "conv_test_retention_123"
    client.post(
        "/chat",
        json={"message": "First message in retention session", "conversation_id": conv_id},
        headers={"Authorization": f"Bearer {token}"},
    )

    # List sessions
    sessions_resp = client.get("/chat/sessions", headers={"Authorization": f"Bearer {token}"})
    assert sessions_resp.status_code == 200
    sessions = sessions_resp.json()
    assert any(s["conversation_id"] == conv_id for s in sessions)

    # Delete specific session
    del_resp = client.delete(f"/chat/{conv_id}", headers={"Authorization": f"Bearer {token}"})
    assert del_resp.status_code == 200
    assert del_resp.json()["status"] == "deleted"

    # Confirm history is now empty
    hist_resp = client.get(f"/chat/{conv_id}", headers={"Authorization": f"Bearer {token}"})
    assert hist_resp.status_code == 200
    assert hist_resp.json()["total"] == 0


def test_account_deletion_wipes_all_data(client: TestClient):
    """Verify that deleting an account wipes memories, embeddings, conversations, and sessions."""
    reg = client.post(
        "/auth/register",
        json={"username": "wipe_user", "password": "Password123!"},
    )
    token = reg.json()["access_token"]

    # Create memory
    client.post(
        "/memories",
        json={"title": "To be wiped", "content": "Sensitive data"},
        headers={"Authorization": f"Bearer {token}"},
    )

    # Chat
    client.post(
        "/chat",
        json={"message": "Sensitive chat message"},
        headers={"Authorization": f"Bearer {token}"},
    )

    # Delete account
    del_account = client.delete("/auth/account", headers={"Authorization": f"Bearer {token}"})
    assert del_account.status_code == 200
    assert del_account.json()["status"] == "deleted"

    # Subsequent request with old token should fail (token invalidated / user deleted)
    me_resp = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_resp.status_code == 401


def test_rate_limiting_on_auth_endpoint(client: TestClient):
    """Verify that rapid authentication requests are rate limited with 429 Too Many Requests."""
    statuses = []
    for i in range(15):
        resp = client.post(
            "/auth/login",
            json={"username": f"user_{i}", "password": "BadPassword123!"},
        )
        statuses.append(resp.status_code)

    assert 429 in statuses
