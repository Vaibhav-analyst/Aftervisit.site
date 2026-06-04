from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, List
import sys, os
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from database import get_db
from routes.auth import get_current_user, require_doctor

router = APIRouter(prefix="/doctor", tags=["doctor"])

# ── SCHEMAS ──────────────────────────────────────────────────────
class VisitCreate(BaseModel):
    patient_id: int
    chief_complaint: str
    diagnosis: str
    notes: Optional[str] = None
    follow_up_date: Optional[str] = None

class VitalsCreate(BaseModel):
    patient_id: int
    visit_id: int
    bp_sys: Optional[int] = None
    bp_dia: Optional[int] = None
    heart_rate: Optional[int] = None
    temperature: Optional[float] = None
    weight: Optional[float] = None
    spo2: Optional[int] = None

class MedicineCreate(BaseModel):
    patient_id: int
    visit_id: int
    name: str
    dose: str
    frequency: str
    timing: str
    duration: Optional[str] = None
    instructions: Optional[str] = None

class ScribeNoteCreate(BaseModel):
    patient_id: int
    visit_id: Optional[int] = None
    raw_transcript: str
    ai_summary: str

class AlertCreate(BaseModel):
    patient_id: int
    alert_type: str
    title: str
    message: str
    severity: str = "medium"

class EscalationUpdate(BaseModel):
    status: str
    notes: Optional[str] = None

# ── DASHBOARD ────────────────────────────────────────────────────
@router.get("/dashboard")
def get_dashboard(current_user: dict = Depends(require_doctor)):
    db = get_db()
    try:
        doctor_id = current_user["user_id"]

        # All patients
        patients = db.execute("""
            SELECT p.*, u.name, u.email, u.phone
            FROM patients p
            JOIN users u ON p.user_id = u.id
            WHERE p.doctor_id = ?
        """, (doctor_id,)).fetchall()

        # Today's OPD
        today_visits = db.execute("""
            SELECT v.*, u.name as patient_name, p.condition
            FROM visits v
            JOIN patients p ON v.patient_id = p.id
            JOIN users u ON p.user_id = u.id
            WHERE v.doctor_id = ? AND date(v.visit_date) = date('now')
            ORDER BY v.created_at
        """, (doctor_id,)).fetchall()

        # Open escalations
        escalations = db.execute("""
            SELECT e.*, u.name as patient_name
            FROM escalations e
            JOIN patients p ON e.patient_id = p.id
            JOIN users u ON p.user_id = u.id
            WHERE e.doctor_id = ? AND e.status = 'open'
            ORDER BY e.created_at DESC
        """, (doctor_id,)).fetchall()

        # Average compliance across all patients
        compliance_data = db.execute("""
            SELECT AVG(CASE WHEN ml.taken = 1 THEN 100.0 ELSE 0.0 END) as avg_compliance
            FROM medicine_logs ml
            JOIN medicines m ON ml.medicine_id = m.id
            JOIN patients p ON m.patient_id = p.id
            WHERE p.doctor_id = ?
            AND ml.log_date >= date('now', '-30 days')
        """, (doctor_id,)).fetchone()

        # Overdue follow-ups
        overdue = db.execute("""
            SELECT f.*, u.name as patient_name
            FROM follow_ups f
            JOIN patients p ON f.patient_id = p.id
            JOIN users u ON p.user_id = u.id
            WHERE f.doctor_id = ?
            AND f.scheduled_date < date('now')
            AND f.status = 'pending'
            ORDER BY f.scheduled_date ASC
        """, (doctor_id,)).fetchall()

        # AI questions this week
        ai_count = db.execute("""
            SELECT COUNT(*) as cnt
            FROM ai_conversations ac
            JOIN patients p ON ac.patient_id = p.id
            WHERE p.doctor_id = ?
            AND ac.created_at >= date('now', '-7 days')
        """, (doctor_id,)).fetchone()

        # Per-patient compliance
        patient_compliance = []
        for pat in patients[:5]:
            comp = db.execute("""
                SELECT AVG(CASE WHEN taken = 1 THEN 100.0 ELSE 0.0 END) as comp
                FROM medicine_logs ml
                JOIN medicines m ON ml.medicine_id = m.id
                WHERE m.patient_id = ?
                AND ml.log_date >= date('now', '-30 days')
            """, (pat["id"],)).fetchone()
            patient_compliance.append({
                "name": pat["name"],
                "patient_id": pat["id"],
                "compliance": round(comp["comp"] or 0)
            })

        return {
            "stats": {
                "total_patients": len(patients),
                "today_visits": len(today_visits),
                "open_escalations": len(escalations),
                "avg_compliance": round(compliance_data["avg_compliance"] or 0),
                "overdue_followups": len(overdue),
                "ai_questions_week": ai_count["cnt"]
            },
            "today_opd": [dict(v) for v in today_visits],
            "open_escalations": [dict(e) for e in escalations],
            "overdue_follow_ups": [dict(o) for o in overdue],
            "patient_compliance": patient_compliance
        }
    finally:
        db.close()

# ── ALL PATIENTS ──────────────────────────────────────────────────
@router.get("/patients")
def get_all_patients(current_user: dict = Depends(require_doctor)):
    db = get_db()
    try:
        doctor_id = current_user["user_id"]
        patients = db.execute("""
            SELECT p.*, u.name, u.email, u.phone, u.city
            FROM patients p
            JOIN users u ON p.user_id = u.id
            WHERE p.doctor_id = ?
            ORDER BY u.name
        """, (doctor_id,)).fetchall()

        result = []
        for pat in patients:
            # Compliance
            comp = db.execute("""
                SELECT AVG(CASE WHEN taken=1 THEN 100.0 ELSE 0.0 END) as comp
                FROM medicine_logs ml
                JOIN medicines m ON ml.medicine_id = m.id
                WHERE m.patient_id = ?
                AND ml.log_date >= date('now', '-30 days')
            """, (pat["id"],)).fetchone()

            # Last visit
            last_visit = db.execute("""
                SELECT visit_date FROM visits WHERE patient_id = ?
                ORDER BY visit_date DESC LIMIT 1
            """, (pat["id"],)).fetchone()

            # AI questions count
            ai_cnt = db.execute("""
                SELECT COUNT(*) as cnt FROM ai_conversations
                WHERE patient_id = ? AND created_at >= date('now', '-30 days')
            """, (pat["id"],)).fetchone()

            # Active alerts
            alert_cnt = db.execute("""
                SELECT COUNT(*) as cnt FROM alerts
                WHERE patient_id = ? AND is_read = 0
            """, (pat["id"],)).fetchone()

            # Next follow-up
            next_fu = db.execute("""
                SELECT scheduled_date, status FROM follow_ups
                WHERE patient_id = ? AND scheduled_date >= date('now')
                AND status IN ('pending','confirmed')
                ORDER BY scheduled_date ASC LIMIT 1
            """, (pat["id"],)).fetchone()

            pat_dict = dict(pat)
            pat_dict["compliance"] = round(comp["comp"] or 0)
            pat_dict["last_visit"] = last_visit["visit_date"] if last_visit else None
            pat_dict["ai_questions"] = ai_cnt["cnt"]
            pat_dict["unread_alerts"] = alert_cnt["cnt"]
            pat_dict["next_follow_up"] = next_fu["scheduled_date"] if next_fu else None
            result.append(pat_dict)

        return {"patients": result, "total": len(result)}
    finally:
        db.close()

@router.get("/patients/{patient_id}")
def get_patient_detail(patient_id: int, current_user: dict = Depends(require_doctor)):
    db = get_db()
    try:
        doctor_id = current_user["user_id"]
        patient = db.execute("""
            SELECT p.*, u.name, u.email, u.phone, u.city
            FROM patients p JOIN users u ON p.user_id = u.id
            WHERE p.id = ? AND p.doctor_id = ?
        """, (patient_id, doctor_id)).fetchone()
        
        if not patient:
            raise HTTPException(status_code=404, detail="Patient not found")

        visits = db.execute("""
            SELECT * FROM visits WHERE patient_id = ?
            ORDER BY visit_date DESC LIMIT 5
        """, (patient_id,)).fetchall()

        medicines = db.execute("""
            SELECT * FROM medicines WHERE patient_id = ? AND is_active = 1
        """, (patient_id,)).fetchall()

        alerts = db.execute("""
            SELECT * FROM alerts WHERE patient_id = ?
            ORDER BY created_at DESC LIMIT 5
        """, (patient_id,)).fetchall()

        ai_convs = db.execute("""
            SELECT * FROM ai_conversations WHERE patient_id = ?
            ORDER BY created_at DESC LIMIT 10
        """, (patient_id,)).fetchall()

        return {
            **dict(patient),
            "visits": [dict(v) for v in visits],
            "medicines": [dict(m) for m in medicines],
            "alerts": [dict(a) for a in alerts],
            "ai_conversations": [dict(c) for c in ai_convs]
        }
    finally:
        db.close()

# ── VISIT MANAGEMENT ─────────────────────────────────────────────
@router.post("/visits")
def create_visit(visit: VisitCreate, current_user: dict = Depends(require_doctor)):
    db = get_db()
    try:
        doctor_id = current_user["user_id"]
        from datetime import date
        db.execute("""
            INSERT INTO visits (patient_id, doctor_id, visit_date, chief_complaint, diagnosis, notes, follow_up_date)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (visit.patient_id, doctor_id, date.today().isoformat(),
              visit.chief_complaint, visit.diagnosis, visit.notes, visit.follow_up_date))
        db.commit()
        visit_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

        # Auto-create follow-up if date provided
        if visit.follow_up_date:
            db.execute("""
                INSERT INTO follow_ups (patient_id, doctor_id, scheduled_date, reason)
                VALUES (?, ?, ?, ?)
            """, (visit.patient_id, doctor_id, visit.follow_up_date, "Post-visit follow-up"))
            db.commit()

        return {"success": True, "visit_id": visit_id}
    finally:
        db.close()

# ── VITALS ────────────────────────────────────────────────────────
@router.post("/vitals")
def add_vitals(vitals: VitalsCreate, current_user: dict = Depends(require_doctor)):
    db = get_db()
    try:
        db.execute("""
            INSERT INTO vitals (visit_id, patient_id, bp_sys, bp_dia, heart_rate, temperature, weight, spo2)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (vitals.visit_id, vitals.patient_id, vitals.bp_sys, vitals.bp_dia,
              vitals.heart_rate, vitals.temperature, vitals.weight, vitals.spo2))
        db.commit()
        return {"success": True}
    finally:
        db.close()

# ── MEDICINE MANAGEMENT ───────────────────────────────────────────
@router.post("/medicines")
def prescribe_medicine(med: MedicineCreate, current_user: dict = Depends(require_doctor)):
    db = get_db()
    try:
        db.execute("""
            INSERT INTO medicines (patient_id, visit_id, name, dose, frequency, timing, duration, instructions)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (med.patient_id, med.visit_id, med.name, med.dose,
              med.frequency, med.timing, med.duration, med.instructions))
        db.commit()
        return {"success": True}
    finally:
        db.close()

# ── AI SCRIBE ─────────────────────────────────────────────────────
@router.post("/scribe")
def save_scribe_note(note: ScribeNoteCreate, current_user: dict = Depends(require_doctor)):
    db = get_db()
    try:
        doctor_id = current_user["user_id"]
        db.execute("""
            INSERT INTO scribe_notes (visit_id, doctor_id, patient_id, raw_transcript, ai_summary)
            VALUES (?, ?, ?, ?, ?)
        """, (note.visit_id, doctor_id, note.patient_id, note.raw_transcript, note.ai_summary))
        db.commit()
        scribe_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

        # Send alert to patient
        db.execute("""
            INSERT INTO alerts (patient_id, doctor_id, alert_type, title, message, severity)
            VALUES (?, ?, 'general', 'Visit summary ready', ?, 'low')
        """, (note.patient_id, doctor_id,
              note.ai_summary[:200] + "..." if len(note.ai_summary) > 200 else note.ai_summary))
        db.commit()

        return {"success": True, "scribe_id": scribe_id}
    finally:
        db.close()

@router.get("/scribe/today")
def get_today_scribes(current_user: dict = Depends(require_doctor)):
    db = get_db()
    try:
        doctor_id = current_user["user_id"]
        scribes = db.execute("""
            SELECT sn.*, u.name as patient_name
            FROM scribe_notes sn
            JOIN patients p ON sn.patient_id = p.id
            JOIN users u ON p.user_id = u.id
            WHERE sn.doctor_id = ? AND date(sn.created_at) = date('now')
            ORDER BY sn.created_at DESC
        """, (doctor_id,)).fetchall()
        return {"scribes": [dict(s) for s in scribes]}
    finally:
        db.close()

# ── AI TRANSCRIPTS ────────────────────────────────────────────────
@router.get("/transcripts")
def get_ai_transcripts(current_user: dict = Depends(require_doctor)):
    db = get_db()
    try:
        doctor_id = current_user["user_id"]
        convs = db.execute("""
            SELECT ac.*, u.name as patient_name, p.condition
            FROM ai_conversations ac
            JOIN patients p ON ac.patient_id = p.id
            JOIN users u ON p.user_id = u.id
            WHERE p.doctor_id = ?
            ORDER BY ac.created_at DESC LIMIT 50
        """, (doctor_id,)).fetchall()
        
        escalated = [c for c in convs if c["escalated"]]
        return {
            "conversations": [dict(c) for c in convs],
            "escalated_count": len(escalated),
            "total": len(convs)
        }
    finally:
        db.close()

# ── ESCALATIONS ───────────────────────────────────────────────────
@router.get("/escalations")
def get_escalations(current_user: dict = Depends(require_doctor)):
    db = get_db()
    try:
        doctor_id = current_user["user_id"]
        escalations = db.execute("""
            SELECT e.*, u.name as patient_name, p.condition, p.age
            FROM escalations e
            JOIN patients p ON e.patient_id = p.id
            JOIN users u ON p.user_id = u.id
            WHERE e.doctor_id = ?
            ORDER BY e.created_at DESC
        """, (doctor_id,)).fetchall()
        
        open_esc = [e for e in escalations if e["status"] == "open"]
        return {
            "escalations": [dict(e) for e in escalations],
            "open_count": len(open_esc)
        }
    finally:
        db.close()

@router.post("/escalations")
def create_escalation(data: dict, current_user: dict = Depends(require_doctor)):
    db = get_db()
    try:
        doctor_id = current_user["user_id"]
        db.execute("""
            INSERT INTO escalations (patient_id, doctor_id, reason, severity)
            VALUES (?, ?, ?, ?)
        """, (data["patient_id"], doctor_id, data.get("reason"), data.get("severity", "high")))
        db.commit()
        return {"success": True}
    finally:
        db.close()

@router.patch("/escalations/{esc_id}")
def update_escalation(esc_id: int, update: EscalationUpdate, current_user: dict = Depends(require_doctor)):
    db = get_db()
    try:
        from datetime import datetime
        resolved_at = datetime.utcnow().isoformat() if update.status == "resolved" else None
        db.execute("""
            UPDATE escalations SET status = ?, resolved_at = ?
            WHERE id = ?
        """, (update.status, resolved_at, esc_id))
        db.commit()
        return {"success": True}
    finally:
        db.close()

# ── COMPLIANCE REPORT ─────────────────────────────────────────────
@router.get("/compliance")
def get_compliance_report(current_user: dict = Depends(require_doctor)):
    db = get_db()
    try:
        doctor_id = current_user["user_id"]
        
        # Per-patient compliance last 30 days
        patient_compliance = db.execute("""
            SELECT u.name, p.id as patient_id, p.condition,
                   AVG(CASE WHEN ml.taken=1 THEN 100.0 ELSE 0.0 END) as compliance
            FROM patients p
            JOIN users u ON p.user_id = u.id
            LEFT JOIN medicines m ON m.patient_id = p.id AND m.is_active = 1
            LEFT JOIN medicine_logs ml ON ml.medicine_id = m.id
                AND ml.log_date >= date('now', '-30 days')
            WHERE p.doctor_id = ?
            GROUP BY p.id
            ORDER BY compliance ASC
        """, (doctor_id,)).fetchall()

        # Overall stats
        overall = db.execute("""
            SELECT AVG(CASE WHEN ml.taken=1 THEN 100.0 ELSE 0.0 END) as avg,
                   COUNT(DISTINCT p.id) as total_patients,
                   SUM(ml.taken) as total_taken,
                   COUNT(ml.id) as total_doses
            FROM patients p
            JOIN medicines m ON m.patient_id = p.id AND m.is_active = 1
            JOIN medicine_logs ml ON ml.medicine_id = m.id
                AND ml.log_date >= date('now', '-30 days')
            WHERE p.doctor_id = ?
        """, (doctor_id,)).fetchone()

        # AI reminders sent (all alerts)
        reminders = db.execute("""
            SELECT COUNT(*) as cnt FROM alerts a
            JOIN patients p ON a.patient_id = p.id
            WHERE p.doctor_id = ?
            AND a.created_at >= date('now', '-30 days')
        """, (doctor_id,)).fetchone()

        return {
            "patient_compliance": [dict(p) for p in patient_compliance],
            "overall": {
                "avg_compliance": round(overall["avg"] or 0),
                "total_patients": overall["total_patients"],
                "total_taken": overall["total_taken"],
                "total_doses": overall["total_doses"],
            },
            "ai_reminders_sent": reminders["cnt"],
            "low_compliance_count": sum(1 for p in patient_compliance if (p["compliance"] or 0) < 60),
            "high_compliance_count": sum(1 for p in patient_compliance if (p["compliance"] or 0) >= 90),
        }
    finally:
        db.close()

# ── PENDING FOLLOW-UPS ────────────────────────────────────────────
@router.get("/pending-followups")
def get_pending_followups(current_user: dict = Depends(require_doctor)):
    db = get_db()
    try:
        doctor_id = current_user["user_id"]
        
        # Overdue
        overdue = db.execute("""
            SELECT f.*, u.name as patient_name, p.condition, p.id as patient_id,
                   CAST(julianday('now') - julianday(f.scheduled_date) AS INTEGER) as days_overdue
            FROM follow_ups f
            JOIN patients p ON f.patient_id = p.id
            JOIN users u ON p.user_id = u.id
            WHERE f.doctor_id = ?
            AND f.scheduled_date < date('now')
            AND f.status = 'pending'
            ORDER BY f.scheduled_date ASC
        """, (doctor_id,)).fetchall()

        # Upcoming
        upcoming = db.execute("""
            SELECT f.*, u.name as patient_name, p.condition, p.id as patient_id,
                   CAST(julianday(f.scheduled_date) - julianday('now') AS INTEGER) as days_until
            FROM follow_ups f
            JOIN patients p ON f.patient_id = p.id
            JOIN users u ON p.user_id = u.id
            WHERE f.doctor_id = ?
            AND f.scheduled_date >= date('now')
            AND f.status IN ('pending','confirmed')
            ORDER BY f.scheduled_date ASC
        """, (doctor_id,)).fetchall()

        return {
            "overdue": [dict(o) for o in overdue],
            "upcoming": [dict(u) for u in upcoming],
            "overdue_count": len(overdue),
            "upcoming_count": len(upcoming)
        }
    finally:
        db.close()

@router.patch("/follow-ups/{fu_id}")
def update_follow_up(fu_id: int, data: dict, current_user: dict = Depends(require_doctor)):
    db = get_db()
    try:
        db.execute("""
            UPDATE follow_ups SET status = ?, notes = ?
            WHERE id = ?
        """, (data.get("status"), data.get("notes"), fu_id))
        db.commit()
        return {"success": True}
    finally:
        db.close()

# ── ALERTS (DOCTOR) ───────────────────────────────────────────────
@router.post("/alerts")
def create_alert(alert: AlertCreate, current_user: dict = Depends(require_doctor)):
    db = get_db()
    try:
        doctor_id = current_user["user_id"]
        db.execute("""
            INSERT INTO alerts (patient_id, doctor_id, alert_type, title, message, severity)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (alert.patient_id, doctor_id, alert.alert_type,
              alert.title, alert.message, alert.severity))
        db.commit()
        return {"success": True}
    finally:
        db.close()
