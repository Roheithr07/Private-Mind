import sqlite3
import pytest
from backend.tests.conftest import TEST_DB_FILE


def test_approve_memory_persists_in_sqlite(client):
    """Verify approving a candidate memory persists it into SQLite and enables retrieval."""
    # 1. Chat to extract a candidate memory
    chat_res = client.post(
        "/chat",
        json={
            "message": "My favorite programming language for high performance is Rust.",
            "conversation_id": "conv_verify_test",
            "user_id": "default_user",
        },
        headers={"Origin": "http://127.0.0.1:5500"},
    )
    assert chat_res.status_code == 200
    chat_data = chat_res.json()
    candidates = chat_data.get("extracted_candidates", [])
    assert len(candidates) > 0, "Expected at least one candidate extracted"
    cand = candidates[0]
    assert cand["title"]
    assert cand["content"]

    # 2. Approve and save memory
    cand["category"] = "Skills"
    cand["action"] = "create"
    app_res = client.post(
        "/memories/approve",
        json={
            "candidates": [cand],
            "user_id": "default_user",
        },
        headers={"Origin": "http://127.0.0.1:5500"},
    )
    assert app_res.status_code == 200
    app_data = app_res.json()
    assert app_data["status"] == "approved"
    assert len(app_data["saved_memories"]) > 0
    saved = app_data["saved_memories"][0]
    saved_id = saved["id"]
    assert saved_id > 0
    assert saved["category"] == "Skills"

    # 3. Verify in SQLite database file
    conn = sqlite3.connect(str(TEST_DB_FILE))
    row = conn.cursor().execute(
        "SELECT id, title, content, category FROM memories WHERE id = ?", (saved_id,)
    ).fetchone()
    conn.close()
    assert row is not None, f"Memory {saved_id} must be in SQLite database"
    assert row[0] == saved_id
    assert row[3] == "Skills"

    # 4. Verify memory remains available after refresh (via GET /memories)
    list_res = client.get("/memories?user_id=default_user", headers={"Origin": "http://127.0.0.1:5500"})
    assert list_res.status_code == 200
    assert any(m["id"] == saved_id for m in list_res.json())

    # 5. Verify memory is retrieved in a new conversation session
    chat_new = client.post(
        "/chat",
        json={
            "message": "What programming language do I prefer for high performance?",
            "conversation_id": "conv_new_session_999",
            "user_id": "default_user",
        },
        headers={"Origin": "http://127.0.0.1:5500"},
    )
    assert chat_new.status_code == 200
    retrieved_ids = [m["memory_id"] for m in chat_new.json().get("memories_retrieved", [])]
    assert saved_id in retrieved_ids, f"Saved memory {saved_id} should be semantically retrieved in new conversation"


def test_reject_memory_does_not_save_to_database(client):
    """Verify rejected candidates are discarded and never written to SQLite."""
    reject_id = "cand_reject_unique_12345"
    title = "Should not be saved anywhere"
    res = client.post(
        "/memories/reject",
        json={"candidate_ids": [reject_id]},
        headers={"Origin": "http://127.0.0.1:5500"},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "rejected"

    conn = sqlite3.connect(str(TEST_DB_FILE))
    row = conn.cursor().execute("SELECT id FROM memories WHERE title = ?", (title,)).fetchone()
    conn.close()
    assert row is None, "Rejected candidate must NOT be persisted in SQLite"


def test_create_project_persists_in_sqlite(client):
    """Verify creating a project persists it into SQLite and returns it in project listings."""
    proj_payload = {
        "title": "Smart Campus Energy Monitor",
        "description": "IoT edge sensor system to monitor electrical load across buildings",
        "status": "active",
        "priority": "high",
        "deadline": "2026-12-31",
        "progress": 25,
        "tags": ["IoT", "ESP32", "Energy"],
        "theme": "teal",
    }
    proj_res = client.post(
        "/projects",
        json=proj_payload,
        headers={"Origin": "http://127.0.0.1:5500"},
    )
    assert proj_res.status_code == 201
    proj_data = proj_res.json()
    proj_id = proj_data["id"]
    assert proj_id > 0
    assert proj_data["title"] == "Smart Campus Energy Monitor"
    assert proj_data["status"] == "active"
    assert proj_data["priority"] == "high"

    # Verify in SQLite database file
    conn = sqlite3.connect(str(TEST_DB_FILE))
    row = conn.cursor().execute(
        "SELECT id, title, status, priority, progress FROM projects WHERE id = ?", (proj_id,)
    ).fetchone()
    conn.close()
    assert row is not None, f"Project {proj_id} must be in SQLite database"
    assert row[1] == "Smart Campus Energy Monitor"
    assert row[4] == 25

    # Verify project remains available after refresh (via GET /projects)
    projs_resp = client.get("/projects?user_id=default_user", headers={"Origin": "http://127.0.0.1:5500"})
    assert projs_resp.status_code == 200
    assert any(p["id"] == proj_id for p in projs_resp.json()["projects"])


def test_duplicate_approval_handling(client):
    """Verify approving a duplicate memory candidate returns the existing memory without duplicate row insertion."""
    cand = {
        "candidate_id": "cand_duplicate_test",
        "title": "Deduplication Verification",
        "content": "Deduplication content test fact",
        "category": "General",
        "user_id": "default_user",
    }
    res1 = client.post(
        "/memories/approve",
        json={"candidates": [cand]},
        headers={"Origin": "http://127.0.0.1:5500"},
    )
    assert res1.status_code == 200
    id1 = res1.json()["saved_memories"][0]["id"]

    # Submit second time (duplicate)
    res2 = client.post(
        "/memories/approve",
        json={"candidates": [cand]},
        headers={"Origin": "http://127.0.0.1:5500"},
    )
    assert res2.status_code == 200
    id2 = res2.json()["saved_memories"][0]["id"]
    assert id1 == id2, "Duplicate submission should return existing saved memory ID without duplicate insertion"


def test_validation_errors(client):
    """Verify validation errors return HTTP 422 Unprocessable Entity."""
    # Empty title for project should fail with 422
    res = client.post(
        "/projects",
        json={"title": ""},
        headers={"Origin": "http://127.0.0.1:5500"},
    )
    assert res.status_code == 422
