from http.server import BaseHTTPRequestHandler
import json, os, urllib.request

SCRIBE_SYS = (
    "You are a clinical documentation assistant. From the raw transcript of a "
    "doctor-patient consultation, produce a concise, structured visit summary with "
    "these sections: Chief Complaint, History, Examination / Findings, Diagnosis, "
    "Medications / Plan, Follow-up. Use ONLY information present in the transcript. "
    "If a section was not discussed, write 'Not discussed'. Do not invent clinical facts."
)


def call_openai(system, user_text, max_tokens=800):
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
        self._send(200, {"status": "ok", "endpoint": "scribe"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw or b"{}")
        except Exception:
            data = {}
        transcript = (data.get("raw_transcript") or "").strip()
        if not transcript:
            self._send(400, {"error": "raw_transcript is required"})
            return
        summary = call_openai(SCRIBE_SYS, "Consultation transcript:\n\n" + transcript, 800)
        self._send(200, {"ai_summary": summary})

    def _send(self, code, obj):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(obj).encode())
