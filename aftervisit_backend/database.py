import sqlite3
from datetime import date, timedelta

DB_PATH = "aftervisit.db"

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()

    c.execute("""CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        phone TEXT,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'patient',
        city TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS patients (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER UNIQUE,
        patient_code TEXT UNIQUE,
        age INTEGER,
        gender TEXT,
        condition TEXT,
        doctor_id INTEGER,
        blood_group TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id),
        FOREIGN KEY (doctor_id) REFERENCES users(id)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS medicines (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        patient_id INTEGER,
        name TEXT NOT NULL,
        dose TEXT,
        frequency TEXT,
        timing TEXT,
        start_date TEXT,
        color TEXT DEFAULT '#00BFA8',
        prescribed_by INTEGER,
        active INTEGER DEFAULT 1,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (patient_id) REFERENCES patients(id)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS medicine_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        patient_id INTEGER,
        medicine_id INTEGER,
        date TEXT,
        taken INTEGER DEFAULT 0,
        taken_at TEXT,
        UNIQUE(patient_id, medicine_id, date),
        FOREIGN KEY (patient_id) REFERENCES patients(id),
        FOREIGN KEY (medicine_id) REFERENCES medicines(id)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS visits (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        patient_id INTEGER,
        doctor_id INTEGER,
        visit_date TEXT,
        chief_complaint TEXT,
        diagnosis TEXT,
        instructions TEXT,
        bp TEXT,
        heart_rate TEXT,
        weight TEXT,
        temperature TEXT,
        spo2 TEXT,
        next_visit TEXT,
        notes TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (patient_id) REFERENCES patients(id),
        FOREIGN KEY (doctor_id) REFERENCES users(id)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS lab_reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        patient_id INTEGER,
        report_name TEXT,
        report_date TEXT,
        lab_name TEXT,
        results TEXT,
        flags TEXT,
        ai_explanation TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (patient_id) REFERENCES patients(id)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS symptom_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        patient_id INTEGER,
        symptom TEXT,
        severity TEXT,
        ai_response TEXT,
        escalated INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (patient_id) REFERENCES patients(id)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS chat_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        role TEXT,
        message TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        patient_id INTEGER,
        alert_type TEXT,
        title TEXT,
        message TEXT,
        severity TEXT DEFAULT 'info',
        read_status INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (patient_id) REFERENCES patients(id)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS followups (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        patient_id INTEGER,
        doctor_id INTEGER,
        scheduled_date TEXT,
        purpose TEXT,
        status TEXT DEFAULT 'pending',
        notes TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (patient_id) REFERENCES patients(id),
        FOREIGN KEY (doctor_id) REFERENCES users(id)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS escalations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        patient_id INTEGER,
        doctor_id INTEGER,
        type TEXT,
        description TEXT,
        ai_action TEXT,
        status TEXT DEFAULT 'active',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (patient_id) REFERENCES patients(id),
        FOREIGN KEY (doctor_id) REFERENCES users(id)
    )""")

    conn.commit()
    conn.close()
    print("Database initialized!")

def seed_demo_data():
    from passlib.context import CryptContext
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    conn = get_db()
    c = conn.cursor()

    c.execute("SELECT COUNT(*) as cnt FROM users")
    if c.fetchone()["cnt"] > 0:
        conn.close()
        return

    # Doctor
    c.execute("INSERT INTO users (name, email, phone, password_hash, role, city) VALUES (?,?,?,?,?,?)",
              ("Dr. Rajan Deshmukh","doctor@aftervisit.com","9876543210",
               pwd_context.hash("doctor123"),"doctor","Nagpur"))
    doc_id = c.lastrowid

    # Patient user
    c.execute("INSERT INTO users (name, email, phone, password_hash, role, city) VALUES (?,?,?,?,?,?)",
              ("Rahul Sharma","patient@aftervisit.com","9876543211",
               pwd_context.hash("patient123"),"patient","Nagpur"))
    pat_user_id = c.lastrowid

    # Patient profile
    c.execute("INSERT INTO patients (user_id, patient_code, age, gender, condition, doctor_id, blood_group) VALUES (?,?,?,?,?,?,?)",
              (pat_user_id,"AV-2024-0847",42,"Male","Stage 1 Hypertension",doc_id,"B+"))
    pat_id = c.lastrowid

    # Medicines
    med_data = [
        (pat_id,"Amlodipine 5mg","5mg","Once daily","Morning after food","2026-03-22","#00BFA8",doc_id),
        (pat_id,"Telmisartan 40mg","40mg","Once daily","Night before food","2026-03-22","#4A90E8",doc_id),
        (pat_id,"Aspirin 75mg","75mg","Once daily","Morning after food","2026-03-22","#F5A623",doc_id),
    ]
    for m in med_data:
        c.execute("INSERT INTO medicines (patient_id,name,dose,frequency,timing,start_date,color,prescribed_by) VALUES (?,?,?,?,?,?,?,?)", m)

    c.execute("SELECT id FROM medicines WHERE patient_id=?", (pat_id,))
    med_ids = [r["id"] for r in c.fetchall()]

    # Medicine logs last 21 days
    today = date.today()
    skip = [2, 8, 15]
    for offset in range(21):
        d = (today - timedelta(days=20-offset)).isoformat()
        taken = 0 if offset in skip else 1
        for mid in med_ids:
            c.execute("INSERT OR IGNORE INTO medicine_logs (patient_id,medicine_id,date,taken) VALUES (?,?,?,?)",
                      (pat_id, mid, d, taken))

    # Visits
    c.execute("""INSERT INTO visits (patient_id,doctor_id,visit_date,chief_complaint,diagnosis,
               instructions,bp,heart_rate,weight,spo2,next_visit,notes) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
              (pat_id,doc_id,"2026-05-20","Routine BP checkup",
               "Stage 1 Hypertension — improving. BP reduced from 148/92.",
               "Continue all medicines. Monitor BP every Sunday. Reduce sodium. Daily walk 30-45 min. Fasting sugar 112 — reduce sweets and white rice.",
               "134/86","78","74","98","2026-06-03","Patient responding well to medication."))

    c.execute("""INSERT INTO visits (patient_id,doctor_id,visit_date,chief_complaint,diagnosis,
               instructions,bp,heart_rate,weight,spo2,next_visit,notes) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
              (pat_id,doc_id,"2026-03-22","High BP complaint",
               "Stage 1 Hypertension — newly diagnosed.",
               "Starting Amlodipine 5mg and Aspirin 75mg. Strict low-sodium diet. No smoking. Min 30 min daily walk.",
               "148/92","84","76","97","2026-05-20","First visit. Started medication."))

    # Lab report
    import json
    results = json.dumps([
        {"name":"Haemoglobin","value":"14.2","unit":"g/dL","range":"13.0-17.0","status":"normal"},
        {"name":"WBC Count","value":"7400","unit":"/uL","range":"4000-11000","status":"normal"},
        {"name":"Fasting Blood Sugar","value":"112","unit":"mg/dL","range":"70-100","status":"high"},
        {"name":"Total Cholesterol","value":"194","unit":"mg/dL","range":"<200","status":"borderline"},
        {"name":"HDL","value":"52","unit":"mg/dL","range":">40","status":"normal"},
        {"name":"Creatinine","value":"0.9","unit":"mg/dL","range":"0.7-1.2","status":"normal"},
    ])
    c.execute("""INSERT INTO lab_reports (patient_id,report_name,report_date,lab_name,results,flags,ai_explanation)
               VALUES (?,?,?,?,?,?,?)""",
              (pat_id,"CBC + Lipid Profile","2026-05-18","City Diagnostic Lab, Nagpur",
               results,"Fasting sugar 112 mg/dL",
               "Fasting sugar 112 mg/dL pre-diabetic range mein hai. Diabetes abhi nahi hai, lekin risk hai. Meetha aur white rice abhi se kam karo. June 3 visit mein Dr. Deshmukh ko zaroor batao."))

    # Alerts
    for typ,title,msg,sev in [
        ("lab_flag","Fasting sugar elevated — pre-diabetic range",
         "CBC shows fasting sugar 112 mg/dL. Reduce sweets and white rice. Discuss June 3.","danger"),
        ("medicine_low","Telmisartan running low — 5 days left",
         "Please refill before June 1. Missing this medicine can cause dangerous BP spikes.","warning"),
        ("followup","Follow-up reminder — June 3 confirmed",
         "Cardiology follow-up with Dr. Deshmukh confirmed for June 3 at 10:30 AM.","success"),
    ]:
        c.execute("INSERT INTO alerts (patient_id,alert_type,title,message,severity) VALUES (?,?,?,?,?)",
                  (pat_id,typ,title,msg,sev))

    # Follow-up
    c.execute("INSERT INTO followups (patient_id,doctor_id,scheduled_date,purpose,status) VALUES (?,?,?,?,?)",
              (pat_id,doc_id,"2026-06-03","BP review + fasting sugar discussion","pending"))

    conn.commit()
    conn.close()
    print("Demo data seeded!")
    print("\nDemo Credentials:")
    print("  Doctor  -> doctor@aftervisit.com / doctor123")
    print("  Patient -> patient@aftervisit.com / patient123")

if __name__ == "__main__":
    init_db()
    seed_demo_data()
