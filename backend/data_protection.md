# PrivateMind: Data Protection, Privacy Controls & Security Architecture

This document details the data protection model, storage layout, privacy controls, authentication architecture, and external data transmission policies for PrivateMind.

---

## 1. Data Inventory: What is Stored & Where

| Category | Specific Data Stored | Primary Storage Location | Persistence Lifecycle |
| :--- | :--- | :--- | :--- |
| **User Identity** | Username, email (optional), password hash (`scrypt`), privacy preferences, timestamps | SQLite database (`data/privatemind.db`), `users` table | Permanent until account deletion |
| **Authentication Sessions** | Cryptographically random session tokens (32-byte URL-safe base64), user ID, expiration timestamp, last active timestamp | SQLite database (`data/privatemind.db`), `user_sessions` table | Valid for 7 days or until logout/account deletion |
| **Persistent Memories** | User ID, memory title, memory text content, category, origin source, created/updated timestamps | SQLite database (`data/privatemind.db`), `memories` table | Permanent until deleted individually, bulk deleted, or account deleted |
| **Vector Embeddings** | Memory ID, user ID, embedding vector (384-dimensional dense float vector), model identifier | FAISS Index (`data/faiss_index.bin`) & SQLite `memory_embeddings` table | Synchronized with memories; purged when memory or account is deleted |
| **Conversations** | Conversation session ID, user ID, role (`user` or `assistant`), message text content, timestamp | SQLite database (`data/privatemind.db`), `conversation_messages` table | Retained per session; user can delete individual conversations, clear all chat history, or delete account |
| **Projects Context** | Derived memory projects (title, description, tags, progress, theme) | SQLite database (`data/privatemind.db`), `memories` table (`category='Projects'`) | Permanent until deleted |

---

## 2. External Data Flow: What is Sent to External AI Providers

PrivateMind is configured to interface with inference providers (Nebius Studio, NVIDIA NIM, or a local provider). When a user sends a chat message:

### Data Transmitted External to the Host:
1. **Chat Conversation History**: The user's current message and the recent conversation turns (up to 10 most recent turns) in that conversation session.
2. **Retrieved Memory Snippets**: Only memories deemed semantically relevant by the local FAISS index (filtered above the retrieval similarity threshold) are included in the `<retrieved_context>` XML block inside the system prompt.
3. **System Instructions**: PrivateMind assistant rules and prompt injection defense guidelines.

### Data NEVER Transmitted to External Providers:
- Passwords, password hashes, or session tokens.
- User email addresses or account metadata.
- Memories that did not match the user's current query or belong to other users.
- Unapproved candidate memories.
- Internal SQLite IDs or database metadata.
- Provider API keys (API keys are held exclusively on the backend server and injected into HTTP headers by the backend client; they are never sent to the browser or logged).

> [!NOTE]
> If `memory_enabled` is switched off in user settings or if `max_memories` is set to 0, zero memories are retrieved from SQLite/FAISS and no memory context is included in the prompt sent to the LLM.

---

## 3. Authentication & Session Security Architecture

### Password Derivation (`scrypt`)
- Utilizes Python's standard library `hashlib.scrypt` (memory-hard key derivation function recommended by OWASP).
- Derivation parameters: `n=16384`, `r=8`, `p=1`, `maxmem=33554432`.
- Generates a cryptographically random 16-byte salt per password (`secrets.token_bytes(16)`).
- Compares hashes using timing-attack resistant `hmac.compare_digest`.
- Passwords must be at least 8 characters long and are rejected if empty or whitespace.

### Session Management
- Sessions use high-entropy 32-byte tokens (`secrets.token_urlsafe(32)`).
- Session tokens are stored in the `user_sessions` table and verified on every protected request.
- Tokens are transmitted via:
  1. `Authorization: Bearer <token>` header (standard API clients).
  2. Secure `session_token` cookie configured with:
     - `HttpOnly`: Prevents client-side JavaScript access / XSS token exfiltration.
     - `SameSite=Lax`: Mitigates Cross-Site Request Forgery (CSRF).
     - `Secure`: Dynamically set to `True` when `ENVIRONMENT=production`.
     - `Max-Age`: 7 days.
     - `Path=/`.
- Logging out (`POST /auth/logout`) deletes the session row from SQLite and instructs the browser to delete the cookie.

---

## 4. Authorization & Insecure Direct Object Reference (IDOR) Defense

1. **Scoped Ownership Checks**:
   - Every memory endpoint (`GET /memories/{id}`, `PATCH /memories/{id}`, `DELETE /memories/{id}`) verifies ownership against the authenticated user (`current_user.username`).
   - Querying a memory ID owned by another user yields **`404 Not Found`** rather than `403 Forbidden`, preventing resource existence enumeration.
2. **Conversation Isolation**:
   - `POST /chat` verifies that the requested `conversation_id` belongs to the requesting user if prior turns exist; cross-user attempts receive `403 Forbidden`.
   - `GET /chat/{conversation_id}` and `DELETE /chat/{conversation_id}` verify user ownership of the conversation session.
3. **Cross-User Semantic Isolation**:
   - FAISS vector queries are filtered by `user_id == current_user.username` in `vector_index.py`, ensuring Alice's vector embeddings are never returned to Bob.

---

## 5. Privacy Controls & Backend Enforcement

1. **Backend-Enforced Memory Toggle (`memory_enabled`)**:
   - Not a frontend cosmetic toggle.
   - When set to `False` via `PATCH /auth/settings`, both `/memories/search` and the `/chat` semantic retrieval pipeline skip retrieval completely, returning zero memories.
2. **Review-Before-Save Workflow (`review_before_save`)**:
   - Extracted candidate facts from chat messages are flagged as candidates requiring user review.
   - Candidates are only persisted to SQLite and indexed in FAISS when explicitly approved via `POST /memories/approve`.
   - Candidates can be discarded via `POST /memories/reject`.
3. **Portable Data Export (`GET /auth/export` & `GET /memories/export`)**:
   - Generates a standardized, self-contained JSON file containing all user memories and conversation histories with timestamps.
4. **Account & Retention Deletion (`DELETE /auth/account`, `DELETE /memories`, `DELETE /chat`)**:
   - Granular deletion: Users can delete single memories, individual chat conversations, or all chat messages.
   - Complete account purge (`DELETE /auth/account`): Atomically purges user memories, vector embeddings in FAISS, conversation messages, active sessions, and the user record.

---

## 6. Abuse Prevention & Rate Limiting

- **Thread-Safe Sliding-Window Limiter** (`backend/rate_limiter.py`):
  - `POST /auth/register` and `POST /auth/login`: Limited to **10 requests per minute per IP**.
  - `POST /chat`: Limited to **30 requests per minute per IP** to prevent upstream LLM provider quota exhaustion and DoS abuse.
  - Exceeding the rate limit responds with **HTTP 429 Too Many Requests** and a standard `Retry-After` header.
- **Input Validation & Size Limits**:
  - Chat messages are capped at 4,000 characters (HTTP 413 if exceeded).
  - Memory titles are capped at 255 characters; content capped at 10,000 characters.

---

## 7. Known Security Limitations & Honest Declarations

In accordance with PrivateMind constraints:
1. **No End-to-End Encryption (E2EE)**:
   - Data stored in SQLite (`data/privatemind.db`) is not encrypted at rest using SQLCipher or transparent file encryption. Local filesystem access on the server machine allows reading the database file.
2. **Inference is NOT Completely Local When Cloud LLMs Are Used**:
   - When configured with Nebius Studio or NVIDIA NIM endpoints, prompts and retrieved memories travel over HTTPS/TLS to external cloud inference APIs. Only if a strictly local LLM endpoint (e.g. Ollama or vLLM running on `localhost`) is configured is inference fully local.
3. **In-Memory Rate Limiting**:
   - The sliding-window rate limiter is currently in-process memory. Restarting the backend server resets the IP request counters. For multi-instance distributed deployments, a Redis-backed limiter would be required.
