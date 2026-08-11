# AI Email Triage Agent

An agentic, Human-in-the-Loop AI application that reads customer emails from Gmail, uses OpenRouter LLM to triage them, and lets a human operator approve or reject replies before they are sent.

## Architecture
This is a **monolithic application** — FastAPI serves both the REST API and the frontend static files from a single process. Deploy it anywhere that can run a Docker container.

---

## Deployment on Render

1. Push this entire folder to a GitHub repository.
2. Go to [render.com](https://render.com) and click **New > Web Service**.
3. Connect your GitHub repo.
4. Use these settings:
   - **Environment**: Docker
   - **Port**: 8000
5. Add the following **Environment Variables** in the Render dashboard:

| Key | Value |
|-----|-------|
| `OPENROUTER_API_KEY` | Your OpenRouter API key |
| `LLM_MODEL` | `google/gemini-2.5-flash` |
| `GMAIL_ADDRESS` | Your Gmail address |
| `GMAIL_APP_PASSWORD` | Your Gmail App Password (16 chars, no spaces) |

6. Click **Deploy**. Once live, open the Render URL in your browser.

---

## How to Get a Gmail App Password

> You MUST use an App Password — your regular Gmail password will NOT work.

### Step 1 — Enable 2-Step Verification
1. Go to your Google Account: [myaccount.google.com](https://myaccount.google.com)
2. Click **Security** in the left sidebar.
3. Under "How you sign in to Google", click **2-Step Verification**.
4. Follow the prompts to enable it (takes ~1 minute).

### Step 2 — Generate an App Password
1. Go back to **Security** → search for **"App Passwords"** in the search bar at the top, or navigate directly to [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords).
2. You may be asked to sign in again.
3. Under **"App name"**, type anything e.g. `Email Triage Agent`.
4. Click **Create**.
5. Google will show you a **16-character password** (like `abcd efgh ijkl mnop`).
6. Copy it **without spaces** → `abcdefghijklmnop`.
7. Use this as your `GMAIL_APP_PASSWORD` environment variable.

> ⚠️ You will only see this password once. Save it immediately.

---

## Local Development

```bash
# 1. Copy .env.example to .env and fill in your values
cp .env.example .env

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run the server
uvicorn app:app --reload --port 8000

# 4. Open in browser
# http://localhost:8000
```

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/health` | Backend health check |
| `GET` | `/api/fetch-email` | Fetch oldest unread email from Gmail inbox |
| `POST` | `/api/analyze` | Analyze email with OpenRouter LLM |
| `POST` | `/api/approve` | Approve ticket → log to CSV + send reply via Gmail |
| `POST` | `/api/reject` | Reject ticket → log to CSV only, no email sent |

---

## Project Structure

```
AI-Email-Triage-Agent/
├── app.py                    # FastAPI monolith (API + static file serving)
├── requirements.txt
├── Dockerfile
├── .env.example
├── triage_database.csv       # Auto-created on first run
├── README.md
└── static/
    ├── index.html
    ├── style.css
    ├── script.js
    └── config.js
```
