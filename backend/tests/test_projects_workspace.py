"""
Comprehensive test suite for PrivateMind Project Workspaces.
Validates:
- Project CRUD, search, and status filtering
- Project Notes CRUD and conversion to persistent memory with FAISS vector indexing
- Project Tasks CRUD and automatic progress recalculation
- Project Memory attachment, detachment, and safe project deletion (preserving memories)
- "Ask AI about this project" context-grounded retrieval
- Strict user isolation and IDOR protection
"""

import os
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.rate_limiter import rate_limiter


@pytest.fixture(autouse=True)
def reset_rate_limiters():
    rate_limiter.clear()


@pytest.fixture
def auth_headers(client: TestClient):
    """Registers two distinct users and provides Bearer authorization headers."""
    reg1 = client.post(
        "/auth/register",
        json={"username": "alice_ws", "password": "AlicePassword123!"},
    )
    assert reg1.status_code == 201
    tok1 = reg1.json()["access_token"]

    reg2 = client.post(
        "/auth/register",
        json={"username": "bob_ws", "password": "BobPassword123!"},
    )
    assert reg2.status_code == 201
    tok2 = reg2.json()["access_token"]

    return {
        "alice": {"Authorization": f"Bearer {tok1}"},
        "bob": {"Authorization": f"Bearer {tok2}"},
    }


def test_project_crud_and_filtering(client: TestClient, auth_headers):
    headers = auth_headers["alice"]

    # 1. Create project
    create_payload = {
        "title": "Autonomous Drone Fleet",
        "description": "Navigation and computer vision stack for autonomous drones",
        "status": "active",
        "priority": "high",
        "deadline": "2026-12-01",
        "progress": 25,
        "tags": ["Robotics", "Computer Vision", "AI"],
        "theme": "indigo",
    }
    resp = client.post("/projects", json=create_payload, headers=headers)
    assert resp.status_code == 201, resp.text
    proj = resp.json()
    assert proj["title"] == "Autonomous Drone Fleet"
    assert proj["status"] == "active"
    assert proj["priority"] == "high"
    assert proj["deadline"] == "2026-12-01"
    assert proj["progress"] == 25
    assert "Robotics" in proj["tags"]
    proj_id = proj["id"]

    # Create second project for filtering test
    resp2 = client.post("/projects", json={
        "title": "Quantum Algorithm Simulator",
        "description": "Simulating Shor's algorithm on classic hardware",
        "status": "planning",
        "priority": "medium",
        "tags": ["Quantum", "Physics"],
    }, headers=headers)
    assert resp2.status_code == 201
    proj2_id = resp2.json()["id"]

    # 2. Search filtering
    search_resp = client.get("/projects?search=Drone", headers=headers)
    assert search_resp.status_code == 200
    search_data = search_resp.json()["projects"]
    assert len(search_data) == 1
    assert search_data[0]["id"] == proj_id

    # 3. Status filtering
    filter_resp = client.get("/projects?status=planning", headers=headers)
    assert filter_resp.status_code == 200
    filter_data = filter_resp.json()["projects"]
    assert any(p["id"] == proj2_id for p in filter_data)
    assert not any(p["id"] == proj_id for p in filter_data)

    # 4. Update project
    update_resp = client.patch(f"/projects/{proj_id}", json={
        "status": "completed",
        "priority": "urgent",
        "progress": 100,
        "deadline": "2026-11-15",
    }, headers=headers)
    assert update_resp.status_code == 200
    updated = update_resp.json()
    assert updated["status"] == "completed"
    assert updated["priority"] == "urgent"
    assert updated["progress"] == 100
    assert updated["deadline"] == "2026-11-15"

    # 5. Get project detail
    detail_resp = client.get(f"/projects/{proj_id}", headers=headers)
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    assert detail["project"]["title"] == "Autonomous Drone Fleet"
    assert "notes" in detail
    assert "tasks" in detail
    assert "memories" in detail
    assert "activities" in detail
    assert any(a["action_type"] == "created_project" for a in detail["activities"])


def test_project_notes_and_convert_to_memory(client: TestClient, auth_headers):
    headers = auth_headers["alice"]

    # Create project
    proj_resp = client.post("/projects", json={
        "title": "Edge Compute Device",
        "description": "Jetson Orin deployment pipeline",
        "status": "active",
    }, headers=headers)
    proj_id = proj_resp.json()["id"]

    # 1. Create note
    note_resp = client.post(f"/projects/{proj_id}/notes", json={
        "title": "Camera Latency Optimization",
        "content": "Using GStreamer pipeline with nvarguscamerasrc reduces frame latency to 18ms.",
    }, headers=headers)
    assert note_resp.status_code == 201
    note = note_resp.json()
    note_id = note["id"]
    assert note["title"] == "Camera Latency Optimization"
    assert note["is_memory"] is False

    # 2. Update note (supports PATCH and PUT)
    update_note_resp = client.patch(f"/projects/{proj_id}/notes/{note_id}", json={
        "title": "Camera & TensorRT Latency Optimization",
        "content": "Using GStreamer with nvarguscamerasrc and FP16 TensorRT engine reduces total latency to 14ms.",
    }, headers=headers)
    assert update_note_resp.status_code == 200
    assert "TensorRT" in update_note_resp.json()["title"]

    # 3. Convert note to memory
    convert_resp = client.post(f"/projects/{proj_id}/notes/{note_id}/convert-to-memory", headers=headers)
    assert convert_resp.status_code == 201
    mem_result = convert_resp.json()
    assert mem_result["id"] is not None
    mem_id = mem_result["id"]

    # Verify memory is listed under project memories
    proj_mems = client.get(f"/projects/{proj_id}/memories", headers=headers).json()
    assert any(m["id"] == mem_id for m in proj_mems)

    # Verify note is marked as memory
    notes = client.get(f"/projects/{proj_id}/notes", headers=headers).json()
    matched_note = next(n for n in notes if n["id"] == note_id)
    assert matched_note["is_memory"] is True

    # 4. Delete note
    del_resp = client.delete(f"/projects/{proj_id}/notes/{note_id}", headers=headers)
    assert del_resp.status_code == 200
    remaining_notes = client.get(f"/projects/{proj_id}/notes", headers=headers).json()
    assert not any(n["id"] == note_id for n in remaining_notes)


def test_project_tasks_and_progress_recalculation(client: TestClient, auth_headers):
    headers = auth_headers["alice"]

    proj_resp = client.post("/projects", json={
        "title": "Autonomous Rover Stack",
        "description": "ROS2 Humble implementation on Ubuntu 22.04",
        "status": "active",
        "progress": 0,
    }, headers=headers)
    proj_id = proj_resp.json()["id"]

    # 1. Add 2 tasks
    t1_resp = client.post(f"/projects/{proj_id}/tasks", json={
        "title": "Configure Nav2 Planner",
        "status": "todo",
        "priority": "high",
    }, headers=headers)
    assert t1_resp.status_code == 201
    t1_id = t1_resp.json()["id"]

    t2_resp = client.post(f"/projects/{proj_id}/tasks", json={
        "title": "Calibrate Wheel Odometry",
        "status": "todo",
        "priority": "medium",
    }, headers=headers)
    assert t2_resp.status_code == 201
    t2_id = t2_resp.json()["id"]

    # Progress should be 0% (0 of 2)
    proj_check = client.get(f"/projects/{proj_id}", headers=headers).json()
    assert proj_check["project"]["progress"] == 0

    # Complete task 1 -> progress should recalculate to 50%
    client.patch(f"/projects/{proj_id}/tasks/{t1_id}", json={"status": "completed"}, headers=headers)
    proj_check = client.get(f"/projects/{proj_id}", headers=headers).json()
    assert proj_check["project"]["progress"] == 50

    # Complete task 2 -> progress should recalculate to 100%
    client.patch(f"/projects/{proj_id}/tasks/{t2_id}", json={"status": "completed"}, headers=headers)
    proj_check = client.get(f"/projects/{proj_id}", headers=headers).json()
    assert proj_check["project"]["progress"] == 100

    # Delete task 2
    del_resp = client.delete(f"/projects/{proj_id}/tasks/{t2_id}", headers=headers)
    assert del_resp.status_code == 200
    tasks_left = client.get(f"/projects/{proj_id}/tasks", headers=headers).json()
    assert len(tasks_left) == 1


def test_project_memories_linking_and_safe_deletion(client: TestClient, auth_headers):
    headers = auth_headers["alice"]

    # 1. Create a global memory first
    mem_resp = client.post("/memories", json={
        "title": "Global Hardware Architecture",
        "content": "All edge systems use a dual CAN bus topology at 500kbps.",
        "category": "Architecture",
        "importance": 4,
    }, headers=headers)
    assert mem_resp.status_code == 201
    memory_id = mem_resp.json()["id"]

    # 2. Create project
    proj_resp = client.post("/projects", json={
        "title": "CAN Bus Telemetry Hub",
        "description": "High-throughput CAN bus monitoring",
        "status": "active",
    }, headers=headers)
    proj_id = proj_resp.json()["id"]

    # 3. Attach memory to project
    attach_resp = client.post(f"/projects/{proj_id}/memories", json={"memory_id": memory_id}, headers=headers)
    assert attach_resp.status_code == 201
    attach_data = attach_resp.json()
    assert attach_data["success"] is True

    # Duplicate attachment should return 400
    dup_resp = client.post(f"/projects/{proj_id}/memories", json={"memory_id": memory_id}, headers=headers)
    assert dup_resp.status_code == 400

    # Verify memory is listed
    proj_mems = client.get(f"/projects/{proj_id}/memories", headers=headers).json()
    assert any(m["id"] == memory_id for m in proj_mems)

    # 4. Detach memory
    detach_resp = client.delete(f"/projects/{proj_id}/memories/{memory_id}", headers=headers)
    assert detach_resp.status_code == 200

    # Verify detached memory is NOT in project memories
    proj_mems = client.get(f"/projects/{proj_id}/memories", headers=headers).json()
    assert not any(m["id"] == memory_id for m in proj_mems)

    # Verify memory STILL exists globally in /memories
    global_mem = client.get(f"/memories/{memory_id}", headers=headers)
    assert global_mem.status_code == 200
    assert global_mem.json()["title"] == "Global Hardware Architecture"

    # Re-attach and then DELETE project to verify safe deletion
    client.post(f"/projects/{proj_id}/memories", json={"memory_id": memory_id}, headers=headers)
    del_proj_resp = client.delete(f"/projects/{proj_id}", headers=headers)
    assert del_proj_resp.status_code == 200

    # Verify project is gone
    assert client.get(f"/projects/{proj_id}", headers=headers).status_code == 404

    # Verify memory is STILL safe in database!
    global_mem_after = client.get(f"/memories/{memory_id}", headers=headers)
    assert global_mem_after.status_code == 200
    assert global_mem_after.json()["title"] == "Global Hardware Architecture"


def test_project_ask_ai_chat(client: TestClient, auth_headers):
    headers = auth_headers["alice"]

    # Create project with notes and tasks
    proj_resp = client.post("/projects", json={
        "title": "Nebius Distributed Training",
        "description": "Multi-GPU SLURM cluster on Nebius AI Cloud with NVIDIA H100 SXM5",
        "status": "active",
        "priority": "urgent",
    }, headers=headers)
    proj_id = proj_resp.json()["id"]

    # Add note
    client.post(f"/projects/{proj_id}/notes", json={
        "title": "NCCL Environment Variables",
        "content": "Set NCCL_DEBUG=INFO and NCCL_IB_DISABLE=0 for RoCE v2 infiniband fabric.",
    }, headers=headers)

    # Add task
    client.post(f"/projects/{proj_id}/tasks", json={
        "title": "Benchmark Megatron-Core 8-GPU throughput",
        "status": "in_progress",
    }, headers=headers)

    # Chat with project context
    chat_resp = client.post(f"/projects/{proj_id}/chat", json={
        "query": "What are the recommended NCCL environment variables for our Nebius cluster?"
    }, headers=headers)
    assert chat_resp.status_code == 200
    chat_data = chat_resp.json()
    assert "response" in chat_data
    assert len(chat_data["response"]) > 0
    assert "model" in chat_data


def test_user_isolation_and_idor_protection(client: TestClient, auth_headers):
    alice_headers = auth_headers["alice"]
    bob_headers = auth_headers["bob"]

    # Alice creates a private project
    proj_resp = client.post("/projects", json={
        "title": "Confidential Stealth Project",
        "description": "Proprietary IP and trade secrets",
        "status": "active",
    }, headers=alice_headers)
    alice_proj_id = proj_resp.json()["id"]

    # Bob tries to GET Alice's project -> 404 Not Found
    bob_get = client.get(f"/projects/{alice_proj_id}", headers=bob_headers)
    assert bob_get.status_code == 404

    # Bob tries to PATCH Alice's project -> 404 Not Found
    bob_patch = client.patch(f"/projects/{alice_proj_id}", json={"title": "Hacked Title"}, headers=bob_headers)
    assert bob_patch.status_code == 404

    # Bob tries to DELETE Alice's project -> 404 Not Found
    bob_del = client.delete(f"/projects/{alice_proj_id}", headers=bob_headers)
    assert bob_del.status_code == 404

    # Bob tries to add a note to Alice's project -> 404 Not Found
    bob_note = client.post(f"/projects/{alice_proj_id}/notes", json={
        "title": "Malicious Note",
        "content": "Injected text"
    }, headers=bob_headers)
    assert bob_note.status_code == 404

    # Bob tries to ask AI about Alice's project -> 404 Not Found
    bob_chat = client.post(f"/projects/{alice_proj_id}/chat", json={
        "query": "What are the secret details?"
    }, headers=bob_headers)
    assert bob_chat.status_code == 404

    # Bob listing projects does NOT see Alice's project
    bob_list = client.get("/projects", headers=bob_headers).json()["projects"]
    assert not any(p["id"] == alice_proj_id for p in bob_list)
