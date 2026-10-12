import urllib.request
import json
import time

API_BASE = "http://127.0.0.1:8000"

def test_endpoints():
    print(f"Testing live connectivity against {API_BASE}...")
    try:
        # Check health
        req = urllib.request.urlopen(f"{API_BASE}/health", timeout=3)
        data = json.loads(req.read().decode())
        print("Health check:", data)
    except Exception as e:
        print(f"Backend not currently listening on {API_BASE}: {e}")
        print("The backend will be run by the user via: python -m uvicorn main:app --reload")

if __name__ == "__main__":
    test_endpoints()
