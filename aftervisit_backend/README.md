# AfterVisit Backend API

## Tech Stack
- **Python** + FastAPI
- **SQLite** (no Supabase, no cloud database)
- **JWT** Authentication
- **Claude API** for AI chat

## Setup

```bash
pip install -r requirements.txt
python database.py   # Initialize DB + seed demo data
python main.py       # Start server on http://localhost:8000
```

## Demo Credentials
- **Doctor**: doctor@aftervisit.com / doctor123
- **Patient**: patient@aftervisit.com / patient123

## API Documentation
Visit http://localhost:8000/docs for full Swagger UI

## All API Routes

### Auth
- POST /api/auth/register
- POST /api/auth/login
- GET  /api/auth/me

### Patient
- GET  /api/patient/profile
- GET  /api/patient/overview      (compliance, BP, alerts count)
- GET  /api/patient/medicines
- GET  /api/patient/medicines/logs
- POST /api/patient/medicines/log  (mark medicine taken/missed)
- GET  /api/patient/visits
- GET  /api/patient/lab-reports
- GET  /api/patient/alerts
- POST /api/patient/alerts/read
- GET  /api/patient/followups
- POST /api/patient/symptoms       (AI-powered symptom checker)

### AI Chat
- POST /api/chat                   (Claude-powered chat with history)
- GET  /api/chat/history

### Doctor
- GET  /api/doctor/dashboard       (patients, escalations, followups)
- GET  /api/doctor/patients        (all patients with compliance)
- GET  /api/doctor/patients/{id}   (patient detail)
- POST /api/doctor/visits          (create new visit)
- GET  /api/doctor/escalations     (emergency alerts)
- PATCH /api/doctor/escalations/{id}/resolve
- GET  /api/doctor/compliance-report

## Environment Variables
```
ANTHROPIC_API_KEY=your_claude_api_key_here
```

## Database Tables
- users, patients, medicines, medicine_logs
- visits, lab_reports, symptom_logs
- chat_history, alerts, followups, escalations
