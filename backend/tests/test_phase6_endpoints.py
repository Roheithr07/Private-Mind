import pytest


def test_bulk_delete_memories(client):
    # Create 2 memories
    client.post("/memories", json={"title": "M1", "content": "Content 1", "category": "General", "user_id": "test_user"})
    client.post("/memories", json={"title": "M2", "content": "Content 2", "category": "General", "user_id": "test_user"})
    client.post("/memories", json={"title": "Other", "content": "Other Content", "category": "General", "user_id": "other_user"})

    # Bulk delete test_user memories
    resp = client.delete("/memories?user_id=test_user")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "deleted"
    assert data["deleted_count"] == 2

    # Verify test_user memories are gone but other_user remains
    m_test = client.get("/memories?user_id=test_user").json()
    assert len(m_test) == 0
    m_other = client.get("/memories?user_id=other_user").json()
    assert len(m_other) == 1


def test_projects_endpoints(client):
    # Create a project
    create_resp = client.post("/projects", json={"title": "PrivateMind Hackathon", "description": "Persistent AI memory assistant", "user_id": "proj_user", "tags": ["AI", "NVIDIA"]})
    assert create_resp.status_code == 201
    proj_data = create_resp.json()
    assert proj_data["title"] == "PrivateMind Hackathon"
    assert proj_data["theme"] == "blue"

    # List projects
    get_resp = client.get("/projects?user_id=proj_user")
    assert get_resp.status_code == 200
    list_data = get_resp.json()
    assert list_data["total_projects"] == 1
    assert list_data["projects"][0]["title"] == "PrivateMind Hackathon"
    assert list_data["connected"] is True
