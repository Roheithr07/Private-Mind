import os
import pytest


def test_cors_preflight_and_origin_headers(client):
    # Test origin 127.0.0.1:5500
    resp = client.options(
        "/chat",
        headers={
            "Origin": "http://127.0.0.1:5500",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type",
        },
    )
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "http://127.0.0.1:5500"

    # Test origin localhost:5500
    resp_local = client.options(
        "/memories",
        headers={
            "Origin": "http://localhost:5500",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert resp_local.status_code == 200
    assert resp_local.headers.get("access-control-allow-origin") == "http://localhost:5500"


def test_frontend_files_integrity():
    # Verify index.html exists and has api.js script include
    index_path = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "index.html")
    assert os.path.exists(index_path)
    with open(index_path, "r", encoding="utf-8") as f:
        content = f.read()
    assert '<script src="api.js"></script>' in content
    assert 'id="chatForm"' in content
    assert 'id="memorySearch"' in content
    assert 'id="addMemory"' in content
    assert 'id="view"' in content
    assert 'class="workspace"' in content

    # Verify api.js exists and exports expected methods
    api_path = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "api.js")
    assert os.path.exists(api_path)
    with open(api_path, "r", encoding="utf-8") as f:
        api_content = f.read()
    for method in [
        "checkHealth",
        "getMemories",
        "getMemory",
        "createMemory",
        "updateMemory",
        "deleteMemory",
        "deleteAllMemories",
        "sendChat",
        "getProjects",
        "approveMemories",
        "rejectMemories",
    ]:
        assert method in api_content, f"Missing method {method} in api.js"


def test_full_frontend_backend_flow(client):
    # 1. Health check
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json() == {"status": "healthy"}

    # 2. Create memory (as done by frontend "Add memory" button)
    create_res = client.post(
        "/memories",
        json={
            "title": "ESP32 Water Quality Project",
            "content": "Developing a water quality monitor with turbidity and dissolved oxygen sensors.",
            "category": "Projects",
            "source": "manual",
            "user_id": "default_user",
        },
    )
    assert create_res.status_code == 201
    mem_id = create_res.json()["id"]

    # 3. List memories (as done by Memory Vault)
    list_res = client.get("/memories?user_id=default_user")
    assert list_res.status_code == 200
    mems = list_res.json()
    assert len(mems) == 1
    assert mems[0]["title"] == "ESP32 Water Quality Project"

    # 4. Search memories (as done by Memory Vault search box)
    search_res = client.get("/memories?search=turbidity")
    assert search_res.status_code == 200
    assert len(search_res.json()) == 1

    # 5. Chat message with semantic retrieval (as done by Workspace chat)
    chat_res = client.post(
        "/chat",
        json={
            "message": "Which sensors am I using in my water project?",
            "conversation_id": "conv_test_123",
            "user_id": "default_user",
            "retrieval_threshold": 0.25,
        },
    )
    assert chat_res.status_code == 200
    chat_data = chat_res.json()
    assert len(chat_data["memories_retrieved"]) >= 1
    assert chat_data["memories_retrieved"][0]["memory_id"] == mem_id
    assert chat_data["conversation_id"] == "conv_test_123"

    # 6. Candidate extraction in chat
    chat_cand_res = client.post(
        "/chat",
        json={
            "message": "I prefer dark chocolate over milk chocolate.",
            "conversation_id": "conv_test_123",
            "user_id": "default_user",
        },
    )
    assert chat_cand_res.status_code == 200
    cand_data = chat_cand_res.json()
    assert len(cand_data["extracted_candidates"]) >= 1

    # Approve candidate
    candidate_to_approve = cand_data["extracted_candidates"][0]
    approve_res = client.post(
        "/memories/approve",
        json={
            "candidates": [candidate_to_approve],
            "user_id": "default_user",
        },
    )
    assert approve_res.status_code == 200
    assert len(approve_res.json()["saved_memories"]) == 1

    # Verify approved memory now appears in memories list
    list_after_approval = client.get("/memories?user_id=default_user").json()
    assert len(list_after_approval) == 2

    # 7. Edit memory (as done by Edit button in Vault)
    edit_res = client.patch(
        f"/memories/{mem_id}",
        json={"title": "Updated ESP32 Project", "category": "Projects"},
    )
    assert edit_res.status_code == 200
    assert edit_res.json()["title"] == "Updated ESP32 Project"

    # 8. Projects endpoint (as done by Projects tab)
    proj_res = client.get("/projects?user_id=default_user")
    assert proj_res.status_code == 200
    proj_data = proj_res.json()
    assert proj_data["connected"] is True
    assert proj_data["total_projects"] >= 1

    # 9. Delete single memory (as done by delete button in Vault)
    del_res = client.delete(f"/memories/{mem_id}")
    assert del_res.status_code == 200

    # 10. Privacy Center Delete all data
    del_all_res = client.delete("/memories?user_id=default_user")
    assert del_all_res.status_code == 200
    final_list = client.get("/memories?user_id=default_user").json()
    assert len(final_list) == 0
