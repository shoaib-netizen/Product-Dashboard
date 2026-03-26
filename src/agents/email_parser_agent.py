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
    task_name: str = Field(description="Brief name/title of the task")
    description: str = Field(description="Detailed description of the task/query")
    status: str = Field(default="Pending", description="Current status: Pending, In Progress, Completed")
    date_of_query: str = Field(description="Date when query was received (YYYY-MM-DD)")
    date_of_solution: str = Field(default="", description="Date when resolved (empty if pending)")
    request_came_from: str = Field(description="Person/email who sent the request")
    team_origin: str = Field(description="Team/department where request originated")


class EmailParserAgent:
    """
    Agentic AI component that parses emails using LLM intelligence.
    
    This agent:
    1. Receives raw email content
    2. Uses Groq LLM to understand context and extract structured data
    3. Returns standardized task information for Google Sheets
    """
    
    SYSTEM_PROMPT = """You are an intelligent email parser agent. Your job is to extract structured task/query information from emails.

Extract the following fields:
1. task_name: A brief, clear title for the task/query (max 50 chars)
2. description: Full description of what is being requested
3. status: Default to "Pending" unless email indicates otherwise
4. date_of_query: The date the email was sent (format: YYYY-MM-DD)
5. date_of_solution: Leave empty if not resolved
6. request_came_from: The sender's name and email
7. team_origin: Infer the team/department from email signature, domain, or content. If unclear, use "Unknown"

Be intelligent:
- Look for context clues to determine the team
- Extract the core request even if buried in pleasantries
- If multiple tasks in one email, focus on the primary request
- Use professional, concise language for task_name

Respond ONLY with valid JSON matching this structure:
{
    "task_name": "string",
    "description": "string", 
    "status": "Pending|In Progress|Completed",
    "date_of_query": "YYYY-MM-DD",
    "date_of_solution": "",
    "request_came_from": "Name <email>",
    "team_origin": "string"
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
        return f"""Parse this email:

FROM: {email_data.get('from', 'Unknown')}
DATE: {email_data.get('date', datetime.now().strftime('%Y-%m-%d'))}
SUBJECT: {email_data.get('subject', 'No Subject')}

BODY:
{email_data.get('body', 'No content')}

---
Extract the task information as JSON."""

    def _fallback_parse(self, email_data: dict) -> TaskData:
        """Fallback parsing when LLM fails - uses basic extraction."""
        return TaskData(
            task_name=email_data.get('subject', 'Email Task')[:50],
            description=email_data.get('body', '')[:500],
            status="Pending",
            date_of_query=email_data.get('date', datetime.now().strftime('%Y-%m-%d')),
            date_of_solution="",
            request_came_from=email_data.get('from', 'Unknown'),
            team_origin="Unknown"
        )
    
    def batch_parse(self, emails: list[dict]) -> list[TaskData]:
        """Parse multiple emails and return list of TaskData."""
        results = []
        for email in emails:
            task = self.parse_email(email)
            if task:
                results.append(task)
        return results
