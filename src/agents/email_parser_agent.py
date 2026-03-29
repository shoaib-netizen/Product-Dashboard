"""
Email Parser Agent - Uses Groq LLM to intelligently extract task data from emails.
"""
import json
from datetime import datetime
from groq import Groq
from pydantic import BaseModel, Field, field_validator
from typing import Optional

from config import Config

VALID_TEAM_ORIGINS = {
    "Product Ops", "Sales", "Supply Chain & Logistics", "Engineering",
    "Finance", "Marketing", "Support", "HR", "Legal", "Other"
}


class TaskData(BaseModel):
    """Structured task data extracted from email."""
    # Thread Tracking
    thread_id: str = Field(description="Gmail thread ID for tracking conversation")
    
    # Email Metadata
    email_subject: str = Field(description="Email subject line")
    sender_name: str = Field(description="Sender's name")
    sender_email: str = Field(description="Sender's email address")
    date_sent: str = Field(description="Date email was sent (YYYY-MM-DD)")
    date_received: str = Field(description="Date email was received (YYYY-MM-DD)")
    
    # Task Information
    task_name: str = Field(description="Brief name/title of the task")
    email_summary: str = Field(description="Short summary of email body (2-3 sentences)")
    team_origin: str = Field(description="Team/department where request originated")

    @field_validator('team_origin')
    @classmethod
    def normalize_team_origin(cls, v: str) -> str:
        if v not in VALID_TEAM_ORIGINS:
            return "Other"
        return v
    
    # Reply Tracking
    reply_status: str = Field(default="No Reply", description="Replied, Pending, No Reply")
    replied_by: str = Field(default="", description="Who replied to the email")
    reply_date: str = Field(default="", description="Date of reply (YYYY-MM-DD)")
    reply_summary: str = Field(default="", description="Summary of the reply")
    
    # Legacy fields for compatibility
    status: str = Field(default="Pending", description="Task status: Pending, In Progress, Completed")
    date_of_solution: str = Field(default="", description="Date when resolved (empty if pending)")


class EmailParserAgent:
    """
    Agentic AI component that parses emails using LLM intelligence.
    
    This agent:
    1. Receives raw email content
    2. Uses Groq LLM to understand context and extract structured data
    3. Returns standardized task information for Google Sheets
    """
    
    SYSTEM_PROMPT = """You are an intelligent email parser agent for a Product Ops team that manages customer and partner responses. Extract structured information from emails.

Extract these fields:
1. thread_id: Gmail thread ID (will be provided in email data)
2. email_subject: The email subject line
3. sender_name: Sender's full name (extract from email if available)
4. sender_email: Sender's email address
5. date_sent: Date sent (YYYY-MM-DD format)
7. date_received: Date/time received (YYYY-MM-DD HH:MM format)
8. task_name: Brief, clear title for the task/request (max 50 chars)
9. email_summary: 2-3 sentence summary of the email body
10. team_origin: The team/department where the email request originated. Use one of these categories:
    - "Product Ops" — Internal product operations, customer response management, product queries, coordination
    - "Sales" — Sales inquiries, deals, pricing, proposals, partnerships, business development
    - "Supply Chain & Logistics" — Shipping, inventory, warehousing, procurement, delivery, fulfillment, freight
    - "Engineering" — Technical issues, bugs, feature requests, development, integrations, API
    - "Finance" — Invoicing, billing, payments, accounting, purchase orders
    - "Marketing" — Campaigns, branding, PR, events, content
    - "Support" — Customer complaints, help desk, troubleshooting, RMA, returns
    - "HR" — Recruitment, onboarding, internal team matters
    - "Legal" — Contracts, compliance, terms, NDAs
    - "Other" — If none of the above clearly fits
    Classify based on email content, sender's role/department, domain, and context. When in doubt, prefer the most specific match.
11. reply_status: "No Reply" (default for initial emails)
12. replied_by: "" (empty for initial emails)
13. reply_date: "" (empty for initial emails)
14. reply_summary: "" (empty for initial emails)
15. status: "Pending" (default task status)
16. date_of_solution: "" (empty if not resolved)

Be intelligent:
- Extract sender name from "From" field or email signature
- Infer team from email content, sender's role, domain, signature, or context
- Create concise, actionable task names
- Summarize the core request clearly

Respond ONLY with valid JSON matching this structure:
{
    "email_subject": "string",
    "sender_name": "string",
    "sender_email": "email@domain.com",
    "date_sent": "YYYY-MM-DD",
    "date_received": "YYYY-MM-DD HH:MM",
    "task_name": "string",
    "email_summary": "string",
    "team_origin": "string",
    "reply_status": "No Reply",
    "replied_by": "",
    "reply_date": "",
    "reply_summary": "",
    "status": "Pending",
    "date_of_solution": ""
}"""

    def __init__(self):
        """Initialize the Email Parser Agent with multiple Groq clients."""
        # Initialize multiple Groq clients for fallback
        self.groq_api_keys = Config.GROQ_API_KEYS
        self.groq_clients = [Groq(api_key=key) for key in self.groq_api_keys if key]
        self.model = Config.GROQ_MODEL
        self.current_groq_index = 0  # Track which key we're using
        
        print(f"[EmailParserAgent] Initialized with {len(self.groq_clients)} Groq API keys, model: {self.model}")
    
    def parse_email(self, email_data: dict) -> Optional[TaskData]:
        """
        Parse an email and extract structured task data.
        Uses multiple Groq API keys with fallback, then Gemini as final fallback.
        
        Args:
            email_data: Dictionary containing:
                - subject: Email subject line
                - from: Sender email address
                - date: Email date
                - body: Email body content
        
        Returns:
            TaskData object with extracted fields, or None if parsing fails
        """
        import time as _time
        email_content = self._format_email_for_parsing(email_data)
        thread_id = email_data.get('thread_id', 'unknown')
        
        # Try each Groq API key with rate limit retry
        for i, client in enumerate(self.groq_clients):
            try:
                response = client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": self.SYSTEM_PROMPT},
                        {"role": "user", "content": email_content}
                    ],
                    temperature=0.1,  # Low temperature for consistent extraction
                    max_tokens=1000,
                    response_format={"type": "json_object"}
                )
                
                result = json.loads(response.choices[0].message.content)
                # Always inject thread_id from email data (AI may not return it)
                result['thread_id'] = thread_id
                return TaskData(**result)
                
            except Exception as e:
                error_str = str(e).lower()
                if "429" in str(e) or "rate_limit" in error_str:
                    print(f"[EmailParserAgent] Groq key {i+1}/{len(self.groq_clients)} rate limited")
                    # If it's the last key, wait and retry the first key once
                    if i == len(self.groq_clients) - 1:
                        print(f"[EmailParserAgent] All keys rate limited, waiting 15s before retry...")
                        _time.sleep(15)
                        try:
                            response = self.groq_clients[0].chat.completions.create(
                                model=self.model,
                                messages=[
                                    {"role": "system", "content": self.SYSTEM_PROMPT},
                                    {"role": "user", "content": email_content}
                                ],
                                temperature=0.1,
                                max_tokens=1000,
                                response_format={"type": "json_object"}
                            )
                            result = json.loads(response.choices[0].message.content)
                            result['thread_id'] = thread_id
                            return TaskData(**result)
                        except Exception as retry_e:
                            print(f"[EmailParserAgent] Retry after wait also failed: {retry_e}")
                    continue
                else:
                    print(f"[EmailParserAgent] Groq error (key {i+1}): {e}")
                    continue
        
        # All Groq keys failed, use basic fallback
        print(f"[EmailParserAgent] All Groq keys failed, using fallback parser")
        return self._fallback_parse(email_data)
    
    def _format_email_for_parsing(self, email_data: dict) -> str:
        """Format email data into a prompt for the LLM."""
        # Limit body to 2000 chars to save tokens and avoid rate limits
        body = email_data.get('body', 'No content')
        if len(body) > 2000:
            body = body[:2000] + "\n...[truncated]"
        
        return f"""Parse this email:

SUBJECT: {email_data.get('subject', 'No Subject')}
FROM: {email_data.get('from', 'Unknown')}
TO: {email_data.get('to', 'Unknown')}
DATE SENT: {email_data.get('date_sent', datetime.now().strftime('%Y-%m-%d'))}
DATE RECEIVED: {email_data.get('date_received', datetime.now().strftime('%Y-%m-%d'))}

BODY:
{body}

---
Extract the email information as JSON. reply_status="No Reply", reply fields empty."""

    def _fallback_parse(self, email_data: dict) -> TaskData:
        """Fallback parsing when LLM fails - uses basic extraction."""
        sender_email = email_data.get('from', 'unknown@unknown.com')
        date_str = email_data.get('date_sent', email_data.get('date', datetime.now().strftime('%Y-%m-%d')))
        subject = email_data.get('subject', 'No Subject')
        
        # Create a clean summary from subject (don't dump raw email body)
        summary = f"Email regarding: {subject}"
        
        return TaskData(
            thread_id=email_data.get('thread_id', 'unknown'),
            email_subject=subject,
            sender_name=sender_email.split('<')[0].strip() if '<' in sender_email else sender_email,
            sender_email=sender_email,
            date_sent=date_str,
            date_received=date_str,
            task_name=subject[:50],
            email_summary=summary,
            team_origin="Other",
            reply_status="No Reply",
            replied_by="",
            reply_date="",
            reply_summary="",
            status="Pending",
            date_of_solution=""
        )
    
    def batch_parse(self, emails: list[dict]) -> list[TaskData]:
        """Parse multiple emails and return list of TaskData."""
        results = []
        for email in emails:
            task = self.parse_email(email)
            if task:
                results.append(task)
        return results
