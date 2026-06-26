from fastapi import FastAPI, HTTPException, Depends, status, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timedelta, date
from passlib.context import CryptContext
from jose import JWTError, jwt
import sqlite3, json, httpx, os
from database import get_db, init_db, seed_demo_data

# ── CONFIG ─────────────────────────────────────────
SECRET_KEY = "aftervisit-secret-key-2026-nagpur"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_CHAT = "https://api.openai.com/v1/chat/completions"
OPENAI_AUDIO = "https://api.openai.com/v1/audio/transcriptions"

app = FastAPI(title="AfterVisit API", version="1.0.0")

app.add_middleware(CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"])

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

# ── STARTUP ────────────────────────────────────────
@app.on_event("startup")
def startup():
    init_db()
    seed_demo_data()

# ── MODELS ─────────────────────────────────────────
class UserRegister(BaseModel):
    name: str
    email: str
    password: str
    phone: Optional[str] = None
    role: str = "patient"
    city: Optional[str] = None

class Token(BaseModel):
    access_token: str
    token_type: str
    user: dict

class ChatMessage(BaseModel):
    message: str

class MedicineLog(BaseModel):
    medicine_id: int
    date: str
    taken: bool

class SymptomLog(BaseModel):
    symptom: str
    severity: str = "moderate"

class VisitCreate(BaseModel):
    patient_id: int
    chief_complaint: str
    diagnosis: str
    instructions: str
    bp: Optional[str] = None
    heart_rate: Optional[str] = None
    weight: Optional[str] = None
    temperature: Optional[str] = None
    spo2: Optional[str] = None
    next_visit: Optional[str] = None
    notes: Optional[str] = None

class AlertRead(BaseModel):
    alert_id: int

# ── AUTH HELPERS ───────────────────────────────────
def create_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def verify_token(token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid token")
        return int(user_id)
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

def get_current_user(user_id: int = Depends(verify_token)):
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    conn.close()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return dict(user)

def get_patient_id(user_id: int, conn):
    pat = conn.execute("SELECT id FROM patients WHERE user_id=?", (user_id,)).fetchone()
    return pat["id"] if pat else None

# ── OPENAI HELPER ──────────────────────────────────
def ai_complete(system: str, messages: list, max_tokens: int = 500, json_mode: bool = False):
    """One place for all OpenAI chat calls. Returns text, or None on failure."""
    if not OPENAI_API_KEY:
        return None
    body = {
        "model": "gpt-4o-mini",
        "max_tokens": max_tokens,
        "messages": [{"role": "system", "content": system}] + messages,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    try:
        r = httpx.post(
            OPENAI_CHAT,
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}",
                     "Content-Type": "application/json"},
            json=body, timeout=60)
        return r.json()["choices"][0]["message"]["content"]
    except Exception:
        return None

# ── AUTH ROUTES ────────────────────────────────────
@app.post("/api/auth/register")
def register(data: UserRegister):
    conn = get_db()
    existing = conn.execute("SELECT id FROM users WHERE email=?", (data.email,)).fetchone()
    if existing:
        conn.close()
        raise HTTPException(status_code=400, detail="Email already registered")
    pwd_hash = pwd_context.hash(data.password)
    cur = conn.execute(
        "INSERT INTO users (name,email,phone,password_hash,role,city) VALUES (?,?,?,?,?,?)",
        (data.name, data.email, data.phone, pwd_hash, data.role, data.city))
    user_id = cur.lastrowid
    if data.role == "patient":
        import random
        code = f"AV-2026-{random.randint(1000,9999)}"
        conn.execute("INSERT INTO patients (user_id, patient_code) VALUES (?,?)", (user_id, code))
    conn.commit()
    conn.close()
    token = create_token({"sub": str(user_id)})
    return {"access_token": token, "token_type": "bearer",
            "user": {"id": user_id, "name": data.name, "email": data.email, "role": data.role}}

@app.post("/api/auth/login")
def login(form: OAuth2PasswordRequestForm = Depends()):
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE email=?", (form.username,)).fetchone()
    conn.close()
    if not user or not pwd_context.verify(form.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = create_token({"sub": str(user["id"])})
    return {"access_token": token, "token_type": "bearer",
            "user": {"id": user["id"], "name": user["name"],
                     "email": user["email"], "role": user["role"]}}

@app.get("/api/auth/me")
def me(user = Depends(get_current_user)):
    return {"id": user["id"], "name": user["name"],
            "email": user["email"], "role": user["role"], "city": user["city"]}

# ── PATIENT ROUTES ─────────────────────────────────
@app.get("/api/patient/profile")
def patient_profile(user = Depends(get_current_user)):
    conn = get_db()
    pat = conn.execute("""
        SELECT p.*, u.name, u.email, u.phone, u.city,
               d.name as doctor_name
        FROM patients p
        JOIN users u ON p.user_id = u.id
        LEFT JOIN users d ON p.doctor_id = d.id
        WHERE p.user_id=?""", (user["id"],)).fetchone()
    conn.close()
    if not pat:
        raise HTTPException(status_code=404, detail="Patient profile not found")
    return dict(pat)

@app.get("/api/patient/overview")
def patient_overview(user = Depends(get_current_user)):
    conn = get_db()
    pat_id = get_patient_id(user["id"], conn)
    if not pat_id:
        conn.close()
        raise HTTPException(404, "Patient not found")

    # Compliance last 30 days
    today = date.today()
    start = (today - timedelta(days=29)).isoformat()
    logs = conn.execute("""
        SELECT COUNT(*) as total,
               SUM(taken) as taken_count
        FROM medicine_logs
        WHERE patient_id=? AND date>=?""", (pat_id, start)).fetchone()
    total = logs["total"] or 1
    taken = logs["taken_count"] or 0
    compliance = round((taken / total) * 100)

    # Latest BP from visit
    latest_visit = conn.execute("""
        SELECT bp, visit_date FROM visits
        WHERE patient_id=? ORDER BY visit_date DESC LIMIT 1""", (pat_id,)).fetchone()

    # Unread alerts
    unread = conn.execute("""
        SELECT COUNT(*) as cnt FROM alerts
        WHERE patient_id=? AND read_status=0""", (pat_id,)).fetchone()

    # Next followup
    followup = conn.execute("""
        SELECT scheduled_date, purpose FROM followups
        WHERE patient_id=? AND status='pending'
        ORDER BY scheduled_date ASC LIMIT 1""", (pat_id,)).fetchone()

    conn.close()
    return {
        "compliance_pct": compliance,
        "total_doses": total,
        "taken_doses": taken,
        "missed_doses": total - taken,
        "latest_bp": latest_visit["bp"] if latest_visit else "N/A",
        "last_visit_date": latest_visit["visit_date"] if latest_visit else None,
        "unread_alerts": unread["cnt"],
        "next_followup": dict(followup) if followup else None,
    }

@app.get("/api/patient/medicines")
def get_medicines(user = Depends(get_current_user)):
    conn = get_db()
    pat_id = get_patient_id(user["id"], conn)
    meds = conn.execute("""
        SELECT m.*, u.name as prescribed_by_name
        FROM medicines m
        LEFT JOIN users u ON m.prescribed_by = u.id
        WHERE m.patient_id=? AND m.active=1
        ORDER BY m.created_at""", (pat_id,)).fetchall()
    conn.close()
    return [dict(m) for m in meds]

@app.get("/api/patient/medicines/logs")
def get_medicine_logs(user = Depends(get_current_user)):
    conn = get_db()
    pat_id = get_patient_id(user["id"], conn)
    today = date.today()
    start = (today - timedelta(days=29)).isoformat()
    logs = conn.execute("""
        SELECT ml.*, m.name as medicine_name, m.color
        FROM medicine_logs ml
        JOIN medicines m ON ml.medicine_id = m.id
        WHERE ml.patient_id=? AND ml.date>=?
        ORDER BY ml.date DESC""", (pat_id, start)).fetchall()
    conn.close()
    return [dict(l) for l in logs]

@app.post("/api/patient/medicines/log")
def log_medicine(data: MedicineLog, user = Depends(get_current_user)):
    conn = get_db()
    pat_id = get_patient_id(user["id"], conn)
    conn.execute("""
        INSERT OR REPLACE INTO medicine_logs (patient_id, medicine_id, date, taken, taken_at)
        VALUES (?,?,?,?,?)""",
        (pat_id, data.medicine_id, data.date,
         1 if data.taken else 0,
         datetime.now().isoformat() if data.taken else None))
    conn.commit()
    conn.close()
    return {"success": True, "message": "Medicine log updated"}

@app.get("/api/patient/visits")
def get_visits(user = Depends(get_current_user)):
    conn = get_db()
    pat_id = get_patient_id(user["id"], conn)
    visits = conn.execute("""
        SELECT v.*, u.name as doctor_name, u.city as doctor_city
        FROM visits v
        JOIN users u ON v.doctor_id = u.id
        WHERE v.patient_id=?
        ORDER BY v.visit_date DESC""", (pat_id,)).fetchall()
    conn.close()
    return [dict(v) for v in visits]

@app.get("/api/patient/lab-reports")
def get_lab_reports(user = Depends(get_current_user)):
    conn = get_db()
    pat_id = get_patient_id(user["id"], conn)
    reports = conn.execute("""
        SELECT * FROM lab_reports
        WHERE patient_id=?
        ORDER BY report_date DESC""", (pat_id,)).fetchall()
    conn.close()
    result = []
    for r in reports:
        d = dict(r)
        try:
            d["results"] = json.loads(d["results"])
        except:
            pass
        result.append(d)
    return result

@app.get("/api/patient/alerts")
def get_alerts(user = Depends(get_current_user)):
    conn = get_db()
    pat_id = get_patient_id(user["id"], conn)
    alerts = conn.execute("""
        SELECT * FROM alerts WHERE patient_id=?
        ORDER BY created_at DESC""", (pat_id,)).fetchall()
    conn.close()
    return [dict(a) for a in alerts]

@app.post("/api/patient/alerts/read")
def mark_alert_read(data: AlertRead, user = Depends(get_current_user)):
    conn = get_db()
    conn.execute("UPDATE alerts SET read_status=1 WHERE id=?", (data.alert_id,))
    conn.commit()
    conn.close()
    return {"success": True}

@app.get("/api/patient/followups")
def get_followups(user = Depends(get_current_user)):
    conn = get_db()
    pat_id = get_patient_id(user["id"], conn)
    followups = conn.execute("""
        SELECT f.*, u.name as doctor_name
        FROM followups f
        JOIN users u ON f.doctor_id = u.id
        WHERE f.patient_id=?
        ORDER BY f.scheduled_date ASC""", (pat_id,)).fetchall()
    conn.close()
    return [dict(f) for f in followups]

@app.post("/api/patient/symptoms")
async def log_symptom(data: SymptomLog, user = Depends(get_current_user)):
    conn = get_db()
    pat_id = get_patient_id(user["id"], conn)

    # Get patient context for AI
    pat = conn.execute("""
        SELECT p.*, u.name FROM patients p
        JOIN users u ON p.user_id = u.id
        WHERE p.id=?""", (pat_id,)).fetchone()

    meds = conn.execute("""
        SELECT name, dose, timing FROM medicines
        WHERE patient_id=? AND active=1""", (pat_id,)).fetchall()
    med_list = ", ".join([f"{m['name']} ({m['timing']})" for m in meds])

    system_prompt = f"""You are AfterVisit AI for {pat['name']} ({pat['age']} years, {pat['condition']}).
Medicines: {med_list}.
Provide brief Hindi/Hinglish guidance for the reported symptom.
For emergency symptoms (chest pain, breathlessness, sudden weakness) — immediately say call 108.
Keep response under 4 lines. Never diagnose."""

    ai_response = "Symptom noted. Please consult your doctor if symptoms persist."
    escalated = 0

    emergency_keywords = ["chest pain", "seene mein dard", "breathless", "saans", "numbness", "sudden weakness"]
    if any(kw in data.symptom.lower() for kw in emergency_keywords):
        ai_response = "EMERGENCY: Yeh serious ho sakta hai. ABHI 108 pe call karein. Doctor ko alert bhej diya hai."
        escalated = 1

        # Create escalation
        conn.execute("""INSERT INTO escalations (patient_id, doctor_id, type, description, ai_action, status)
                       VALUES (?,?,?,?,?,?)""",
                     (pat_id, pat["doctor_id"], "emergency",
                      f"Emergency symptom reported: {data.symptom}",
                      "Patient directed to call 108. Doctor alerted.", "active"))

        # Create alert for doctor
        conn.execute("""INSERT INTO alerts (patient_id, alert_type, title, message, severity)
                       VALUES (?,?,?,?,?)""",
                     (pat_id, "emergency",
                      f"EMERGENCY: {pat['name']} reported {data.symptom}",
                      "Patient has been directed to call 108. Please follow up immediately.", "danger"))
    else:
        # AI response for non-emergency
        reply = ai_complete(system_prompt,
                            [{"role": "user", "content": f"Symptom reported: {data.symptom}"}],
                            max_tokens=300)
        if reply:
            ai_response = reply
        else:
            ai_response = "Symptom noted. Agar 30 min mein theek nahi hua — doctor ko call karein."

    conn.execute("""INSERT INTO symptom_logs (patient_id, symptom, severity, ai_response, escalated)
                   VALUES (?,?,?,?,?)""", (pat_id, data.symptom, data.severity, ai_response, escalated))
    conn.commit()
    conn.close()
    return {"ai_response": ai_response, "escalated": escalated}

# ── AI CHAT ────────────────────────────────────────
@app.post("/api/chat")
async def chat(data: ChatMessage, user = Depends(get_current_user)):
    conn = get_db()

    # Get patient context
    pat = conn.execute("""
        SELECT p.*, u.name FROM patients p
        JOIN users u ON p.user_id = u.id
        WHERE p.user_id=?""", (user["id"],)).fetchone()

    meds = conn.execute("""
        SELECT name, dose, timing FROM medicines
        WHERE patient_id=? AND active=1""",
        (pat["id"] if pat else 0,)).fetchall()

    # Get last 10 messages for context
    history = conn.execute("""
        SELECT role, message FROM chat_history
        WHERE user_id=?
        ORDER BY created_at DESC LIMIT 10""", (user["id"],)).fetchall()
    history = list(reversed([dict(h) for h in history]))

    if user["role"] == "patient" and pat:
        med_list = ", ".join([f"{m['name']} ({m['timing']})" for m in meds])
        system = f"""You are AfterVisit AI for {pat['name']} ({pat['age']} years, {pat['condition']}).
Medicines: {med_list}.
Reply in Hindi, Hinglish, or English matching the patient's language.
Keep responses SHORT (3-4 lines). Never diagnose. For emergency symptoms — call 108."""
    else:
        system = """You are AfterVisit Clinical AI. Provide evidence-based clinical guidance.
Reference Indian clinical context where relevant. Be concise and actionable."""

    messages = [{"role": h["role"], "content": h["message"]} for h in history]
    messages.append({"role": "user", "content": data.message})

    reply = ai_complete(system, messages, max_tokens=500)
    ai_reply = reply if reply else "Sorry, AI is not available right now. Please try again."

    # Save to history
    conn.execute("INSERT INTO chat_history (user_id, role, message) VALUES (?,?,?)",
                 (user["id"], "user", data.message))
    conn.execute("INSERT INTO chat_history (user_id, role, message) VALUES (?,?,?)",
                 (user["id"], "assistant", ai_reply))
    conn.commit()

    conn.close()
    return {"reply": ai_reply, "role": "assistant"}

@app.get("/api/chat/history")
def chat_history(user = Depends(get_current_user)):
    conn = get_db()
    history = conn.execute("""
        SELECT role, message, created_at FROM chat_history
        WHERE user_id=?
        ORDER BY created_at ASC LIMIT 50""", (user["id"],)).fetchall()
    conn.close()
    return [dict(h) for h in history]

# ── DOCTOR ROUTES ──────────────────────────────────
@app.get("/api/doctor/dashboard")
def doctor_dashboard(user = Depends(get_current_user)):
    if user["role"] != "doctor":
        raise HTTPException(403, "Doctor access only")
    conn = get_db()

    # All patients
    patients = conn.execute("""
        SELECT p.*, u.name, u.phone, u.city,
               (SELECT COUNT(*) FROM medicine_logs ml
                WHERE ml.patient_id=p.id AND ml.taken=1
                AND ml.date >= date('now','-30 days')) as taken_doses,
               (SELECT COUNT(*) FROM medicine_logs ml
                WHERE ml.patient_id=p.id
                AND ml.date >= date('now','-30 days')) as total_doses
        FROM patients p
        JOIN users u ON p.user_id = u.id
        WHERE p.doctor_id=?""", (user["id"],)).fetchall()

    patient_list = []
    for p in patients:
        d = dict(p)
        total = d["total_doses"] or 1
        taken = d["taken_doses"] or 0
        d["compliance_pct"] = round((taken / total) * 100)
        patient_list.append(d)

    # Active escalations
    escalations = conn.execute("""
        SELECT e.*, u.name as patient_name
        FROM escalations e
        JOIN patients p ON e.patient_id = p.id
        JOIN users u ON p.user_id = u.id
        WHERE e.doctor_id=? AND e.status='active'
        ORDER BY e.created_at DESC""", (user["id"],)).fetchall()

    # Pending followups
    followups = conn.execute("""
        SELECT f.*, u.name as patient_name
        FROM followups f
        JOIN patients p ON f.patient_id = p.id
        JOIN users u ON p.user_id = u.id
        WHERE f.doctor_id=? AND f.status='pending'
        ORDER BY f.scheduled_date ASC""", (user["id"],)).fetchall()

    conn.close()

    avg_compliance = round(sum(p["compliance_pct"] for p in patient_list) / len(patient_list)) if patient_list else 0

    return {
        "total_patients": len(patient_list),
        "avg_compliance": avg_compliance,
        "active_escalations": len([e for e in escalations]),
        "pending_followups": len([f for f in followups]),
        "patients": patient_list,
        "escalations": [dict(e) for e in escalations],
        "followups": [dict(f) for f in followups],
    }

@app.get("/api/doctor/patients")
def doctor_patients(user = Depends(get_current_user)):
    if user["role"] != "doctor":
        raise HTTPException(403, "Doctor access only")
    conn = get_db()
    patients = conn.execute("""
        SELECT p.*, u.name, u.phone, u.email, u.city,
               (SELECT COUNT(*) FROM medicine_logs ml
                WHERE ml.patient_id=p.id AND ml.taken=1
                AND ml.date >= date('now','-30 days')) as taken_doses,
               (SELECT COUNT(*) FROM medicine_logs ml
                WHERE ml.patient_id=p.id
                AND ml.date >= date('now','-30 days')) as total_doses,
               (SELECT COUNT(*) FROM chat_history ch
                JOIN users pu ON ch.user_id = pu.id
                JOIN patients pp ON pp.user_id = pu.id
                WHERE pp.id = p.id AND ch.created_at >= date('now','-30 days')) as ai_questions,
               (SELECT visit_date FROM visits v WHERE v.patient_id=p.id
                ORDER BY v.visit_date DESC LIMIT 1) as last_visit
        FROM patients p
        JOIN users u ON p.user_id = u.id
        WHERE p.doctor_id=?
        ORDER BY u.name""", (user["id"],)).fetchall()

    result = []
    for p in patients:
        d = dict(p)
        total = d["total_doses"] or 1
        taken = d["taken_doses"] or 0
        d["compliance_pct"] = round((taken / total) * 100)
        result.append(d)
    conn.close()
    return result

@app.get("/api/doctor/patients/{patient_id}")
def doctor_patient_detail(patient_id: int, user = Depends(get_current_user)):
    if user["role"] != "doctor":
        raise HTTPException(403, "Doctor access only")
    conn = get_db()
    pat = conn.execute("""
        SELECT p.*, u.name, u.phone, u.email, u.city
        FROM patients p
        JOIN users u ON p.user_id = u.id
        WHERE p.id=? AND p.doctor_id=?""", (patient_id, user["id"])).fetchone()
    if not pat:
        conn.close()
        raise HTTPException(404, "Patient not found")

    meds = conn.execute("SELECT * FROM medicines WHERE patient_id=? AND active=1", (patient_id,)).fetchall()
    visits = conn.execute("SELECT * FROM visits WHERE patient_id=? ORDER BY visit_date DESC", (patient_id,)).fetchall()
    alerts = conn.execute("SELECT * FROM alerts WHERE patient_id=? ORDER BY created_at DESC LIMIT 5", (patient_id,)).fetchall()

    conn.close()
    return {
        "patient": dict(pat),
        "medicines": [dict(m) for m in meds],
        "visits": [dict(v) for v in visits],
        "alerts": [dict(a) for a in alerts],
    }

@app.post("/api/doctor/visits")
def create_visit(data: VisitCreate, user = Depends(get_current_user)):
    if user["role"] != "doctor":
        raise HTTPException(403, "Doctor access only")
    conn = get_db()
    conn.execute("""
        INSERT INTO visits (patient_id, doctor_id, visit_date, chief_complaint,
                           diagnosis, instructions, bp, heart_rate, weight,
                           temperature, spo2, next_visit, notes)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (data.patient_id, user["id"], date.today().isoformat(),
         data.chief_complaint, data.diagnosis, data.instructions,
         data.bp, data.heart_rate, data.weight, data.temperature,
         data.spo2, data.next_visit, data.notes))

    # Create alert for patient
    conn.execute("""INSERT INTO alerts (patient_id, alert_type, title, message, severity)
                   VALUES (?,?,?,?,?)""",
                 (data.patient_id, "visit_summary",
                  "Visit summary received",
                  f"Dr. visit completed. Diagnosis: {data.diagnosis[:100]}...",
                  "success"))

    conn.commit()
    conn.close()
    return {"success": True, "message": "Visit recorded successfully"}

@app.get("/api/doctor/escalations")
def get_escalations(user = Depends(get_current_user)):
    if user["role"] != "doctor":
        raise HTTPException(403, "Doctor access only")
    conn = get_db()
    escalations = conn.execute("""
        SELECT e.*, u.name as patient_name, p.condition, p.age
        FROM escalations e
        JOIN patients p ON e.patient_id = p.id
        JOIN users u ON p.user_id = u.id
        WHERE e.doctor_id=?
        ORDER BY e.created_at DESC""", (user["id"],)).fetchall()
    conn.close()
    return [dict(e) for e in escalations]

@app.patch("/api/doctor/escalations/{esc_id}/resolve")
def resolve_escalation(esc_id: int, user = Depends(get_current_user)):
    conn = get_db()
    conn.execute("UPDATE escalations SET status='resolved' WHERE id=? AND doctor_id=?",
                 (esc_id, user["id"]))
    conn.commit()
    conn.close()
    return {"success": True}

@app.get("/api/doctor/compliance-report")
def compliance_report(user = Depends(get_current_user)):
    if user["role"] != "doctor":
        raise HTTPException(403, "Doctor access only")
    conn = get_db()
    patients = conn.execute("""
        SELECT p.id, u.name,
               COUNT(ml.id) as total_doses,
               SUM(ml.taken) as taken_doses
        FROM patients p
        JOIN users u ON p.user_id = u.id
        LEFT JOIN medicine_logs ml ON ml.patient_id = p.id
            AND ml.date >= date('now','-30 days')
        WHERE p.doctor_id=?
        GROUP BY p.id""", (user["id"],)).fetchall()

    result = []
    for p in patients:
        d = dict(p)
        total = d["total_doses"] or 1
        taken = d["taken_doses"] or 0
        d["compliance_pct"] = round((taken / total) * 100)
        result.append(d)

    avg = round(sum(p["compliance_pct"] for p in result) / len(result)) if result else 0
    conn.close()
    return {"patients": result, "avg_compliance": avg}

# ── AI SCRIBE (record visit) ───────────────────────
SCRIBE_SYS = """You are a clinical scribe for an Indian doctor.
From the consultation transcript, extract a STRUCTURED DRAFT for the doctor to review.
Use ONLY information present in the transcript. Do NOT invent diagnoses, drugs, doses, or dates.
If something was not said, leave that field empty. This draft is verified by a doctor before any patient sees it.
Return ONLY valid JSON with keys:
{"diagnosis":"","key_points":[],"medications":[],"follow_up":"","warning_signs":[],"patient_summary":""}
patient_summary should be simple plain language (Hindi/Hinglish ok if the transcript is)."""

class TranscriptIn(BaseModel):
    transcript: str

@app.post("/api/scribe/transcribe")
async def scribe_transcribe(audio: UploadFile = File(...)):
    """Word-for-word transcription of consultation audio via Whisper."""
    if not OPENAI_API_KEY:
        raise HTTPException(500, "OPENAI_API_KEY not set")
    raw = await audio.read()
    try:
        r = httpx.post(
            OPENAI_AUDIO,
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            data={"model": "whisper-1"},
            files={"file": (audio.filename or "visit.webm", raw, audio.content_type or "audio/webm")},
            timeout=120)
        return {"transcript": r.json().get("text", "")}
    except Exception as e:
        raise HTTPException(500, f"Transcription failed: {e}")

@app.post("/api/scribe/summarize")
def scribe_summarize(body: TranscriptIn, user = Depends(get_current_user)):
    """Transcript -> structured AI DRAFT. Doctor reviews before saving via /api/doctor/visits."""
    if user["role"] != "doctor":
        raise HTTPException(403, "Doctor access only")
    if not body.transcript.strip():
        raise HTTPException(400, "transcript is required")
    out = ai_complete(SCRIBE_SYS, [{"role": "user", "content": body.transcript}],
                      max_tokens=800, json_mode=True)
    try:
        s = json.loads(out)
    except Exception:
        s = {}
    return {
        "diagnosis": s.get("diagnosis", "") or "",
        "key_points": s.get("key_points", []) or [],
        "medications": s.get("medications", []) or [],
        "follow_up": s.get("follow_up", "") or "",
        "warning_signs": s.get("warning_signs", []) or [],
        "patient_summary": s.get("patient_summary", "") or "",
    }

# ── HEALTH CHECK ───────────────────────────────────
@app.get("/")
def root():
    return {
        "status": "running",
        "app": "AfterVisit API",
        "version": "1.0.0",
        "docs": "/docs"
    }

@app.get("/api/health")
def health():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
