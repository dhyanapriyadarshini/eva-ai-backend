from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import sqlite3
import os
import json
from datetime import datetime
from groq import Groq

# ─── App Setup ───────────────────────────────────────────────────────────────
app = FastAPI(title="Eva AI Assistant", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Groq Client ─────────────────────────────────────────────────────────────
client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
MODEL = "llama-3.3-70b-versatile"

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

# ─── Root ─────────────────────────────────────────────────────────────────────
@app.get("/")
def root():
    return {"message": "Eva is running. Think it. Say it. Done.", "version": "1.0.0"}

# ─── SPEAK IT ────────────────────────────────────────────────────────────────
@app.post("/speak-it")
def speak_it(req: SpeakItRequest):
    prompt = f"""You are Eva, a smart AI assistant for busy parents.
The user said: "{req.voice_input}"

Extract the task information and respond ONLY with valid JSON in this exact format:
{{
  "title": "short task title",
  "description": "optional detail",
  "due_date": "YYYY-MM-DD or null",
  "due_time": "HH:MM or null",
  "priority": "high, medium, or low",
  "category": "work, family, personal, health, or errand",
  "needs_clarification": false,
  "clarification_question": null
}}

If the input is too vague (e.g. 'remind me about the thing'), set needs_clarification to true
and provide a clarification_question. Otherwise set it to false.
Today's date is {datetime.now().strftime('%Y-%m-%d')}. Do not include any text outside the JSON."""

    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
    )

    raw = response.choices[0].message.content.strip()

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail=f"AI response could not be parsed: {raw}")

    if parsed.get("needs_clarification"):
        return {
            "status": "needs_clarification",
            "question": parsed.get("clarification_question"),
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
        "message": f"Task '{parsed['title']}' saved successfully."
    }

# ─── PLAN IT ─────────────────────────────────────────────────────────────────
@app.post("/plan-it")
def plan_it(req: GoalRequest):
    prompt = f"""You are Eva, an AI life assistant for busy parents.
The user wants to achieve this goal: "{req.goal}"
Today's date is {datetime.now().strftime('%Y-%m-%d')}.

Create a realistic, actionable plan and respond ONLY with valid JSON:
{{
  "goal_title": "short goal name",
  "target_date": "YYYY-MM-DD",
  "summary": "2-sentence overview of the plan",
  "weekly_sessions": [
    {{
      "week": 1,
      "focus": "what to do this week",
      "sessions_per_week": 3,
      "session_duration_minutes": 30,
      "suggested_days": ["Monday", "Wednesday", "Friday"],
      "suggested_time": "06:00"
    }}
  ],
  "milestones": [
    {{"week": 4, "milestone": "first milestone description"}},
    {{"week": 8, "milestone": "second milestone description"}}
  ],
  "tips": ["tip 1", "tip 2"]
}}

Keep it to 4-6 weeks of weekly_sessions. Do not include any text outside the JSON."""

    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
    )

    raw = response.choices[0].message.content.strip()

    try:
        parsed = json.loads(raw)
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

# ─── FOCUS MODE ──────────────────────────────────────────────────────────────
@app.post("/focus-mode")
def focus_mode(req: FocusRequest):
    conn = get_db()
    tasks = conn.execute(
        "SELECT * FROM tasks WHERE status = 'pending' ORDER BY priority DESC, due_date ASC LIMIT 20"
    ).fetchall()
    conn.close()

    if not tasks:
        return {"status": "no_tasks", "message": "No pending tasks found.", "top_3": []}

    task_list = [dict(t) for t in tasks]

    prompt = f"""You are Eva, an AI assistant for busy parents.
Here are the user's pending tasks: {json.dumps(task_list)}
Today is {datetime.now().strftime('%Y-%m-%d %H:%M')}.

Pick the TOP 3 most important tasks to focus on RIGHT NOW based on:
1. Deadline urgency
2. Priority level
3. Category importance (family > work > personal)

Respond ONLY with valid JSON:
{{
  "top_3": [
    {{"id": 1, "title": "task title", "reason": "why this is in top 3"}},
    {{"id": 2, "title": "task title", "reason": "why this is in top 3"}},
    {{"id": 3, "title": "task title", "reason": "why this is in top 3"}}
  ],
  "deferred": [4, 5, 6],
  "message": "motivational one-liner for the parent"
}}
Do not include any text outside the JSON."""

    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
    )

    raw = response.choices[0].message.content.strip()

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail=f"AI response could not be parsed: {raw}")

    return {"status": "success", "focus": parsed}

# ─── SHIFT IT ────────────────────────────────────────────────────────────────
@app.post("/shift-it")
def shift_it(req: ShiftItRequest):
    conn = get_db()
    tasks = []
    for tid in req.task_ids:
        task = conn.execute("SELECT * FROM tasks WHERE id = ?", (tid,)).fetchone()
        if task:
            tasks.append(dict(task))
    conn.close()

    if not tasks:
        raise HTTPException(status_code=404, detail="No tasks found with those IDs")

    prompt = f"""You are Eva, a scheduling assistant for busy parents.
These tasks need to be rescheduled: {json.dumps(tasks)}
Today is {datetime.now().strftime('%Y-%m-%d')}.

Suggest new dates and times across the next 3 days.
Respond ONLY with valid JSON:
{{
  "rescheduled": [
    {{"id": 1, "new_date": "YYYY-MM-DD", "new_time": "HH:MM", "reason": "why this slot"}}
  ],
  "summary": "one sentence summary of what was moved"
}}
Do not include any text outside the JSON."""

    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
    )

    raw = response.choices[0].message.content.strip()

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail=f"AI response could not be parsed: {raw}")

    conn = get_db()
    for item in parsed.get("rescheduled", []):
        conn.execute(
            "UPDATE tasks SET due_date = ?, due_time = ? WHERE id = ?",
            (item["new_date"], item["new_time"], item["id"])
        )
    conn.commit()
    conn.close()

    return {"status": "rescheduled", "result": parsed}

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
        return {"status": "duplicate", "message": f"'{item.item}' is already on your list."}
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
