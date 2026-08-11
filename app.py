import os
import csv
import json
import uuid
import imaplib
import smtplib
import datetime
import email as email_module
from email.header import decode_header
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from dotenv import load_dotenv

# ─────────────────────────────────────────
#  Startup Configuration
# ─────────────────────────────────────────
load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
LLM_MODEL          = os.getenv("LLM_MODEL", "google/gemini-2.5-flash")
GMAIL_ADDRESS      = os.getenv("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")

# Path to the CSV file that acts as our database
DB_PATH = Path("triage_database.csv")
DB_COLUMNS = [
    "Timestamp", "Ticket ID", "Category", "Priority", "Sentiment",
    "Customer Intent", "Assigned Team", "Estimated Response Time",
    "Confidence", "Human Decision"
]

# Create the CSV with headers if it doesn't already exist
if not DB_PATH.exists():
    with open(DB_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(DB_COLUMNS)

# ─────────────────────────────────────────
#  App & Middleware
# ─────────────────────────────────────────
app = FastAPI(title="AI Email Triage Agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─────────────────────────────────────────
#  Pydantic Models
# ─────────────────────────────────────────
class EmailRequest(BaseModel):
    email: str

class TicketPayload(BaseModel):
    ticket_id: str
    category: str
    priority: str
    sentiment: str
    customer_intent: str
    assigned_team: str
    estimated_response_time: str
    summary: str
    suggested_reply: str
    confidence: int
    sender_email: str = ""   # populated when email is fetched from inbox

# ─────────────────────────────────────────
#  Helper: Generate Ticket ID
# ─────────────────────────────────────────
def generate_ticket_id() -> str:
    date_str   = datetime.datetime.now().strftime("%Y%m%d")
    short_uuid = str(uuid.uuid4())[:8].upper()
    return f"TKT-{date_str}-{short_uuid}"

# ─────────────────────────────────────────
#  Helper: Log ticket to CSV
# ─────────────────────────────────────────
def log_to_csv(ticket: TicketPayload, decision: str) -> None:
    row = [
        datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        ticket.ticket_id,
        ticket.category,
        ticket.priority,
        ticket.sentiment,
        ticket.customer_intent,
        ticket.assigned_team,
        ticket.estimated_response_time,
        ticket.confidence,
        decision,
    ]
    with open(DB_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(row)

# ─────────────────────────────────────────
#  Helper: Send reply via Gmail SMTP
# ─────────────────────────────────────────
def send_email_reply(to_address: str, subject: str, body: str) -> None:
    if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
        raise RuntimeError("Gmail credentials are not configured in environment variables.")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Re: {subject}"
    msg["From"]    = GMAIL_ADDRESS
    msg["To"]      = to_address
    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_ADDRESS, to_address, msg.as_string())

# ─────────────────────────────────────────
#  Helper: Fetch oldest unread email via IMAP
# ─────────────────────────────────────────
def fetch_unread_email() -> dict:
    if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
        raise RuntimeError("Gmail credentials are not configured in environment variables.")

    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
    mail.select("inbox")

    # Search for UNSEEN emails
    status, messages = mail.search(None, "UNSEEN")
    if status != "OK" or not messages[0]:
        mail.logout()
        return {}

    # Pick the first (oldest) unread email
    email_ids = messages[0].split()
    email_id  = email_ids[0]

    # Fetch the raw email
    status, msg_data = mail.fetch(email_id, "(RFC822)")
    raw_email        = msg_data[0][1]
    msg              = email_module.message_from_bytes(raw_email)

    # Mark as read by removing the \Seen flag removal (marking it seen)
    mail.store(email_id, "+FLAGS", "\\Seen")
    mail.logout()

    # --- Parse sender ---
    sender_raw  = msg.get("From", "")
    sender_name, sender_addr = email_module.utils.parseaddr(sender_raw)

    # --- Parse subject ---
    raw_subject  = msg.get("Subject", "(No Subject)")
    decoded_parts = decode_header(raw_subject)
    subject_parts = []
    for part, enc in decoded_parts:
        if isinstance(part, bytes):
            subject_parts.append(part.decode(enc or "utf-8", errors="replace"))
        else:
            subject_parts.append(part)
    subject = " ".join(subject_parts)

    # --- Parse body ---
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            content_type        = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition", ""))
            if content_type == "text/plain" and "attachment" not in content_disposition:
                payload = part.get_payload(decode=True)
                if payload:
                    body = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
                    break
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            body = payload.decode(msg.get_content_charset() or "utf-8", errors="replace")

    return {
        "sender_email": sender_addr,
        "sender_name":  sender_name,
        "subject":      subject,
        "body":         body.strip(),
    }

# ─────────────────────────────────────────
#  API Endpoints
# ─────────────────────────────────────────

@app.get("/api/health")
async def health_check():
    """Health check — frontend calls this on load."""
    return {"status": "healthy"}


@app.get("/api/fetch-email")
async def fetch_email():
    """
    Connects to Gmail via IMAP, fetches the oldest UNSEEN email,
    marks it as read, and returns it to the frontend.
    """
    try:
        result = fetch_unread_email()
        if not result:
            return {"found": False, "message": "No unread emails found in inbox."}
        return {"found": True, **result}
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except imaplib.IMAP4.error as e:
        raise HTTPException(status_code=401, detail=f"Gmail IMAP login failed: {str(e)}. Check your GMAIL_ADDRESS and GMAIL_APP_PASSWORD.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch email: {str(e)}")


@app.post("/api/analyze")
async def analyze_email(request: EmailRequest):
    """
    Sends the email text to OpenRouter and returns a structured
    JSON analysis with a generated Ticket ID.
    """
    if not OPENROUTER_API_KEY:
        raise HTTPException(status_code=500, detail="OPENROUTER_API_KEY is not configured.")

    system_prompt = """You are an enterprise customer support triage agent.
Your ONLY job is to analyze customer emails and return structured JSON.

STRICT RULES:
- Return ONLY valid JSON. Nothing else.
- Never return markdown formatting (no ```json blocks).
- Never explain your reasoning.
- Never output any text outside of the JSON object.
- The JSON must match the exact structure below, with no extra fields.

Required JSON structure:
{
  "category": "One of: Billing, Technical Support, Sales, Returns, Account, Feedback, Complaint, General Inquiry, Other",
  "priority": "One of: Low, Medium, High, Critical",
  "sentiment": "One of: Positive, Neutral, Negative",
  "customer_intent": "Short description e.g. Refund Request, Password Reset, Product Inquiry",
  "assigned_team": "One of: Billing Team, Technical Support, Customer Success, Returns, Sales",
  "estimated_response_time": "One of: Immediate, 2 Hours, 4 Hours, 24 Hours, 48 Hours",
  "summary": "1-2 sentence summary of the customer issue",
  "suggested_reply": "A complete, professional, empathetic reply to the customer",
  "confidence": <integer 0 to 100>
}"""

    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": f"Analyze this customer email:\n\n{request.email}"},
        ],
    }

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type":  "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            response = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()

        raw_content = response.json()["choices"][0]["message"]["content"].strip()

        # Defensive cleanup in case the LLM wraps with markdown fences
        if raw_content.startswith("```"):
            raw_content = raw_content.split("```", 2)[-1]
            if raw_content.startswith("json"):
                raw_content = raw_content[4:]
            raw_content = raw_content.rsplit("```", 1)[0].strip()

        ai_data = json.loads(raw_content)

        # Inject the server-generated Ticket ID — LLM must never set this
        ai_data["ticket_id"] = generate_ticket_id()

        return ai_data

    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="The AI returned an invalid JSON response. Please try again.")
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=f"OpenRouter returned an error: {e.response.status_code}")
    except httpx.RequestError as e:
        raise HTTPException(status_code=503, detail=f"Cannot reach OpenRouter: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/approve")
async def approve_ticket(ticket: TicketPayload):
    """
    Human approved the ticket.
    1. Logs it to triage_database.csv with 'Approved'.
    2. Sends the suggested_reply via Gmail SMTP to the original sender.
    """
    try:
        log_to_csv(ticket, "Approved")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to log ticket to database: {str(e)}")

    if ticket.sender_email:
        try:
            send_email_reply(
                to_address=ticket.sender_email,
                subject=f"Re: Your support ticket {ticket.ticket_id}",
                body=ticket.suggested_reply,
            )
        except RuntimeError as e:
            raise HTTPException(status_code=503, detail=str(e))
        except smtplib.SMTPAuthenticationError:
            raise HTTPException(status_code=401, detail="Gmail SMTP authentication failed. Check GMAIL_ADDRESS and GMAIL_APP_PASSWORD.")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Email sent failed: {str(e)}")
        return {"status": "success", "message": f"Ticket approved. Reply sent to {ticket.sender_email}."}

    return {"status": "success", "message": "Ticket approved and logged. No sender email — reply not sent."}


@app.post("/api/reject")
async def reject_ticket(ticket: TicketPayload):
    """
    Human rejected the ticket.
    Logs it to triage_database.csv with 'Rejected'. No email is sent.
    """
    try:
        log_to_csv(ticket, "Rejected")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to log ticket to database: {str(e)}")

    return {"status": "success", "message": "Ticket rejected and logged. No email was sent."}


# ─────────────────────────────────────────
#  Static Files & SPA Fallback
# ─────────────────────────────────────────
# Serve the frontend from the /static directory.
# This MUST come after all API routes.
app.mount("/", StaticFiles(directory="static", html=True), name="static")
