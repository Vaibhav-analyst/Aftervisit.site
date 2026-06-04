from http.server import BaseHTTPRequestHandler
import json, os, urllib.request

PATIENT_SYS = (
    "You are AfterVisit AI, a post-visit assistant for patients in India. "
    "Reply in the same language the patient uses (Hindi/Hinglish/English). "
    "Keep replies short (3-4 lines). Never diagnose or prescribe. "
    "For chest pain, breathing difficulty, or any emergency, tell them to call 108 immediately."
)
DOCTOR_SYS = (
    "You are AfterVisit Clinical AI assisting a doctor in India. "
    "Give concise, evidence-based guidance with Indian clinical context. "
    "This is decision-support only, not a substitute for the doctor's judgement."
)


def call_openai(system, user_text, max_tokens=600):
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        return "AI is not configured. Set OPENAI_API_KEY in your Vercel project settings."
    payload = json.dumps({
        "model": "gpt-4o-mini",
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_text},
        ],
    }).encode()
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            data = json.loads(resp.read().decode())
            return data["choices"][0]["message"]["content"]
    except Exception:
        return "Network error reaching the AI. Please try again."


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self._send(200, {"status": "ok", "endpoint": "chat"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw or b"{}")
        except Exception:
            data = {}
        message = (data.get("message") or "").strip()
        is_doctor = bool(data.get("is_doctor"))
        if not message:
            self._send(400, {"error": "message is required"})
            return
        system = DOCTOR_SYS if is_doctor else PATIENT_SYS
        reply = call_openai(system, message, 600)
        self._send(200, {"reply": reply})

    def _send(self, code, obj):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(obj).encode())
