# PrivateMind: Deployment Guide & Operational Reliability

This document provides complete instructions for deploying PrivateMind into staging and production environments, along with backup, disaster recovery, and operational procedures.

---

## 1. Pre-Deployment Checklist

Before deploying PrivateMind to a public or production environment, complete the following steps:

- [ ] **Secrets Segregation**: Ensure no `.env` files, API keys, or private database files are committed to Git. Verify `.gitignore` is active.
- [ ] **Environment Mode**: Set `ENVIRONMENT=production` in the backend environment.
- [ ] **CORS Configuration**: Configure `ALLOWED_ORIGINS` with exact trusted URLs (e.g. `https://app.privatemind.ai`). Never use wildcards `*` in production.
- [ ] **Storage Persistence**: Verify that SQLite storage (`data/privatemind.db`) is mounted on a **persistent disk volume** or switch `DATABASE_URL` to a managed PostgreSQL instance.
- [ ] **HTTPS & SSL/TLS**: Ensure the application is served over HTTPS to guarantee that secure HTTP-only cookies and Bearer tokens are encrypted in transit.
- [ ] **Health Probes**: Configure container liveness and readiness probes to monitor `/health` and `/health/ready`.
- [ ] **Rate Limiting**: Review sliding-window rate limits (defaults: 10 req/min on `/auth/*`, 30 req/min on `/chat`).
- [ ] **External AI Endpoint Credentials**: If using Nebius or NVIDIA NIM, verify that valid API keys are configured and funded; otherwise, verify mock fallback behavior.

---

## 2. Environment Variables Reference

| Variable | Default (Dev) | Production Recommendation | Description |
| :--- | :--- | :--- | :--- |
| `ENVIRONMENT` | `development` | `production` | Enables production security (secure cookies, strict CORS, disables default dev user bypass). |
| `BACKEND_HOST` | `127.0.0.1` | `0.0.0.0` | Network interface to bind the FastAPI backend. |
| `BACKEND_PORT` | `8000` | `8000` (or `PORT` provided by PaaS) | Port for the backend application. |
| `ALLOWED_ORIGINS` | `http://localhost:5500` | `https://yourdomain.com` | Comma-separated list of allowed CORS frontend origins. |
| `DATABASE_URL` | `sqlite:///./data/privatemind.db` | `sqlite:////data/privatemind.db` or `postgresql://user:pass@host/db` | Database connection string. |
| `LLM_PROVIDER` | `mock` | `nebius`, `nvidia`, or `mock` | Active inference provider. |
| `LLM_TIMEOUT` | `30.0` | `30.0` | Timeout in seconds for upstream LLM provider calls. |
| `NEBIUS_API_KEY` | *(None)* | `your_nebius_api_key` | Nebius AI Studio token (required if `LLM_PROVIDER=nebius`). |
| `NVIDIA_API_KEY` | *(None)* | `your_nvidia_api_key` | NVIDIA NIM API catalog token (required if `LLM_PROVIDER=nvidia`). |
| `LLM_BASE_URL` | *(Provider default)* | *(Provider endpoint)* | Overrides API base URL if using a private inference gateway. |
| `LLM_MODEL` | *(Provider default)* | e.g. `meta-llama/Meta-Llama-3.1-70B-Instruct` | Model identifier. |

---

## 3. Storage Persistence & Ephemeral Hosting Warning

> [!WARNING]
> **Ephemeral Container Disks (Heroku, standard Render, AWS Fargate without EFS):**  
> If deployed on a platform where container filesystems are ephemeral, local SQLite files (`data/privatemind.db`) will be **lost on every container restart, redeploy, or auto-scale event**.

### Solutions for Persistent Storage:
1. **Persistent Volume Mount (Recommended for SQLite)**:
   - On **Render**: Attach a Persistent Disk (e.g., mount `/data`). Set `DATABASE_URL=sqlite:////data/privatemind.db`.
   - On **Fly.io**: Create a volume `fly volumes create privatemind_data -s 1` and mount to `/data`.
   - On **Railway**: Add a Volume service and set the mount path to `/data`.
2. **Managed PostgreSQL**:
   - Provide standard PostgreSQL connection URI: `DATABASE_URL=postgresql://user:password@hostname:5432/privatemind`.
   - SQLAlchemy automatically switches to PostgreSQL dialect without code modifications.

---

## 4. Backend Deployment Instructions

### Option A: Docker Deployment (Recommended)

1. **Build Docker Image**:
   ```bash
   docker build -t privatemind-backend:latest -f backend/Dockerfile .
   ```

2. **Run Container with Persistent Volume**:
   ```bash
   docker run -d \
     --name privatemind-backend \
     -p 8000:8000 \
     -v privatemind_data:/app/backend/data \
     -e ENVIRONMENT=production \
     -e ALLOWED_ORIGINS="https://privatemind.yourdomain.com" \
     -e LLM_PROVIDER=nebius \
     -e NEBIUS_API_KEY="your-secret-api-key" \
     privatemind-backend:latest
   ```

### Option B: Cloud PaaS (Render / Railway / Fly.io)

1. Link your repository.
2. Set Root Directory to `backend`.
3. Set Build Command: `pip install -r requirements.txt`.
4. Set Start Command: `uvicorn main:app --host 0.0.0.0 --port $PORT --workers 2`.
5. Attach a persistent disk mounted at `/app/data` and configure `DATABASE_URL=sqlite:////app/data/privatemind.db`.
6. Add all production environment variables from `.env.example`.

---

## 5. Frontend Deployment Instructions

The frontend is a standalone, dependency-free vanilla HTML/JS application located in `frontend/`.

### Deployment to Vercel / Netlify / Cloudflare Pages:
1. Set the publish directory to `frontend`.
2. Configure your production API base URL by either:
   - Defining a build-time script injection: `<script>window.API_BASE_URL = "https://api.privatemind.yourdomain.com";</script>`.
   - Setting the URL directly inside the **Settings** view in the UI (stored persistently in browser localStorage).
3. Ensure custom domains use HTTPS so cookies can be issued with `SameSite=Lax`.

---

## 6. Data Backup & Restore Procedures

### Backing Up SQLite Database
While the backend is running, use SQLite's safe online backup API to ensure zero write corruption:

```bash
# 1. Online safe SQLite backup
sqlite3 backend/data/privatemind.db ".backup 'backend/data/privatemind_backup_$(date +%Y%m%d_%H%M%S).db'"

# 2. Upload backup snapshot to S3 or secure cold storage
aws s3 cp backend/data/privatemind_backup_*.db s3://your-backup-bucket/privatemind/
```

### Restoring SQLite Database
```bash
# 1. Stop backend service
docker stop privatemind-backend

# 2. Replace database file with verified backup
cp privatemind_backup_20261012_220000.db backend/data/privatemind.db

# 3. Restart backend service (lifespan automatically re-indexes FAISS on startup)
docker start privatemind-backend
```

---

## 7. Disaster Recovery & Migration Failure Process

If a deployment fails, database corruption occurs, or schema changes need rollback:

1. **Immediate Health Failure Detection**:
   - The `/health/ready` probe returns `503 Service Unavailable` if the database fails query execution or vector tables are corrupt.
2. **Container Rollback**:
   - Roll back to the previous container image tag.
3. **Database Recovery**:
   - If SQLite integrity check fails (`PRAGMA integrity_check;`), restore the most recent snapshot as described in Section 6.
   - Run startup sync: The backend's lifespan function `get_vector_index().load_or_sync_from_db(db)` re-synchronizes the in-memory FAISS index from SQLite records automatically.

---

## 8. Known Operational Limitations

1. **In-Memory Rate Limiter**: The sliding-window rate limiter runs in-process. In a multi-replica clustered setup behind a load balancer, deploy an external Redis instance to share rate limits across workers.
2. **Plaintext SQLite at Rest**: Data at rest in `privatemind.db` is not encrypted with disk-level encryption. For high-compliance requirements, use OS-level volume encryption (LUKS / BitLocker) or SQLCipher.
3. **Cloud LLM Latency**: When using remote Nebius or NVIDIA NIM inference, response latency is subject to public internet transit and provider inference queues (typically 800ms - 2,500ms).
