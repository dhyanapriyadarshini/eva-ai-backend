from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import sqlite3
import os
import json
from datetime import datetime
import google.generativeai as genai

# ─── App Setup ───────────────────────────────────────────────────────────────
app = FastAPI(title="Eva AI Assistant", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

genai.configure(api_key=os.environ.get("GOOGLE_API_KEY"))
client = genai.GenerativeModel("gemini-1.5-flash")
MODEL = "gemini-1.5-flash"

# Eva's core personality — used across all prompts
EVA_PERSONA = """You are Eva — a sharp, witty AI assistant built for busy parents juggling jobs, kids, school runs, and zero time.
Your tone: sassy but warm, direct, zero fluff. Like a hyper-organised best friend who gets things done.
You speak like a real person — short sentences, occasional dry humour, always practical. Never lecture. Never waffle."""

# ─── Database Setup ──────────────────────────────────────────────────────────
DB_PATH = "eva.db"

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            due_date TEXT,
            due_time TEXT,
            priority TEXT DEFAULT 'medium',
            status TEXT DEFAULT 'pending',
            category TEXT DEFAULT 'personal',
            reschedule_count INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            target_date TEXT,
            plan TEXT,
            status TEXT DEFAULT 'active',
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS quick_list (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item TEXT NOT NULL,
            checked INTEGER DEFAULT 0,
            added_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS smart_blocks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_title TEXT NOT NULL,
            conflict_with TEXT,
            suggested_reschedule TEXT,
            draft_message TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS email_digests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject TEXT,
            summary TEXT,
            urgency TEXT DEFAULT 'low',
            draft_reply TEXT,
            approved INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        );
    """)
    conn.commit()
    conn.close()

init_db()

# ─── Models ──────────────────────────────────────────────────────────────────
class TaskCreate(BaseModel):
    title: str
    description: Optional[str] = None
    due_date: Optional[str] = None
    due_time: Optional[str] = None
    priority: Optional[str] = "medium"
    category: Optional[str] = "personal"

class TaskUpdate(BaseModel):
    title: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    due_date: Optional[str] = None
    due_time: Optional[str] = None

class SpeakItRequest(BaseModel):
    voice_input: str

class GoalRequest(BaseModel):
    goal: str

class FocusRequest(BaseModel):
    task_ids: Optional[List[int]] = None

class QuickListItem(BaseModel):
    item: str

class ShiftItRequest(BaseModel):
    task_ids: List[int]

class SmartBlockRequest(BaseModel):
    new_event_title: str
    new_event_date: str
    new_event_time: str
    protected_events: List[str]

class EmailDigestRequest(BaseModel):
    emails: List[dict]

class ApproveEmailRequest(BaseModel):
    email_id: int

# ─── Helper: Call OpenAI ─────────────────────────────────────────────────────
def ask_eva(prompt: str, temperature: float = 0.2) -> str:
    try:
        full_prompt = f"{EVA_PERSONA}\n\n{prompt}"
        response = client.generate_content(
            full_prompt,
            generation_config={
                "temperature": temperature,
                "max_output_tokens": 2048,
            }
        )
        text = response.text.strip()
        text = text.replace("```json", "").replace("```", "").strip()
        return text
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gemini error: {str(e)}")

# ─── Root — serve frontend ────────────────────────────────────────────────────
@app.get("/")
def root():
    return FileResponse("index.html")

@app.get("/health")
def health():
    return {"message": "Eva is running. Think it. Say it. Done.", "version": "2.0.0"}

# ─── SPEAK IT — Voice/text → structured task ─────────────────────────────────
@app.post("/speak-it")
def speak_it(req: SpeakItRequest):
    """
    Hands-free task capture. Eva parses natural language into a structured task.
    Edge case: vague commands trigger a clarification loop.
    """
    prompt = f"""The user said: "{req.voice_input}"
Today's date is {datetime.now().strftime('%Y-%m-%d')}.

Extract the task and respond ONLY with valid JSON:
{{
  "title": "short task title",
  "description": "optional detail",
  "due_date": "YYYY-MM-DD or null",
  "due_time": "HH:MM or null",
  "priority": "high, medium, or low",
  "category": "work, family, personal, health, or errand",
  "needs_clarification": false,
  "clarification_question": null,
  "eva_quip": "a short sassy one-liner confirming the task or asking for clarification"
}}

IMPORTANT: If the input is too vague (e.g. 'remind me about the thing'), set needs_clarification to true
and write a clarification_question like "Is this for the school fundraiser or the car service?"
Never save a task without enough information.
Do not include any text outside the JSON."""

    raw = ask_eva(prompt)

    try:
        # Strip markdown code fences if present
        clean = raw.replace("```json", "").replace("```", "").strip()
        parsed = json.loads(clean)
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail=f"AI response could not be parsed: {raw}")

    if parsed.get("needs_clarification"):
        return {
            "status": "needs_clarification",
            "question": parsed.get("clarification_question"),
            "eva_quip": parsed.get("eva_quip"),
            "original_input": req.voice_input
        }

    conn = get_db()
    cursor = conn.execute(
        "INSERT INTO tasks (title, description, due_date, due_time, priority, category) VALUES (?, ?, ?, ?, ?, ?)",
        (parsed["title"], parsed.get("description"), parsed.get("due_date"),
         parsed.get("due_time"), parsed.get("priority", "medium"), parsed.get("category", "personal"))
    )
    conn.commit()
    task_id = cursor.lastrowid
    conn.close()

    return {
        "status": "created",
        "task_id": task_id,
        "task": parsed,
        "eva_quip": parsed.get("eva_quip", "Done. You're welcome."),
        "message": f"Task '{parsed['title']}' saved successfully."
    }

# ─── FOCUS MODE — Surface top 3 priorities ───────────────────────────────────
@app.post("/focus-mode")
def focus_mode(req: FocusRequest):
    """
    The Chaos Button. Eva surfaces top 3 priorities and defers everything else.
    From the presentation: day goes sideways → one tap → top 3, rest deferred.
    """
    conn = get_db()
    tasks = conn.execute(
        "SELECT * FROM tasks WHERE status = 'pending' ORDER BY priority DESC, due_date ASC LIMIT 20"
    ).fetchall()
    conn.close()

    if not tasks:
        return {
            "status": "no_tasks",
            "message": "Nothing pending. Eva's impressed. Genuinely.",
            "top_3": []
        }

    task_list = [dict(t) for t in tasks]

    prompt = f"""These are the user's pending tasks: {json.dumps(task_list)}
Today is {datetime.now().strftime('%Y-%m-%d %H:%M')}.

The parent's day has gone sideways. Pick the TOP 3 most critical tasks based on:
1. Deadline urgency (overdue = highest priority)
2. Priority level (high > medium > low)
3. Category importance (family > work > personal)

Also check: if any task has been rescheduled 3+ times (reschedule_count >= 3), flag it as a "habit audit" case.

Respond ONLY with valid JSON:
{{
  "top_3": [
    {{"id": 1, "title": "task", "reason": "why Eva picked this", "urgency": "high/medium/low"}}
  ],
  "deferred": [2, 3, 4],
  "habit_audit": [
    {{"id": 5, "title": "task", "message": "This has been rescheduled 3 times. Keep it, set a hard deadline, or drop it?"}}
  ],
  "eva_message": "sassy but motivational one-liner for the parent"
}}
Do not include text outside the JSON."""

    raw = ask_eva(prompt)

    try:
        clean = raw.replace("```json", "").replace("```", "").strip()
        parsed = json.loads(clean)
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail=f"AI response could not be parsed: {raw}")

    return {"status": "success", "focus": parsed}

# ─── SHIFT IT — Reschedule tasks (The Chaos Button) ──────────────────────────
@app.post("/shift-it")
def shift_it(req: ShiftItRequest):
    """
    One-tap recovery. Eva scans next 72hrs for white space and moves tasks intelligently.
    Edge case: total week failure — Eva finds true white space across 3 days.
    """
    conn = get_db()
    tasks = []
    for tid in req.task_ids:
        task = conn.execute("SELECT * FROM tasks WHERE id = ?", (tid,)).fetchone()
        if task:
            tasks.append(dict(task))
    conn.close()

    if not tasks:
        raise HTTPException(status_code=404, detail="No tasks found with those IDs")

    prompt = f"""These tasks need to be rescheduled: {json.dumps(tasks)}
Today is {datetime.now().strftime('%Y-%m-%d')}.

The parent's day collapsed. Find new slots across the next 72 hours.
Rules:
- Urgent/high priority tasks go to tomorrow morning
- Medium priority tasks go to day after tomorrow
- Low priority tasks go to 3 days from now
- Never double-book (space tasks at least 1 hour apart)
- Increment the reschedule_count for each task
- If any task already has reschedule_count >= 2, flag it

Respond ONLY with valid JSON:
{{
  "rescheduled": [
    {{"id": 1, "new_date": "YYYY-MM-DD", "new_time": "HH:MM", "reason": "why this slot", "new_reschedule_count": 1}}
  ],
  "flagged": [
    {{"id": 5, "title": "task title", "reschedule_count": 3, "message": "This keeps slipping. Drop it or set a hard deadline?"}}
  ],
  "summary": "One sassy sentence summarising what Eva moved and why."
}}
Do not include text outside the JSON."""

    raw = ask_eva(prompt)

    try:
        clean = raw.replace("```json", "").replace("```", "").strip()
        parsed = json.loads(clean)
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail=f"AI response could not be parsed: {raw}")

    # Apply rescheduled dates and update reschedule counts
    conn = get_db()
    for item in parsed.get("rescheduled", []):
        conn.execute(
            "UPDATE tasks SET due_date = ?, due_time = ?, reschedule_count = ? WHERE id = ?",
            (item["new_date"], item["new_time"], item.get("new_reschedule_count", 1), item["id"])
        )
    conn.commit()
    conn.close()

    return {"status": "rescheduled", "result": parsed}

# ─── SMART BLOCK — Detect calendar conflicts ─────────────────────────────────
@app.post("/smart-block")
def smart_block(req: SmartBlockRequest):
    """
    Auto-detects work/life calendar clashes.
    Eva drafts a reschedule message automatically — parent just approves.
    Edge case: unmovable hard-deadline conflict → Eva drafts message + flags partner.
    """
    prompt = f"""A new event just landed: "{req.new_event_title}" on {req.new_event_date} at {req.new_event_time}.
Protected events that cannot move: {json.dumps(req.protected_events)}
Today is {datetime.now().strftime('%Y-%m-%d')}.

Check if there's a conflict. If yes, draft a polite reschedule message to the organiser.

Respond ONLY with valid JSON:
{{
  "conflict_detected": true,
  "conflicting_with": "name of the protected event it clashes with",
  "conflict_severity": "hard (can't move) or soft (can reschedule)",
  "suggested_new_time": "HH:MM on YYYY-MM-DD",
  "draft_message": "Dear [Organiser], I have a prior commitment at [time]. Could we move this to [suggested time]? Best regards.",
  "eva_quip": "sassy one-liner about the conflict",
  "action": "reschedule or keep"
}}
If no conflict, set conflict_detected to false and leave other fields null.
Do not include text outside the JSON."""

    raw = ask_eva(prompt)

    try:
        clean = raw.replace("```json", "").replace("```", "").strip()
        parsed = json.loads(clean)
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail=f"AI response could not be parsed: {raw}")

    # Save to DB if conflict detected
    if parsed.get("conflict_detected"):
        conn = get_db()
        conn.execute(
            "INSERT INTO smart_blocks (event_title, conflict_with, suggested_reschedule, draft_message) VALUES (?, ?, ?, ?)",
            (req.new_event_title, parsed.get("conflicting_with"),
             parsed.get("suggested_new_time"), parsed.get("draft_message"))
        )
        conn.commit()
        conn.close()

    return {"status": "success", "result": parsed}

# ─── PLAN IT — Goal → Weekly plan ────────────────────────────────────────────
@app.post("/plan-it")
def plan_it(req: GoalRequest):
    """
    Smart goal-blocking. Eva finds and protects slots before the week fills up.
    Edge case: Snooze Loop — if same goal session rescheduled 3x, Eva flags it.
    """
    prompt = f"""The user wants to achieve: "{req.goal}"
Today's date is {datetime.now().strftime('%Y-%m-%d')}.

Create a realistic, actionable plan. Be specific — this is a busy parent with limited time.

Respond ONLY with valid JSON:
{{
  "goal_title": "short goal name",
  "target_date": "YYYY-MM-DD",
  "summary": "2-sentence overview",
  "weekly_sessions": [
    {{
      "week": 1,
      "focus": "what to do this week",
      "sessions_per_week": 3,
      "session_duration_minutes": 30,
      "suggested_days": ["Monday", "Wednesday", "Friday"],
      "suggested_time": "06:00",
      "protected": true
    }}
  ],
  "milestones": [
    {{"week": 4, "milestone": "milestone description"}}
  ],
  "tips": ["practical tip 1", "practical tip 2"],
  "snooze_warning": "What Eva will say if this goal keeps getting skipped"
}}
Keep to 4-6 weeks. Do not include text outside the JSON."""

    raw = ask_eva(prompt, temperature=0.3)

    try:
        clean = raw.replace("```json", "").replace("```", "").strip()
        parsed = json.loads(clean)
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail=f"AI response could not be parsed: {raw}")

    conn = get_db()
    cursor = conn.execute(
        "INSERT INTO goals (title, description, target_date, plan) VALUES (?, ?, ?, ?)",
        (parsed["goal_title"], parsed.get("summary"), parsed.get("target_date"), json.dumps(parsed))
    )
    conn.commit()
    goal_id = cursor.lastrowid
    conn.close()

    return {"status": "created", "goal_id": goal_id, "plan": parsed}

# ─── EMAIL DIGEST — Summarise inbox ──────────────────────────────────────────
@app.post("/email-digest")
def email_digest(req: EmailDigestRequest):
    """
    7AM inbox summary. Eva flags urgent emails and drafts replies for one-tap approval.
    Edge case: High-stakes/angry email → flagged as HIGH SENSITIVITY, forced manual review.
    Eva NEVER sends without explicit confirmation.
    """
    prompt = f"""Here are the user's emails: {json.dumps(req.emails)}
Today is {datetime.now().strftime('%Y-%m-%d')}.

Analyse each email and respond ONLY with valid JSON:
{{
  "digest": [
    {{
      "id": "email_id from input",
      "subject": "email subject",
      "urgency": "urgent, normal, or low",
      "sensitivity": "high (angry/legal/complaint) or normal",
      "summary": "1-2 sentence plain english summary",
      "action_needed": true,
      "draft_reply": "polite professional draft reply or null if no reply needed",
      "requires_manual_review": false,
      "manual_review_reason": null
    }}
  ],
  "urgent_count": 2,
  "normal_count": 5,
  "low_count": 43,
  "eva_summary": "One sassy sentence summarising the inbox situation"
}}
IMPORTANT: If an email seems angry, legal, or high-stakes, set requires_manual_review to true 
and explain why in manual_review_reason. Eva never sends these automatically.
Do not include text outside the JSON."""

    raw = ask_eva(prompt)

    try:
        clean = raw.replace("```json", "").replace("```", "").strip()
        parsed = json.loads(clean)
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail=f"AI response could not be parsed: {raw}")

    # Save digest to DB
    conn = get_db()
    for email in parsed.get("digest", []):
        conn.execute(
            "INSERT INTO email_digests (subject, summary, urgency, draft_reply) VALUES (?, ?, ?, ?)",
            (email.get("subject"), email.get("summary"),
             email.get("urgency", "low"), email.get("draft_reply"))
        )
    conn.commit()
    conn.close()

    return {"status": "success", "digest": parsed}

# ─── TASKS CRUD ───────────────────────────────────────────────────────────────
@app.get("/tasks")
def get_tasks(status: Optional[str] = None, category: Optional[str] = None):
    conn = get_db()
    query = "SELECT * FROM tasks WHERE 1=1"
    params = []
    if status:
        query += " AND status = ?"
        params.append(status)
    if category:
        query += " AND category = ?"
        params.append(category)
    query += " ORDER BY due_date ASC, priority DESC"
    tasks = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(t) for t in tasks]

@app.get("/tasks/{task_id}")
def get_task(task_id: int):
    conn = get_db()
    task = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    conn.close()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return dict(task)

@app.post("/tasks")
def create_task(task: TaskCreate):
    conn = get_db()
    cursor = conn.execute(
        "INSERT INTO tasks (title, description, due_date, due_time, priority, category) VALUES (?, ?, ?, ?, ?, ?)",
        (task.title, task.description, task.due_date, task.due_time, task.priority, task.category)
    )
    conn.commit()
    task_id = cursor.lastrowid
    conn.close()
    return {"id": task_id, **task.dict()}

@app.put("/tasks/{task_id}")
def update_task(task_id: int, task: TaskUpdate):
    conn = get_db()
    existing = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if not existing:
        conn.close()
        raise HTTPException(status_code=404, detail="Task not found")
    updates = {k: v for k, v in task.dict().items() if v is not None}
    if updates:
        set_clause = ", ".join([f"{k} = ?" for k in updates])
        conn.execute(f"UPDATE tasks SET {set_clause} WHERE id = ?", list(updates.values()) + [task_id])
        conn.commit()
    conn.close()
    return {"id": task_id, "updated": updates}

@app.delete("/tasks/{task_id}")
def delete_task(task_id: int):
    conn = get_db()
    conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    conn.commit()
    conn.close()
    return {"message": f"Task {task_id} deleted"}

# ─── QUICK LIST ───────────────────────────────────────────────────────────────
@app.get("/quick-list")
def get_quick_list():
    conn = get_db()
    items = conn.execute("SELECT * FROM quick_list WHERE checked = 0 ORDER BY added_at DESC").fetchall()
    conn.close()
    return [dict(i) for i in items]

@app.post("/quick-list")
def add_to_quick_list(item: QuickListItem):
    conn = get_db()
    existing = conn.execute("SELECT * FROM quick_list WHERE item = ? AND checked = 0", (item.item,)).fetchone()
    if existing:
        conn.close()
        return {"status": "duplicate", "message": f"'{item.item}' is already on your list. Pay attention. 😏"}
    cursor = conn.execute("INSERT INTO quick_list (item) VALUES (?)", (item.item,))
    conn.commit()
    item_id = cursor.lastrowid
    conn.close()
    return {"status": "added", "id": item_id, "item": item.item}

@app.put("/quick-list/{item_id}/check")
def check_quick_list_item(item_id: int):
    conn = get_db()
    conn.execute("UPDATE quick_list SET checked = 1 WHERE id = ?", (item_id,))
    conn.commit()
    conn.close()
    return {"status": "checked", "id": item_id}

@app.delete("/quick-list/{item_id}")
def delete_quick_list_item(item_id: int):
    conn = get_db()
    conn.execute("DELETE FROM quick_list WHERE id = ?", (item_id,))
    conn.commit()
    conn.close()
    return {"message": f"Item {item_id} removed"}

# ─── GOALS ────────────────────────────────────────────────────────────────────
@app.get("/goals")
def get_goals():
    conn = get_db()
    goals = conn.execute("SELECT * FROM goals ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(g) for g in goals]

@app.get("/goals/{goal_id}")
def get_goal(goal_id: int):
    conn = get_db()
    goal = conn.execute("SELECT * FROM goals WHERE id = ?", (goal_id,)).fetchone()
    conn.close()
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found")
    result = dict(goal)
    if result.get("plan"):
        result["plan"] = json.loads(result["plan"])
    return result

# ─── SMART BLOCKS ─────────────────────────────────────────────────────────────
@app.get("/smart-blocks")
def get_smart_blocks():
    conn = get_db()
    blocks = conn.execute("SELECT * FROM smart_blocks ORDER BY created_at DESC LIMIT 20").fetchall()
    conn.close()
    return [dict(b) for b in blocks]

# ─── EMAIL DIGESTS ────────────────────────────────────────────────────────────
@app.get("/email-digests")
def get_email_digests():
    conn = get_db()
    digests = conn.execute("SELECT * FROM email_digests ORDER BY created_at DESC LIMIT 50").fetchall()
    conn.close()
    return [dict(d) for d in digests]

@app.put("/email-digests/{email_id}/approve")
def approve_email(email_id: int):
    """Parent explicitly approves a draft reply — Eva never sends without this."""
    conn = get_db()
    conn.execute("UPDATE email_digests SET approved = 1 WHERE id = ?", (email_id,))
    conn.commit()
    conn.close()
    return {"status": "approved", "message": "Reply approved. Sending now. ✓"}
