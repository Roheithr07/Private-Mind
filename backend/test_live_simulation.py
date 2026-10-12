import urllib.request
import json

API_BASE = "http://127.0.0.1:8000"

def run_live_browser_simulation():
    print("--- 1. Testing GET /health ---")
    req = urllib.request.urlopen(f"{API_BASE}/health")
    print("Health:", json.loads(req.read().decode()))

    print("\n--- 2. Testing GET /memories ---")
    req = urllib.request.urlopen(f"{API_BASE}/memories?limit=5")
    mems = json.loads(req.read().decode())
    print(f"Retrieved {len(mems)} memories from SQLite.")

    print("\n--- 3. Testing POST /chat ---")
    chat_payload = json.dumps({
        "message": "Hello PrivateMind! What are you working on?",
        "conversation_id": "test_browser_session_1",
        "user_id": "default_user",
        "retrieval_threshold": 0.25,
        "max_memories": 3
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{API_BASE}/chat",
        data=chat_payload,
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req) as resp:
        chat_resp = json.loads(resp.read().decode())
        print("Chat Response:", chat_resp.get("response")[:120], "...")
        print("Provider:", chat_resp.get("provider"), "| is_mock:", chat_resp.get("is_mock"))
        print("Memories retrieved:", len(chat_resp.get("memories_retrieved", [])))
        print("Extracted candidates:", len(chat_resp.get("extracted_candidates", [])))

    print("\n--- 4. Testing GET /projects ---")
    req = urllib.request.urlopen(f"{API_BASE}/projects?user_id=default_user")
    projects_resp = json.loads(req.read().decode())
    print("Projects:", projects_resp.get("total_projects"), "projects found, connected:", projects_resp.get("connected"))

    print("\nALL LIVE ENDPOINTS RESPONDED PERFECTLY!")

if __name__ == "__main__":
    run_live_browser_simulation()
