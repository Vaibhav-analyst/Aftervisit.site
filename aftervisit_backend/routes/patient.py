from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, List
from datetime import date
import sys, os
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from database import get_db
from routes.auth import get_current_user, require_patient, require_doctor

router = APIRouter(prefix="/patient", tags=["patient"])

# ── SCHEMAS ──────────────────────────────────────────────────────
class MedicineLogUpdate(BaseModel):
    medicine_id: int
    taken: bool
    taken_time: Optional[str] = None

class SymptomReport(BaseModel):
    symptom: str
    severity: str
    notes: Optional[str] = None

# ── HELPERS ───────────────────────────────────────────────────────
def get_patient_id(user_id: int, db) -> int:
    row = db.execute("SELECT id FROM patients WHERE user_id = ?", (user_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Patient profile not found")
    return row["id"]

# ── OVERVIEW ─────────────────────────────────────────────────────
@router.get("/overview")
def get_overview(current_user: dict = Depends(get_current_user)):
    db = get_db()
    try:
        user_id = current_user["user_id"]
        patient_id = get_patient_id(user_id, db)

        # User info
        user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        patient = db.execute("SELECT * FROM patients WHERE id = ?", (patient_id,)).fetchone()

        # Medicine compliance (last 30 days)
        logs = db.execute("""
            SELECT COUNT(*) as total,
                   SUM(taken) as taken_count
            FROM medicine_logs
            WHERE patient_id = ?
            AND log_date >= date('now', '-30 days')
        """, (patient_id,)).fetchone()
        
        total = logs["total"] or 1
        taken = logs["taken_count"] or 0
        compliance = round((taken / total) * 100) if total > 0 else 0

        # Latest vitals
        vitals = db.execute("""
            SELECT v.* FROM vitals v
            JOIN visits vis ON v.visit_id = vis.id
            WHERE v.patient_id = ?
            ORDER BY v.recorded_at DESC LIMIT 1
        """, (patient_id,)).fetchone()

        # Next follow-up
        next_fu = db.execute("""
            SELECT * FROM follow_ups
            WHERE patient_id = ? AND status IN ('pending','confirmed')
            AND scheduled_date >= date('now')
            ORDER BY scheduled_date ASC LIMIT 1
        """, (patient_id,)).fetchone()

        # Unread alerts count
        unread = db.execute("""
            SELECT COUNT(*) as cnt FROM alerts
            WHERE patient_id = ? AND is_read = 0
        """, (patient_id,)).fetchone()

        # Total visits this year
        visits_count = db.execute("""
            SELECT COUNT(*) as cnt FROM visits
            WHERE patient_id = ?
            AND visit_date >= date('now', 'start of year')
        """, (patient_id,)).fetchone()

        # Today's medicines
        today_meds = db.execute("""
            SELECT m.*, ml.taken, ml.taken_time
            FROM medicines m
            LEFT JOIN medicine_logs ml ON ml.medicine_id = m.id
                AND ml.log_date = date('now')
            WHERE m.patient_id = ? AND m.is_active = 1
        """, (patient_id,)).fetchall()

        # Recent activity (last 5)
        recent_alerts = db.execute("""
            SELECT * FROM alerts WHERE patient_id = ?
            ORDER BY created_at DESC LIMIT 5
        """, (patient_id,)).fetchall()

        return {
            "user": {"name": user["name"], "email": user["email"]},
            "patient": {"condition": patient["condition"], "blood_group": patient["blood_group"]},
            "stats": {
                "compliance": compliance,
                "bp": f"{vitals['bp_sys']}/{vitals['bp_dia']}" if vitals else "N/A",
                "next_follow_up": next_fu["scheduled_date"] if next_fu else None,
                "visits_this_year": visits_count["cnt"],
                "unread_alerts": unread["cnt"]
            },
            "today_medicines": [dict(m) for m in today_meds],
            "recent_activity": [dict(a) for a in recent_alerts],
            "compliance_detail": {
                "total_doses": total,
                "taken": taken,
                "missed": total - taken,
                "percentage": compliance
            }
        }
    finally:
        db.close()

# ── VISITS ────────────────────────────────────────────────────────
@router.get("/visits")
def get_visits(current_user: dict = Depends(get_current_user)):
    db = get_db()
    try:
        patient_id = get_patient_id(current_user["user_id"], db)
        visits = db.execute("""
            SELECT v.*, u.name as doctor_name
            FROM visits v
            JOIN users u ON v.doctor_id = u.id
            WHERE v.patient_id = ?
            ORDER BY v.visit_date DESC
        """, (patient_id,)).fetchall()

        result = []
        for v in visits:
            visit_dict = dict(v)
            # Get vitals
            vitals = db.execute("""
                SELECT * FROM vitals WHERE visit_id = ?
            """, (v["id"],)).fetchone()
            # Get medicines prescribed
            meds = db.execute("""
                SELECT * FROM medicines WHERE visit_id = ?
            """, (v["id"],)).fetchall()
            # Get prescriptions
            pres = db.execute("""
                SELECT * FROM prescriptions WHERE visit_id = ?
            """, (v["id"],)).fetchone()
            
            visit_dict["vitals"] = dict(vitals) if vitals else {}
            visit_dict["medicines"] = [dict(m) for m in meds]
            visit_dict["prescription"] = dict(pres) if pres else {}
            result.append(visit_dict)

        return {"visits": result, "total": len(result)}
    finally:
        db.close()

@router.get("/visits/{visit_id}")
def get_visit_detail(visit_id: int, current_user: dict = Depends(get_current_user)):
    db = get_db()
    try:
        patient_id = get_patient_id(current_user["user_id"], db)
        visit = db.execute("""
            SELECT v.*, u.name as doctor_name
            FROM visits v JOIN users u ON v.doctor_id = u.id
            WHERE v.id = ? AND v.patient_id = ?
        """, (visit_id, patient_id)).fetchone()
        
        if not visit:
            raise HTTPException(status_code=404, detail="Visit not found")

        vitals = db.execute("SELECT * FROM vitals WHERE visit_id = ?", (visit_id,)).fetchone()
        meds = db.execute("SELECT * FROM medicines WHERE visit_id = ?", (visit_id,)).fetchall()
        pres = db.execute("SELECT * FROM prescriptions WHERE visit_id = ?", (visit_id,)).fetchone()
        scribe = db.execute("SELECT * FROM scribe_notes WHERE visit_id = ?", (visit_id,)).fetchone()

        return {
            **dict(visit),
            "vitals": dict(vitals) if vitals else {},
            "medicines": [dict(m) for m in meds],
            "prescription": dict(pres) if pres else {},
            "ai_scribe_summary": scribe["ai_summary"] if scribe else None
        }
    finally:
        db.close()

# ── MEDICINES ─────────────────────────────────────────────────────
@router.get("/medicines")
def get_medicines(current_user: dict = Depends(get_current_user)):
    db = get_db()
    try:
        patient_id = get_patient_id(current_user["user_id"], db)
        
        medicines = db.execute("""
            SELECT * FROM medicines WHERE patient_id = ? AND is_active = 1
            ORDER BY prescribed_at DESC
        """, (patient_id,)).fetchall()

        # Get adherence per medicine (last 7 days)
        result = []
        for med in medicines:
            logs = db.execute("""
                SELECT COUNT(*) as total, SUM(taken) as taken
                FROM medicine_logs
                WHERE medicine_id = ? AND log_date >= date('now', '-7 days')
            """, (med["id"],)).fetchone()
            
            total = logs["total"] or 1
            taken = logs["taken"] or 0
            adherence = round((taken/total)*100)

            med_dict = dict(med)
            med_dict["adherence_7day"] = adherence
            result.append(med_dict)

        # Heatmap data — last 21 days
        heatmap = db.execute("""
            SELECT log_date, SUM(taken) as taken, COUNT(*) as total
            FROM medicine_logs
            WHERE patient_id = ? AND log_date >= date('now', '-21 days')
            GROUP BY log_date ORDER BY log_date
        """, (patient_id,)).fetchall()

        return {
            "medicines": result,
            "heatmap": [dict(h) for h in heatmap],
            "overall_compliance": round(sum(m["adherence_7day"] for m in result) / len(result)) if result else 0
        }
    finally:
        db.close()

@router.post("/medicines/log")
def log_medicine(log: MedicineLogUpdate, current_user: dict = Depends(get_current_user)):
    db = get_db()
    try:
        patient_id = get_patient_id(current_user["user_id"], db)
        
        # Verify medicine belongs to patient
        med = db.execute("""
            SELECT * FROM medicines WHERE id = ? AND patient_id = ?
        """, (log.medicine_id, patient_id)).fetchone()
        if not med:
            raise HTTPException(status_code=404, detail="Medicine not found")

        # Upsert log for today
        existing = db.execute("""
            SELECT id FROM medicine_logs
            WHERE medicine_id = ? AND patient_id = ? AND log_date = date('now')
        """, (log.medicine_id, patient_id)).fetchone()

        if existing:
            db.execute("""
                UPDATE medicine_logs SET taken = ?, taken_time = ?
                WHERE id = ?
            """, (1 if log.taken else 0, log.taken_time, existing["id"]))
        else:
            db.execute("""
                INSERT INTO medicine_logs (medicine_id, patient_id, taken, taken_time)
                VALUES (?, ?, ?, ?)
            """, (log.medicine_id, patient_id, 1 if log.taken else 0, log.taken_time))

        db.commit()
        return {"success": True, "taken": log.taken, "medicine_id": log.medicine_id}
    finally:
        db.close()

# ── LAB REPORTS ───────────────────────────────────────────────────
@router.get("/lab-reports")
def get_lab_reports(current_user: dict = Depends(get_current_user)):
    db = get_db()
    try:
        patient_id = get_patient_id(current_user["user_id"], db)
        
        reports = db.execute("""
            SELECT * FROM lab_reports WHERE patient_id = ?
            ORDER BY report_date DESC
        """, (patient_id,)).fetchall()

        result = []
        for r in reports:
            values = db.execute("""
                SELECT * FROM lab_values WHERE report_id = ?
            """, (r["id"],)).fetchall()
            flags = sum(1 for v in values if v["flag"])
            
            r_dict = dict(r)
            r_dict["values"] = [dict(v) for v in values]
            r_dict["flag_count"] = flags
            result.append(r_dict)

        return {"reports": result, "total": len(result)}
    finally:
        db.close()

# ── ALERTS ────────────────────────────────────────────────────────
@router.get("/alerts")
def get_alerts(current_user: dict = Depends(get_current_user)):
    db = get_db()
    try:
        patient_id = get_patient_id(current_user["user_id"], db)
        alerts = db.execute("""
            SELECT * FROM alerts WHERE patient_id = ?
            ORDER BY created_at DESC
        """, (patient_id,)).fetchall()
        
        unread = sum(1 for a in alerts if not a["is_read"])
        return {
            "alerts": [dict(a) for a in alerts],
            "unread_count": unread,
            "total": len(alerts)
        }
    finally:
        db.close()

@router.patch("/alerts/{alert_id}/read")
def mark_alert_read(alert_id: int, current_user: dict = Depends(get_current_user)):
    db = get_db()
    try:
        patient_id = get_patient_id(current_user["user_id"], db)
        db.execute("""
            UPDATE alerts SET is_read = 1
            WHERE id = ? AND patient_id = ?
        """, (alert_id, patient_id))
        db.commit()
        return {"success": True}
    finally:
        db.close()

# ── FOLLOW UPS ────────────────────────────────────────────────────
@router.get("/follow-ups")
def get_follow_ups(current_user: dict = Depends(get_current_user)):
    db = get_db()
    try:
        patient_id = get_patient_id(current_user["user_id"], db)
        follow_ups = db.execute("""
            SELECT f.*, u.name as doctor_name
            FROM follow_ups f
            JOIN users u ON f.doctor_id = u.id
            WHERE f.patient_id = ?
            ORDER BY f.scheduled_date ASC
        """, (patient_id,)).fetchall()
        
        upcoming = [f for f in follow_ups if f["status"] in ("pending","confirmed")]
        return {
            "follow_ups": [dict(f) for f in follow_ups],
            "upcoming_count": len(upcoming)
        }
    finally:
        db.close()

# ── AI CONVERSATIONS ──────────────────────────────────────────────
@router.get("/ai-history")
def get_ai_history(current_user: dict = Depends(get_current_user)):
    db = get_db()
    try:
        patient_id = get_patient_id(current_user["user_id"], db)
        convs = db.execute("""
            SELECT * FROM ai_conversations
            WHERE patient_id = ?
            ORDER BY created_at DESC LIMIT 20
        """, (patient_id,)).fetchall()
        return {"conversations": [dict(c) for c in convs]}
    finally:
        db.close()

@router.post("/ai-history")
def save_ai_conversation(
    data: dict,
    current_user: dict = Depends(get_current_user)
):
    db = get_db()
    try:
        patient_id = get_patient_id(current_user["user_id"], db)
        db.execute("""
            INSERT INTO ai_conversations (patient_id, user_message, ai_response, escalated)
            VALUES (?, ?, ?, ?)
        """, (patient_id, data.get("user_message"), data.get("ai_response"), data.get("escalated", 0)))
        db.commit()
        return {"success": True}
    finally:
        db.close()

# ── VITALS ────────────────────────────────────────────────────────
@router.get("/vitals/history")
def get_vitals_history(current_user: dict = Depends(get_current_user)):
    db = get_db()
    try:
        patient_id = get_patient_id(current_user["user_id"], db)
        vitals = db.execute("""
            SELECT v.*, vis.visit_date
            FROM vitals v
            JOIN visits vis ON v.visit_id = vis.id
            WHERE v.patient_id = ?
            ORDER BY vis.visit_date DESC
        """, (patient_id,)).fetchall()
        return {"vitals": [dict(v) for v in vitals]}
    finally:
        db.close()
