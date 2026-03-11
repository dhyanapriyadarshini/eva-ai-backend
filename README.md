# Eva AI Assistant 🧠
> **Think it. Say it. Done.**

Eva is a full-stack AI assistant built for **busy parents** — people juggling jobs, kids, school runs and zero spare time. Speak or type a task naturally, and Eva handles the rest: parsing intent, building plans, detecting calendar conflicts, summarising your inbox and keeping you focused when the day goes sideways.

**Live app → [eva-ai-backend.onrender.com](https://eva-ai-backend.onrender.com)**  
**API docs → [eva-ai-backend.onrender.com/docs](https://eva-ai-backend.onrender.com/docs)**  
**Database proof → [eva-ai-backend.onrender.com/db-status](https://eva-ai-backend.onrender.com/db-status)**  
**Health check → [eva-ai-backend.onrender.com/health](https://eva-ai-backend.onrender.com/health)**

> ⚡ Hosted on Render free tier — first request may take 30–60s to wake up.

---

## Tech Stack

| Layer | Technology |
|---|---|
| **Backend** | FastAPI (Python) |
| **LLM** | Groq API — LLaMA 3.3-70b-versatile |
| **Database** | SQLite (`eva.db`) — 5 tables, persists on Render |
| **Frontend** | Single-page HTML/CSS/JS served via FastAPI `FileResponse` |
| **Hosting** | Render — autodeploys from GitHub on every push |
| **Voice Input** | Web Speech API (Chrome/Safari native, no external service) |

---

## Features & API Endpoints

### 🤖 AI-Powered Endpoints (Groq LLaMA)

| Method | Endpoint | Feature | Description |
|---|---|---|---|
| `POST` | `/speak-it` | **Speak It** | Natural language → structured task. Vague inputs trigger a clarification loop — Eva asks a follow-up rather than saving bad data. |
| `POST` | `/focus-mode` | **Focus Mode** | The chaos button. Eva ranks all pending tasks and surfaces the top 3. Tasks rescheduled 3+ times are flagged as a **habit audit**. |
| `POST` | `/shift-it` | **Shift It** | One-tap recovery. Reschedules selected tasks intelligently across the next 72 hours, never double-booking. |
| `POST` | `/smart-block` | **Smart Block** | Detects work/life calendar conflicts. Auto-drafts a reschedule message — parent just approves with one tap. |
| `POST` | `/plan-it` | **Plan It** | Goal text → protected 4–6 week plan with weekly sessions, milestones and a snooze warning if the goal keeps getting skipped. |
| `POST` | `/email-digest` | **Email Digest** | Inbox summary with urgency flags. High-sensitivity emails (angry/legal) are **forced to manual review** — Eva never sends without explicit confirmation. |

### 📋 CRUD Endpoints (SQLite)

| Method | Endpoint | Description |
|---|---|---|
| `GET / POST / PUT / DELETE` | `/tasks` | Full task management — filter by status or category |
| `GET / POST / PUT / DELETE` | `/quick-list` | Grocery and errand list with **duplicate detection** |
| `GET` | `/goals` | View all saved goal plans |
| `GET` | `/goals/{id}` | View a single goal with full weekly plan |
| `GET` | `/smart-blocks` | View all saved calendar conflicts |
| `GET` | `/email-digests` | View all saved inbox digests |
| `PUT` | `/email-digests/{id}/approve` | Human-in-the-loop: approve a draft email reply |

### 🛠 Utility Endpoints

| Endpoint | Description |
|---|---|
| `GET /health` | Returns `{"message": "Eva is running. Think it. Say it. Done.", "version": "2.0.0"}` |
| `GET /db-status` | Live SQLite proof — shows all 5 tables and current row counts |
| `GET /docs` | Interactive Swagger UI — test every endpoint in the browser |

---

## Database Schema

Eva uses **SQLite (`eva.db`)** with 5 tables, auto-created on startup:

```
tasks          — title, description, due_date, due_time, priority, category, reschedule_count
goals          — title, description, target_date, plan (JSON), status
quick_list     — item, checked
smart_blocks   — event_title, conflict_with, suggested_reschedule, draft_message
email_digests  — subject, summary, urgency, draft_reply, approved
```

Live table counts visible at [`/db-status`](https://eva-ai-backend.onrender.com/db-status).

---

## Run Locally

```bash
# 1. Clone the repo
git clone https://github.com/dhyanapriyadarshini/eva-ai-backend
cd eva-ai-backend

# 2. Install dependencies
pip install -r requirements.txt

# 3. Set your Groq API key (get one free at console.groq.com)
export GROQ_API_KEY=your_key_here

# 4. Start the server
uvicorn main:app --reload

# 5. Open the app
open http://localhost:8000

# Or open the interactive API docs
open http://localhost:8000/docs
```

---

## Deploy to Render

1. Push this repo to GitHub
2. Go to [render.com](https://render.com) → **New → Web Service**
3. Connect your GitHub repo
4. Set **Build Command:** `pip install -r requirements.txt`
5. Set **Start Command:** `uvicorn main:app --host 0.0.0.0 --port $PORT`
6. Add environment variable: `GROQ_API_KEY` = your Groq API key
7. Click **Deploy**

Render will autodeploy on every GitHub push.

---

## Example API Calls

Try these in the [live Swagger docs](https://eva-ai-backend.onrender.com/docs):

**Speak It** — parse a natural language task:
```json
POST /speak-it
{ "voice_input": "dentist for Jake Tuesday 3pm urgent" }
```

**Plan It** — generate a weekly goal plan:
```json
POST /plan-it
{ "goal": "Run a 5K in 3 months, early mornings only" }
```

**Focus Mode** — get today's top 3 priorities:
```json
POST /focus-mode
{}
```

**Smart Block** — check for a calendar conflict:
```json
POST /smart-block
{
  "new_event_title": "Team standup",
  "new_event_date": "2025-03-15",
  "new_event_time": "09:00",
  "protected_events": ["School run 8:45am", "Jake football 5pm"]
}
```

---

## Project Structure

```
eva-ai-backend/
├── main.py           # FastAPI app — all 12 endpoints + SQLite + Groq integration
├── index.html        # Frontend — served by FastAPI FileResponse at GET /
├── requirements.txt  # fastapi, uvicorn, groq, pydantic
├── Procfile          # Render start command
└── README.md
```

---

## Key Design Decisions

**Human-in-the-loop for emails** — Eva drafts replies but never sends automatically. Every reply requires explicit approval via `PUT /email-digests/{id}/approve`. High-sensitivity emails (legal, angry, complaints) are blocked from drafting entirely and flagged for manual review.

**Clarification loop** — `/speak-it` detects vague input and returns a follow-up question rather than saving low-quality data. E.g. "remind me about the thing" → Eva asks "Is this the school fundraiser or the car service?"

**Habit audit** — any task rescheduled 3+ times is flagged by Focus Mode and Shift It, prompting the user to either commit to a hard deadline or drop it.

**API key security** — `GROQ_API_KEY` is stored as a Render environment variable. It is never in source code or committed to GitHub.

---

## Built By

Rahini · Luca · Dhyana — CS Assignment Project, 2025

---

*Eva — Think it. Say it. Done.*
