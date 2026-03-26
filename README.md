# 📧 Email-to-Sheets Agent

An **Agentic AI** application that automatically monitors Gmail, intelligently parses emails using Groq LLM, and stores structured task data in Google Sheets.

## 🎯 What Makes This "Agentic AI"?

Unlike simple automation that relies on rigid rules:

| Feature | Simple Automation | This Agent |
|---------|------------------|------------|
| Email Parsing | Regex patterns | LLM understands context |
| Data Extraction | Fixed templates | Handles any email format |
| Team Detection | Manual mapping | AI infers from content |
| Adaptability | Breaks on changes | Adapts intelligently |

The **EmailParserAgent** uses Groq's LLM to understand email context and extract structured data, making it robust to format variations.

## 🏗️ Project Structure

```
email-to-sheets-agent/
├── config.py                 # Configuration management
├── main.py                   # Application entry point
├── scheduler.py              # Background job scheduler
├── requirements.txt          # Python dependencies
│
├── src/
│   ├── agents/
│   │   ├── __init__.py
│   │   └── email_parser_agent.py    # 🤖 AI Agent (Groq LLM)
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   ├── gmail_service.py         # Gmail API integration
│   │   └── sheets_service.py        # Google Sheets API
│   │
│   └── utils/
│       ├── __init__.py
│       └── logger.py                # Logging utilities
│
├── render.yaml               # Render deployment blueprint
├── Procfile                  # Process definitions
├── runtime.txt               # Python version
└── .env.example              # Environment template
```

## 📊 Output Format

Emails are parsed and stored with these fields:

| SN | Task Name | Description | Status | Date of Query | Date of Solution | Request Came From | Team Origin |
|----|-----------|-------------|--------|---------------|------------------|-------------------|-------------|
| 1  | API Bug Fix | Users reporting 500 errors... | Pending | 2026-03-26 | | John <john@company.com> | Engineering |

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- Google Cloud Project with Gmail & Sheets APIs enabled
- Groq API key

### 1. Clone & Install

```bash
git clone <your-repo>
cd email-to-sheets-agent
python -m venv venv
venv\Scripts\activate  # Windows
pip install -r requirements.txt
```

### 2. Google Cloud Setup

#### Gmail API (OAuth2)
1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a new project or select existing
3. Enable **Gmail API**
4. Create OAuth 2.0 credentials (Desktop app)
5. Download as `credentials.json`

#### Google Sheets API (Service Account)
1. Enable **Google Sheets API**
2. Create Service Account
3. Download JSON key as `service_account.json`
4. Share your Google Sheet with the service account email

### 3. Configure Environment

```bash
cp .env.example .env
# Edit .env with your credentials
```

### 4. Create Google Sheet

Create a new Google Sheet and copy the ID from the URL:
```
https://docs.google.com/spreadsheets/d/[SHEET_ID_HERE]/edit
```

### 5. Run Locally

```bash
# Process emails once
python main.py

# Watch mode (continuous monitoring)
python main.py --watch

# Start web server
python main.py --server
```

## ☁️ Deploy to Render

### Option 1: Blueprint (Recommended)

1. Push code to GitHub
2. Go to [Render Dashboard](https://dashboard.render.com)
3. New → Blueprint
4. Connect your repo
5. Render will use `render.yaml` automatically

### Option 2: Manual Setup

**Background Worker:**
```
Build: pip install -r requirements.txt
Start: python scheduler.py
```

**Environment Variables (Set in Render Dashboard):**
- `GROQ_API_KEY` - Your Groq API key
- `GOOGLE_SHEET_ID` - Your Google Sheet ID  
- `GOOGLE_CREDENTIALS_JSON` - Paste entire service account JSON

### Gmail OAuth on Render

Since Gmail OAuth requires browser interaction for first auth:

1. Run locally first: `python main.py`
2. Complete OAuth flow in browser
3. Copy generated `token.json` content
4. Store as environment variable or use service account approach

## 🔧 Configuration Options

| Variable | Description | Default |
|----------|-------------|---------|
| `GROQ_API_KEY` | Groq API key | Required |
| `GROQ_MODEL` | LLM model to use | `llama-3.1-70b-versatile` |
| `GOOGLE_SHEET_ID` | Target spreadsheet ID | Required |
| `GOOGLE_SHEET_NAME` | Worksheet name | `Sheet1` |
| `GMAIL_LABEL_FILTER` | Gmail label to monitor | `INBOX` |
| `GMAIL_CHECK_INTERVAL_MINUTES` | Check frequency | `5` |
| `FILTER_FROM_EMAIL` | Only process from this sender | All |

## 🧪 Testing

```bash
# Test email parsing
python -c "
from src.agents import EmailParserAgent
agent = EmailParserAgent()
result = agent.parse_email({
    'subject': 'Need help with dashboard',
    'from': 'alice@marketing.com',
    'date': '2026-03-26',
    'body': 'Hi, the sales dashboard is showing wrong numbers. Can you fix it?'
})
print(result)
"
```

## 📁 API Endpoints (Server Mode)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Service info |
| `/health` | GET | Health check |
| `/process` | POST | Trigger email processing |
| `/status` | GET | Current configuration |

## 🛠️ Troubleshooting

**"GROQ_API_KEY is required"**
- Check your `.env` file has the key set
- Verify no extra spaces around the value

**"Gmail credentials not found"**
- Download OAuth credentials from Google Cloud Console
- Save as `credentials.json` in project root

**"Permission denied" on Sheets**
- Share the Google Sheet with your service account email
- Email looks like: `name@project.iam.gserviceaccount.com`

## 📄 License

MIT License - Feel free to use for your portfolio!

---

Built with 🤖 Groq LLM + Gmail API + Google Sheets API
