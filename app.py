import os
import json
import uuid
import imaplib
import smtplib
import datetime
import email as email_module
from email.header import decode_header
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import httpx
import psycopg2
import psycopg2.extras
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv

# ─────────────────────────────────────────
#  Startup Configuration
# ─────────────────────────────────────────
load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
LLM_MODEL          = os.getenv("LLM_MODEL", "meta-llama/llama-3.3-70b-instruct")
GMAIL_ADDRESS      = os.getenv("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")
DATABASE_URL       = os.getenv("DATABASE_URL", "")  # Neon Postgres connection string

# ─────────────────────────────────────────
#  Database: Init table on startup
# ─────────────────────────────────────────
def get_db_connection():
    """Returns a new psycopg2 connection to Neon Postgres."""
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not configured.")
    return psycopg2.connect(DATABASE_URL, sslmode="require")

def init_db():
    """Creates the tickets table if it doesn't already exist."""
    if not DATABASE_URL:
        print("WARNING: DATABASE_URL not set — database logging will be unavailable.")
        return
    try:
        conn = get_db_connection()
        cur  = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tickets (
                id                      SERIAL PRIMARY KEY,
                timestamp               TIMESTAMPTZ DEFAULT NOW(),
                ticket_id               VARCHAR(60)  NOT NULL,
                category                VARCHAR(100),
                priority                VARCHAR(50),
                sentiment               VARCHAR(50),
                customer_intent         VARCHAR(255),
                assigned_team           VARCHAR(100),
                estimated_response_time VARCHAR(50),
                confidence              INTEGER,
                human_decision          VARCHAR(50)
            );
        """)
        conn.commit()
        cur.close()
        conn.close()
        print("Database ready.")
    except Exception as e:
        print(f"Database init warning: {e}")

# Run once at startup
init_db()

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
    sender_email: str = ""

# ─────────────────────────────────────────
#  Helper: Generate Ticket ID
# ─────────────────────────────────────────
def generate_ticket_id() -> str:
    date_str   = datetime.datetime.now().strftime("%Y%m%d")
    short_uuid = str(uuid.uuid4())[:8].upper()
    return f"TKT-{date_str}-{short_uuid}"

# ─────────────────────────────────────────
#  Helper: Log ticket to Neon Postgres
# ─────────────────────────────────────────
def log_to_db(ticket: TicketPayload, decision: str) -> None:
    """Inserts a ticket record into the Neon Postgres database."""
    conn = get_db_connection()
    cur  = conn.cursor()
    cur.execute("""
        INSERT INTO tickets
            (ticket_id, category, priority, sentiment, customer_intent,
             assigned_team, estimated_response_time, confidence, human_decision)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, (
        ticket.ticket_id,
        ticket.category,
        ticket.priority,
        ticket.sentiment,
        ticket.customer_intent,
        ticket.assigned_team,
        ticket.estimated_response_time,
        ticket.confidence,
        decision,
    ))
    conn.commit()
    cur.close()
    conn.close()

# ─────────────────────────────────────────
#  Helper: Send reply via Gmail SMTP
# ─────────────────────────────────────────
def send_email_reply(to_address: str, subject: str, body: str) -> None:
    if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
        raise RuntimeError("Gmail credentials are not configured.")

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
        raise RuntimeError("Gmail credentials are not configured.")

    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
    mail.select("inbox")

    status, messages = mail.search(None, "UNSEEN")
    if status != "OK" or not messages[0]:
        mail.logout()
        return {}

    email_id = messages[0].split()[0]

    status, msg_data = mail.fetch(email_id, "(RFC822)")
    raw_email        = msg_data[0][1]
    msg              = email_module.message_from_bytes(raw_email)

    # Mark as read
    mail.store(email_id, "+FLAGS", "\\Seen")
    mail.logout()

    # Parse sender
    _, sender_addr = email_module.utils.parseaddr(msg.get("From", ""))

    # Parse subject
    decoded_parts = decode_header(msg.get("Subject", "(No Subject)"))
    subject = " ".join(
        part.decode(enc or "utf-8", errors="replace") if isinstance(part, bytes) else part
        for part, enc in decoded_parts
    )

    # Parse body
    body = ""
    html_body = ""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            disposition = str(part.get("Content-Disposition", ""))
            if "attachment" in disposition:
                continue
            
            payload = part.get_payload(decode=True)
            if not payload:
                continue
                
            charset = part.get_content_charset() or "utf-8"
            decoded = payload.decode(charset, errors="replace")
            
            if content_type == "text/plain":
                body = decoded
                break
            elif content_type == "text/html":
                html_body = decoded
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            decoded = payload.decode(charset, errors="replace")
            if msg.get_content_type() == "text/html":
                html_body = decoded
            else:
                body = decoded

    # Fallback to HTML if no plain text
    if not body and html_body:
        import re
        # Basic HTML stripping
        body = re.sub('<[^<]+>', '', html_body).replace('&nbsp;', ' ').strip()

    return {"sender_email": sender_addr, "subject": subject, "body": body.strip()}


# ─────────────────────────────────────────
#  API Endpoints
# ─────────────────────────────────────────

@app.get("/api/health")
async def health_check():
    return {"status": "healthy"}


@app.get("/api/fetch-email")
async def fetch_email():
    """Fetches the oldest unread email from Gmail and marks it as read."""
    try:
        result = fetch_unread_email()
        if not result:
            return {"found": False, "message": "No unread emails found in inbox."}
        return {"found": True, **result}
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except imaplib.IMAP4.error as e:
        raise HTTPException(status_code=401, detail=f"Gmail IMAP login failed: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch email: {str(e)}")


@app.post("/api/analyze")
async def analyze_email(request: EmailRequest):
    """Analyzes the email with OpenRouter LLM and returns structured JSON."""
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

        # Extract JSON if wrapped in markdown fences
        import re
        match = re.search(r'```(?:json)?(.*?)```', raw_content, re.DOTALL)
        if match:
            raw_content = match.group(1).strip()

        ai_data = json.loads(raw_content)

        # Server generates Ticket ID — never the LLM
        ai_data["ticket_id"] = generate_ticket_id()
        return ai_data

    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="The AI returned invalid JSON. Please try again.")
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=f"OpenRouter error: {e.response.status_code}")
    except httpx.RequestError as e:
        raise HTTPException(status_code=503, detail=f"Cannot reach OpenRouter: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/approve")
async def approve_ticket(ticket: TicketPayload):
    """
    Human approved.
    1. Logs ticket to Neon Postgres with 'Approved'.
    2. Sends the suggested reply via Gmail SMTP to the original sender.
    """
    try:
        log_to_db(ticket, "Approved")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

    if ticket.sender_email:
        try:
            send_email_reply(
                to_address=ticket.sender_email,
                subject=f"Your support ticket {ticket.ticket_id}",
                body=ticket.suggested_reply,
            )
        except RuntimeError as e:
            raise HTTPException(status_code=503, detail=str(e))
        except smtplib.SMTPAuthenticationError:
            raise HTTPException(status_code=401, detail="Gmail SMTP authentication failed.")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Email send failed: {str(e)}")
        return {"status": "success", "message": f"Approved. Reply sent to {ticket.sender_email} and logged to database."}

    return {"status": "success", "message": "Approved and logged to database. No sender email — reply not sent."}


@app.post("/api/reject")
async def reject_ticket(ticket: TicketPayload):
    """
    Human rejected.
    Logs ticket to Neon Postgres with 'Rejected'. No email sent.
    """
    try:
        log_to_db(ticket, "Rejected")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

    return {"status": "success", "message": "Rejected and logged to database. No email was sent."}


# ─────────────────────────────────────────
#  Static Files — mount LAST after all API routes
# ─────────────────────────────────────────
app.mount("/", StaticFiles(directory="static", html=True), name="static")
