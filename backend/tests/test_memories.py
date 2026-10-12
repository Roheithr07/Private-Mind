import pytest
from backend.models import Memory
from backend.tests.conftest import TestingSessionLocal


def test_system_endpoints(client):
    # GET /
    res_root = client.get("/")
    assert res_root.status_code == 200
    assert res_root.json()["project"] == "PrivateMind"

    # GET /health
    res_health = client.get("/health")
    assert res_health.status_code == 200
    assert res_health.json() == {"status": "healthy"}


def test_create_memory_success(client):
    payload = {
        "title": "NVIDIA Hackathon Plan",
        "content": "Building PrivateMind with persistent memory architecture.",
        "category": "Projects",
        "source": "manual",
        "user_id": "test_user_1",
    }
    response = client.post("/memories", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["id"] is not None
    assert data["title"] == "NVIDIA Hackathon Plan"
    assert data["content"] == "Building PrivateMind with persistent memory architecture."
    assert data["category"] == "Projects"
    assert data["source"] == "manual"
    assert data["user_id"] == "test_user_1"
    assert "created_at" in data
    assert "updated_at" in data


def test_create_memory_validation_error(client):
    # Empty title
    response = client.post("/memories", json={"title": "", "content": "Some content"})
    assert response.status_code == 422

    # Missing content
    response2 = client.post("/memories", json={"title": "Some title"})
    assert response2.status_code == 422


def test_list_memories_and_filters(client):
    # Seed 3 memories
    client.post("/memories", json={
        "title": "NVIDIA Hackathon",
        "content": "Building PrivateMind for the Nebius hackathon",
        "category": "Projects",
    })
    client.post("/memories", json={
        "title": "Dietary Preferences",
        "content": "Vegetarian diet with low sugar",
        "category": "Preferences",
    })
    client.post("/memories", json={
        "title": "IoT Water Quality Sensor",
        "content": "ESP32 based water monitoring",
        "category": "Projects",
    })

    # List all
    res_all = client.get("/memories")
    assert res_all.status_code == 200
    all_memories = res_all.json()
    assert len(all_memories) == 3

    # Filter by category
    res_cat = client.get("/memories?category=Projects")
    assert res_cat.status_code == 200
    assert len(res_cat.json()) == 2
    assert all(m["category"] == "Projects" for m in res_cat.json())

    # Search filter matching title
    res_search1 = client.get("/memories?search=Dietary")
    assert res_search1.status_code == 200
    assert len(res_search1.json()) == 1
    assert res_search1.json()[0]["title"] == "Dietary Preferences"

    # Search filter matching content
    res_search2 = client.get("/memories?search=Nebius")
    assert res_search2.status_code == 200
    assert len(res_search2.json()) == 1
    assert res_search2.json()[0]["title"] == "NVIDIA Hackathon"


def test_get_memory_by_id(client):
    create_res = client.post("/memories", json={
        "title": "Unique Memory",
        "content": "Unique content details",
        "category": "Personal",
    })
    mem_id = create_res.json()["id"]

    # Existing
    res = client.get(f"/memories/{mem_id}")
    assert res.status_code == 200
    assert res.json()["title"] == "Unique Memory"

    # Non-existent
    res_not_found = client.get("/memories/99999")
    assert res_not_found.status_code == 404
    assert "not found" in res_not_found.json()["detail"].lower()


def test_update_memory(client):
    create_res = client.post("/memories", json={
        "title": "Draft Memory",
        "content": "Initial thoughts",
        "category": "Drafts",
    })
    mem_id = create_res.json()["id"]

    # Partial update title only
    patch_res = client.patch(f"/memories/{mem_id}", json={"title": "Finalized Memory"})
    assert patch_res.status_code == 200
    assert patch_res.json()["title"] == "Finalized Memory"
    assert patch_res.json()["content"] == "Initial thoughts"
    assert patch_res.json()["category"] == "Drafts"

    # Update content and category
    patch_res2 = client.patch(f"/memories/{mem_id}", json={
        "content": "Updated content body",
        "category": "Final",
    })
    assert patch_res2.status_code == 200
    assert patch_res2.json()["content"] == "Updated content body"
    assert patch_res2.json()["category"] == "Final"

    # Patch non-existent
    res_not_found = client.patch("/memories/99999", json={"title": "Won't work"})
    assert res_not_found.status_code == 404


def test_delete_memory(client):
    create_res = client.post("/memories", json={
        "title": "To Be Deleted",
        "content": "Temporary information",
    })
    mem_id = create_res.json()["id"]

    # Delete existing
    del_res = client.delete(f"/memories/{mem_id}")
    assert del_res.status_code == 200
    assert del_res.json()["status"] == "deleted"
    assert del_res.json()["id"] == mem_id

    # Verify gone
    get_res = client.get(f"/memories/{mem_id}")
    assert get_res.status_code == 404

    # Delete non-existent
    del_again = client.delete(f"/memories/{mem_id}")
    assert del_again.status_code == 404


def test_persistence_across_sessions(client):
    """Verify that records committed to the database persist across new DB sessions."""
    create_res = client.post("/memories", json={
        "title": "Persistent Fact",
        "content": "This fact must survive across engine reconnects.",
        "category": "Important",
    })
    mem_id = create_res.json()["id"]

    fresh_session = TestingSessionLocal()
    persisted = fresh_session.query(Memory).filter(Memory.id == mem_id).first()
    assert persisted is not None
    assert persisted.title == "Persistent Fact"
    assert persisted.content == "This fact must survive across engine reconnects."
    fresh_session.close()
