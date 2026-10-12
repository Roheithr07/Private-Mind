import pytest
from backend.models import Memory
from backend.extractor import (
    BaseExtractionProvider,
    DeterministicExtractorProvider,
    get_extractor,
    contains_secrets,
)


def test_extractor_provider_interface():
    """Verify provider implements BaseExtractionProvider interface."""
    extractor = get_extractor()
    assert isinstance(extractor, BaseExtractionProvider)
    assert isinstance(extractor, DeterministicExtractorProvider)


def test_secrets_detection():
    """Verify secrets and credentials are never treated as facts."""
    assert contains_secrets("My key is sk-1234567890abcdef1234567890")
    assert contains_secrets("password = MyPassword123")
    assert contains_secrets("Authorization: Bearer my_secret_token_12345")
    assert not contains_secrets("I'm learning Python and C++.")


def test_acceptance_scenario_extraction(client):
    """
    Acceptance scenario:
    Given message: "I'm learning Python and building a water quality monitoring project using ESP32."
    The extraction service should identify candidate facts about learning Python and the ESP32 project,
    classify them appropriately, and allow them to be approved and stored.
    """
    message = "I'm learning Python and building a water quality monitoring project using ESP32."
    
    # 1. Extract with review_before_saving (default True)
    res = client.post("/memories/extract", json={"message": message, "user_id": "test_user"})
    assert res.status_code == 200
    data = res.json()
    assert data["review_required"] is True
    assert data["auto_saved"] is False
    assert len(data["candidates"]) == 2

    # Check Candidate 1: Learning Python (Skills)
    cand_python = next(c for c in data["candidates"] if "Python" in c["title"])
    assert cand_python["category"] == "Skills"
    assert cand_python["is_durable"] is True
    assert cand_python["confidence"] >= 0.85
    assert cand_python["action"] == "create"

    # Check Candidate 2: Water Quality Monitoring Project (Projects)
    cand_esp32 = next(c for c in data["candidates"] if "Water Quality" in c["title"])
    assert cand_esp32["category"] == "Projects"
    assert cand_esp32["is_durable"] is True
    assert cand_esp32["confidence"] >= 0.85
    assert cand_esp32["action"] == "create"

    # Verify nothing was saved to the database yet (review before saving)
    db_memories = client.get("/memories?user_id=test_user").json()
    assert len(db_memories) == 0

    # 2. Approve both candidates
    approve_payload = {
        "user_id": "test_user",
        "candidates": [
            {
                "candidate_id": cand_python["candidate_id"],
                "title": cand_python["title"],
                "content": cand_python["content"],
                "category": cand_python["category"],
                "action": "create",
            },
            {
                "candidate_id": cand_esp32["candidate_id"],
                "title": cand_esp32["title"],
                "content": cand_esp32["content"],
                "category": cand_esp32["category"],
                "action": "create",
            },
        ],
    }
    approve_res = client.post("/memories/approve", json=approve_payload)
    assert approve_res.status_code == 200
    assert len(approve_res.json()["saved_memories"]) == 2

    # Verify both are now in SQLite
    saved_db = client.get("/memories?user_id=test_user").json()
    assert len(saved_db) == 2


def test_repeated_message_duplicate_detection(client):
    """
    Acceptance scenario:
    A repeated message should not create unnecessary duplicate memories.
    """
    message = "I'm learning Python and building a water quality monitoring project using ESP32."
    
    # First extraction & approval
    res1 = client.post("/memories/extract", json={"message": message, "user_id": "test_user"})
    cands1 = res1.json()["candidates"]
    client.post("/memories/approve", json={
        "user_id": "test_user",
        "candidates": [
            {"title": c["title"], "content": c["content"], "category": c["category"], "action": "create"}
            for c in cands1
        ],
    })
    assert len(client.get("/memories?user_id=test_user").json()) == 2

    # Second extraction with the exact same message
    res2 = client.post("/memories/extract", json={"message": message, "user_id": "test_user"})
    cands2 = res2.json()["candidates"]
    assert len(cands2) == 2

    # Both candidates must be identified as duplicates
    for c in cands2:
        assert c["action"] == "duplicate"
        assert c["existing_memory_id"] is not None

    # Approving duplicates with action duplicate/skip must not add new records
    client.post("/memories/approve", json={
        "user_id": "test_user",
        "candidates": [
            {
                "title": c["title"],
                "content": c["content"],
                "category": c["category"],
                "action": "duplicate",
                "existing_memory_id": c["existing_memory_id"],
            }
            for c in cands2
        ],
    })
    # DB count must still be 2, not 4
    assert len(client.get("/memories?user_id=test_user").json()) == 2


def test_update_existing_memory_via_extraction(client):
    """Verify that related new details trigger an update action."""
    # Seed initial project memory
    init_res = client.post("/memories", json={
        "title": "Water Quality Monitoring Project",
        "content": "Working on a water quality monitoring project using ESP32.",
        "category": "Projects",
        "user_id": "test_user",
    })
    mem_id = init_res.json()["id"]

    # Updated statement
    update_msg = "building an advanced water quality monitoring system with cloud telemetry"
    res = client.post("/memories/extract", json={"message": update_msg, "user_id": "test_user"})
    cands = res.json()["candidates"]
    assert len(cands) >= 1
    cand = cands[0]
    assert cand["action"] == "update"
    assert cand["existing_memory_id"] == mem_id

    # Approve update
    approve_res = client.post("/memories/approve", json={
        "user_id": "test_user",
        "candidates": [{
            "title": cand["title"],
            "content": cand["content"],
            "category": cand["category"],
            "action": "update",
            "existing_memory_id": mem_id,
        }],
    })
    assert approve_res.status_code == 200
    assert len(approve_res.json()["updated_memories"]) == 1

    # Verify existing memory content was updated in SQLite
    updated_db = client.get(f"/memories/{mem_id}").json()
    assert "cloud telemetry" in updated_db["content"].lower() or "advanced" in updated_db["content"].lower()


def test_reject_memories(client):
    """Verify rejecting candidates discards them without storing."""
    res = client.post("/memories/extract", json={
        "message": "I prefer vegetarian food.",
        "user_id": "test_user",
    })
    cands = res.json()["candidates"]
    assert len(cands) == 1
    cand_id = cands[0]["candidate_id"]

    reject_res = client.post("/memories/reject", json={
        "candidate_ids": [cand_id],
        "reason": "Not relevant right now",
    })
    assert reject_res.status_code == 200
    assert reject_res.json()["status"] == "rejected"
    assert reject_res.json()["rejected_count"] == 1

    # DB remains empty
    assert len(client.get("/memories?user_id=test_user").json()) == 0


def test_greetings_and_filler_ignored(client):
    """Verify conversational filler and greetings produce zero memories."""
    greetings = [
        "Hello!",
        "Hi, good morning!",
        "Thanks so much, great job!",
        "Okay, cool.",
    ]
    for msg in greetings:
        res = client.post("/memories/extract", json={"message": msg, "user_id": "test_user"})
        assert res.status_code == 200
        assert len(res.json()["candidates"]) == 0


def test_secrets_dropped_safely(client):
    """Verify messages containing API keys or passwords produce no candidate memories."""
    secret_msgs = [
        "My OpenAI key is sk-1234567890abcdef1234567890",
        "Here is the database password=supersecretpass123",
        "Use token: ghp_1234567890abcdef1234567890abcdef",
    ]
    for msg in secret_msgs:
        res = client.post("/memories/extract", json={"message": msg, "user_id": "test_user"})
        assert res.status_code == 200
        assert len(res.json()["candidates"]) == 0
        assert len(client.get("/memories?user_id=test_user").json()) == 0


def test_auto_save_mode(client):
    """Verify review_before_saving=False auto-saves high-confidence new facts."""
    msg = "I'm learning Python programming."
    res = client.post("/memories/extract", json={
        "message": msg,
        "user_id": "test_user_autosave",
        "review_before_saving": False,
    })
    assert res.status_code == 200
    data = res.json()
    assert data["auto_saved"] is True
    assert len(data["saved_memories"]) == 1

    # DB immediately contains the memory
    db_mems = client.get("/memories?user_id=test_user_autosave").json()
    assert len(db_mems) == 1
    assert "Python" in db_mems[0]["title"]
