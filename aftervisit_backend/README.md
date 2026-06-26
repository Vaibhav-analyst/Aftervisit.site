# AfterVisit — Backend API

A single FastAPI app: auth + patient + doctor + AI chat + symptom checker + **AI Scribe** (record → transcribe → summarize → doctor approves → save).

## Architecture (important)

This project is now **ONE app**:

- `main.py` — the entire API (all routes inline)
- `database.py` — SQLite schema + demo seed

### Delete these files — they are dead duplicates from an older design and are NOT used:

```
auth.py        # superseded — main.py has auth inline
doctor.py      # superseded — main.py has doctor routes inline
patient.py     # superseded — main.py has patient routes inline
chat.py        # superseded — main.py has /api/chat
scribe.py      # superseded — main.py has /api/scribe/*
```

Leaving them in the repo will not break Vercel (they aren't imported), but they cause confusion. Remove them.

## AI provider

Standardized on **OpenAI** (one key). Whisper transcription requires OpenAI, and chat/summaries use `gpt-4o-mini`. Set:

```
OPENAI_API_KEY=sk-...
```

## Local run

```bash
pip install -r requirements.txt
python database.py     # create + seed local aftervisit.db
uvicorn main:app --reload --port 8000
# docs: http://localhost:8000/docs
```

## Demo credentials (from the seed)

- Doctor:  `doctor@aftervisit.com` / `doctor123`
- Patient: `patient@aftervisit.com` / `patient123`

## Deploy to Vercel with Turso (persistent)

Data now **persists** via Turso (libSQL). `database.py` auto-detects: if `TURSO_DATABASE_URL` is set it uses Turso; otherwise it uses a local sqlite file for dev. Your app code didn't change — a compatibility shim handles it.

**Steps:**

1. **Create the Turso DB** — easiest via the Vercel Marketplace:
   Vercel dashboard → your project → **Integrations / Storage** → add **Turso Cloud** → create a database and **connect it to this project**. That automatically injects `TURSO_DATABASE_URL` and `TURSO_AUTH_TOKEN` into your Vercel env.
   *(CLI alternative: `turso db create aftervisit`, then `turso db show --url aftervisit` and `turso db tokens create aftervisit`, and add both as env vars in Vercel.)*

2. **Add `OPENAI_API_KEY`** in Vercel → Settings → Environment Variables.

3. **Deploy.** On first cold start the app creates the tables and seeds the demo data into Turso (idempotent — it skips if users already exist). After that, registrations, visits, medicine logs, etc. **persist**.

4. **Verify:** open `/docs`, log in with a demo account, create a visit, redeploy — the data is still there.

### Local development
No Turso needed locally. Just:
```bash
pip install -r requirements.txt
python database.py            # seeds a local aftervisit.db
uvicorn main:app --reload
```

### Known limitations (honest notes)
- The libSQL sync client is shared per serverless instance. Vercel isolates concurrent invocations, so this is fine; if you ever run this under a multi-threaded server with high concurrency, move to the async libSQL client.
- `commit()` is a no-op on Turso (each statement auto-commits). This app has no multi-statement rollback dependencies, so behaviour is unchanged.
- Keep `bcrypt==4.0.1` pinned — `passlib==1.7.4` breaks with bcrypt ≥ 4.1.

## Env vars

```
OPENAI_API_KEY=sk-...                 # AI chat, symptoms, scribe (required)
TURSO_DATABASE_URL=libsql://...       # set by the Vercel↔Turso integration
TURSO_AUTH_TOKEN=...                  # set by the Vercel↔Turso integration
DB_PATH=aftervisit.db                 # optional, local dev only
```

## Key API routes

### Auth
- `POST /api/auth/register`
- `POST /api/auth/login`
- `GET  /api/auth/me`

### Patient
- `GET  /api/patient/profile` · `GET /api/patient/overview`
- `GET  /api/patient/medicines` · `GET /api/patient/medicines/logs` · `POST /api/patient/medicines/log`
- `GET  /api/patient/visits` · `GET /api/patient/lab-reports`
- `GET  /api/patient/alerts` · `POST /api/patient/alerts/read`
- `GET  /api/patient/followups` · `POST /api/patient/symptoms`

### AI Chat
- `POST /api/chat` · `GET /api/chat/history`

### AI Scribe (record visit)
- `POST /api/scribe/transcribe`  — multipart audio → `{ transcript }` (Whisper)
- `POST /api/scribe/summarize`   — `{ transcript }` → structured DRAFT (doctor-only)
- `POST /api/doctor/visits`      — save the **doctor-approved** summary to the patient's record

**Scribe flow:** record audio → `transcribe` → `summarize` (AI draft) → doctor edits/approves → `POST /api/doctor/visits` to save. Nothing reaches the patient until the doctor approves.

### Doctor
- `GET  /api/doctor/dashboard` · `GET /api/doctor/patients` · `GET /api/doctor/patients/{id}`
- `POST /api/doctor/visits`
- `GET  /api/doctor/escalations` · `PATCH /api/doctor/escalations/{id}/resolve`
- `GET  /api/doctor/compliance-report`

## Notes

- AI provider is OpenAI (`gpt-4o-mini` for chat/summaries, Whisper for transcription).
- Persistence is Turso (libSQL) in production, local sqlite in dev — handled automatically by `database.py`.
