"""
Email Parser Agent - Uses Groq LLM to intelligently extract task data from emails.
"""
import json
from datetime import datetime
from groq import Groq
from pydantic import BaseModel, Field
from typing import Optional

from config import Config


class TaskData(BaseModel):
    """Structured task data extracted from email."""
    # Email Metadata
    email_subject: str = Field(description="Email subject line")
    sender_name: str = Field(description="Sender's name")
    sender_email: str = Field(description="Sender's email address")
    recipient_email: str = Field(description="Recipient's email address")
    date_sent: str = Field(description="Date/time email was sent (YYYY-MM-DD HH:MM)")
    date_received: str = Field(description="Date/time email was received (YYYY-MM-DD HH:MM)")
    
    # Task Information
    task_name: str = Field(description="Brief name/title of the task")
    email_summary: str = Field(description="Short summary of email body (2-3 sentences)")
    team_origin: str = Field(description="Team/department where request originated")
    
    # Reply Tracking
    reply_status: str = Field(default="No Reply", description="Replied, Pending, No Reply")
    replied_by: str = Field(default="", description="Who replied to the email")
    reply_date: str = Field(default="", description="Date/time of reply (YYYY-MM-DD HH:MM)")
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
    
    SYSTEM_PROMPT = """You are an intelligent email parser agent for a product engineering team. Extract structured information from emails.

Extract these fields:
1. email_subject: The email subject line
2. sender_name: Sender's full name (extract from email if available)
3. sender_email: Sender's email address
4. recipient_email: Recipient's email address  
5. date_sent: Date/time sent (YYYY-MM-DD HH:MM format)
6. date_received: Date/time received (YYYY-MM-DD HH:MM format)
7. task_name: Brief, clear title for the task/request (max 50 chars)
8. email_summary: 2-3 sentence summary of the email body
9. team_origin: Infer team/department (Engineering, Product, Support, Marketing, Sales, Unknown)
10. reply_status: "No Reply" (default for initial emails)
11. replied_by: "" (empty for initial emails)
12. reply_date: "" (empty for initial emails)
13. reply_summary: "" (empty for initial emails)
14. status: "Pending" (task completion status)
15. date_of_solution: "" (empty if not resolved)

Be intelligent:
- Extract sender name from "From" field or email signature
- Infer team from email domain, signature, or content context
- Create concise, actionable task names
- Summarize the core request clearly

Respond ONLY with valid JSON matching this structure:
{
    "email_subject": "string",
    "sender_name": "string",
    "sender_email": "email@domain.com",
    "recipient_email": "email@domain.com",
    "date_sent": "YYYY-MM-DD HH:MM",
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
        """Initialize the Email Parser Agent with Groq client."""
        self.client = Groq(api_key=Config.GROQ_API_KEY)
        self.model = Config.GROQ_MODEL
    
    def parse_email(self, email_data: dict) -> Optional[TaskData]:
        """
        Parse an email and extract structured task data.
        
        Args:
            email_data: Dictionary containing:
                - subject: Email subject line
                - from: Sender email address
                - date: Email date
                - body: Email body content
        
        Returns:
            TaskData object with extracted fields, or None if parsing fails
        """
        email_content = self._format_email_for_parsing(email_data)
        
        try:
            response = self.client.chat.completions.create(
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
            return TaskData(**result)
            
        except Exception as e:
            print(f"[EmailParserAgent] Error parsing email: {e}")
            return self._fallback_parse(email_data)
    
    def _format_email_for_parsing(self, email_data: dict) -> str:
        """Format email data into a prompt for the LLM."""
        return f"""Parse this email for the product engineering team:

SUBJECT: {email_data.get('subject', 'No Subject')}
FROM: {email_data.get('from', 'Unknown')}
TO: {email_data.get('to', 'Unknown')}
DATE SENT: {email_data.get('date_sent', datetime.now().strftime('%Y-%m-%d %H:%M'))}
DATE RECEIVED: {email_data.get('date_received', datetime.now().strftime('%Y-%m-%d %H:%M'))}

BODY:
{email_data.get('body', 'No content')}

---
Extract all the email information as JSON. This is an incoming email, so reply_status should be "No Reply" and reply fields should be empty."""

    def _fallback_parse(self, email_data: dict) -> TaskData:
        """Fallback parsing when LLM fails - uses basic extraction."""
        sender_email = email_data.get('from', 'unknown@unknown.com')
        date_str = email_data.get('date', datetime.now().strftime('%Y-%m-%d'))
        
        return TaskData(
            email_subject=email_data.get('subject', 'No Subject'),
            sender_name=sender_email.split('<')[0].strip() if '<' in sender_email else sender_email,
            sender_email=sender_email,
            recipient_email=email_data.get('to', 'Unknown'),
            date_sent=date_str + " 00:00" if len(date_str) == 10 else date_str,
            date_received=date_str + " 00:00" if len(date_str) == 10 else date_str,
            task_name=email_data.get('subject', 'Email Task')[:50],
            email_summary=email_data.get('body', '')[:200],
            team_origin="Unknown",
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
