# PrivateMind 🧠 — Reproducible Demo Walkthrough

> **NVIDIA × Nebius AI Hackathon Demonstration Guide**  
> Validated end-to-end against local FastAPI backend, SQLite persistent store, FAISS vector index, and NVIDIA/Nebius LLM inference interfaces.

This document provides two methods to execute the 8-step PrivateMind demo:
1. **Option A: Automated CLI Script** (`python backend/demo_scenario.py`) — Completely hands-off, programmatic demonstration validating memory extraction, approval, retrieval, grounding, deletion, and empirical benchmark metrics in ~5 seconds.
2. **Option B: Interactive Browser Demo** (`http://127.0.0.1:5500`) — Visual UI walkthrough using the Bolt-generated dark-mode interface.

---

## Prerequisites & Launching Services

Ensure the backend and frontend are running:

### Terminal 1: Backend API
```powershell
cd c:\Users\91720\PrivateMind\backend
.venv\Scripts\Activate.ps1
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```
*Health verification:* Open `http://127.0.0.1:8000/health/ready` -> Returns `{"status":"ready","database":"connected","vector_index":"operational","llm_provider":"mock"}`.

### Terminal 2: Frontend Server
```powershell
cd c:\Users\91720\PrivateMind\frontend
python -m http.server 5500
```
Open `http://127.0.0.1:5500` in Google Chrome or Microsoft Edge.

---

## Option A: Automated CLI Demo (Recommended for Fast Verification)

Run the end-to-end scenario runner directly in your terminal:
```powershell
cd c:\Users\91720\PrivateMind\backend
.venv\Scripts\python demo_scenario.py
```

### What the script executes:
1. **Initializes clean SQLite session and FAISS index** for user `demo_user`.
2. **Step 1:** Sends user prompt describing an IoT water quality project and FastAPI learning goals.
3. **Step 2:** Calls `FactExtractor`, extracts 3 candidate memories with confidence scores, and simulates user approval.
4. **Step 3:** Verifies persistence in SQLite `memories` table and vector index in FAISS `IndexIDMap2`.
5. **Step 4:** Initiates a brand new conversation session (`conv_demo_followup_*`) with an indirect question: *"What hardware microcontrollers and backend tools am I using across my current initiatives?"*
6. **Step 5:** Executes FAISS semantic vector search (cosine similarity $\ge 0.20$), builds prompt-injection sanitized XML context (`<retrieved_context>`), and synthesizes memory-grounded response.
7. **Step 6:** Triggers Privacy Center deletion of the hardware memory from both SQLite and FAISS.
8. **Step 7:** Re-queries *"Which microcontroller board am I using for water monitoring?"* and asserts that the expunged memory is zero-retrieved and absent from the answer.
9. **Step 8:** Prints empirical evaluation results from the Phase 8 benchmark suite.

---

## Option B: Interactive Browser UI Walkthrough

### Step 1: User Shares Project & Learning Goal
1. Open `http://127.0.0.1:5500` in your browser.
2. In the **AI Workspace** chat input, type:
   > *"Hi PrivateMind! I'm currently designing an automated water quality monitoring station using ESP32 microcontroller boards and analog turbidity sensors. At the same time, I am learning Python backend development and FastAPI."*
3. Press **Enter** or click **Send**.
4. The assistant will respond, acknowledging your input.

### Step 2: Fact Extraction & User Review-Before-Save
1. Notice the **Extracted Candidate Facts** banner appears above the chat input or within the response drawer.
2. The system identifies candidate facts:
   - *Title:* "Automated Water Quality Monitoring Station Project" | *Category:* Projects
   - *Title:* "Analog Turbidity Sensors" | *Category:* General
   - *Title:* "Learning Python Backend Development" | *Category:* Skills
3. Click **"Approve"** on the candidate cards to commit them to your permanent vault.
*(If review-before-save is toggled on in Privacy Center, no fact is saved without your explicit approval).*

### Step 3: Verify Memories in Memory Vault
1. Click **"Memory Vault"** in the left sidebar navigation.
2. Verify that your approved facts now appear in the vault with their assigned categories (`Projects`, `Skills`, `General`).
3. Click on a memory card to view its metadata, source tag, and creation timestamp.

### Step 4: Start a New Conversation with an Indirect Query
1. Click **"New Chat"** (`+`) in the AI Workspace.
2. Enter an indirect query that does not repeat the exact project title:
   > *"What hardware microcontrollers and backend tools am I using across my current initiatives?"*
3. Press **Send**.

### Step 5: Grounded Response with Citation Badges
1. Observe the assistant's reply:
   > *"Based on your stored context (Memory #...), you are utilizing ESP32 sensors for your water quality monitoring project..."*
2. Inspect the citation badge: clicking the badge reveals the exact retrieved memory context chunk.
3. Check the developer console (`F12`) to verify the semantic retrieval request to `POST /chat` completed in $<50\text{ ms}$.

### Step 6: Memory Mutation / Deletion via Privacy Center
1. Navigate back to **"Memory Vault"** or the **"Privacy Center"**.
2. Locate the memory card titled *"Automated Water Quality Monitoring Station Project"* (or *"ESP32"*).
3. Click the red **"Delete"** button and confirm.
4. The memory is immediately purged from SQLite and de-indexed from FAISS vector memory.

### Step 7: Verification of Zero Stale Cache Leakage
1. Return to the **AI Workspace**.
2. Ask:
   > *"Which microcontroller board am I using for water monitoring?"*
3. Observe the response:
   - PrivateMind does **not** hallucinate the deleted ESP32 memory.
   - Because the fact was expunged, PrivateMind cleanly states it has no record of that microcontroller hardware or refers only to remaining active memories (turbidity sensors).
4. This confirms zero zombie cache leakage and immediate consistency across SQLite and FAISS.

### Step 8: View Measured Evaluation Metrics
1. Open the backend evaluation report in your editor or browser: [`backend/evaluation_report.md`](file:///c:/Users/91720/PrivateMind/backend/evaluation_report.md).
2. Point judges to the real empirical benchmark measurements:
   - **Semantic Precision@5:** `0.8125` vs Keyword `0.2667` (**+204.6% higher precision**)
   - **Semantic Recall@5:** `0.8750` vs Keyword `0.6250` (**+40.0% recall advantage**)
   - **Warm Cache Retrieval Latency:** `2.63 ms` (**44.4% latency reduction**)
   - **Memory-Grounded Answer Accuracy:** `75.0%` with Memory ON, **100% honest refusal** with Memory OFF.

---

## Graceful Fallback & Offline Reliability
If Nebius or NVIDIA API credentials are not configured or the network is offline:
- PrivateMind automatically routes all chat requests to the local **MockLLMProvider**.
- The UI displays an amber status badge: `Inference: Local Mock (Offline Mode)`.
- All memory extraction, semantic FAISS retrieval, user authentication, and privacy controls continue to function with 100% fidelity on the local CPU without failing or throwing uncaught exceptions.
