"""
Configuration management for Email-to-Sheets Agent
"""
import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Application configuration loaded from environment variables."""
    
    # Groq Configuration
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    GROQ_MODEL: str = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    
    # Google Gemini Configuration (Fallback)
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
    
    # Google Sheets Configuration
    GOOGLE_SHEET_ID: str = os.getenv("GOOGLE_SHEET_ID", "")
    GOOGLE_SHEET_NAME: str = os.getenv("GOOGLE_SHEET_NAME", "Sheet1")
    
    # Gmail Configuration
    GMAIL_CREDENTIALS_PATH: str = os.getenv("GMAIL_CREDENTIALS_PATH", "credentials.json")
    GMAIL_TOKEN_PATH: str = os.getenv("GMAIL_TOKEN_PATH", "token.json")
    GMAIL_LABEL_FILTER: str = os.getenv("GMAIL_LABEL_FILTER", "INBOX")
    GMAIL_CHECK_INTERVAL_MINUTES: int = int(os.getenv("GMAIL_CHECK_INTERVAL_MINUTES", "5"))
    
    # Email Filtering
    FILTER_FROM_EMAIL: str = os.getenv("FILTER_FROM_EMAIL", "")
    FILTER_PRODUCT_ENGINEERING: bool = os.getenv("FILTER_PRODUCT_ENGINEERING", "true").lower() == "true"
    PRODUCT_ENGINEERING_EMAIL: str = os.getenv("PRODUCT_ENGINEERING_EMAIL", "engineering@onescreensolutions.com")
    IGNORED_EMAILS: list = os.getenv("IGNORED_EMAILS", "donotreply@onescreensolutions.com,sage@onescreensolutions.com,noreply@bytello.com").split(",")
    
    # Internal team emails - don't log emails initiated by these addresses
    INTERNAL_TEAM_EMAILS: list = [
        email.strip().lower() 
        for email in os.getenv(
            "INTERNAL_TEAM_EMAILS", 
            "faizan@onescreensolutions.com,fatir@onescreensolutions.com,abdullah@onescreensolutions.com,nasir@onescreensolutions.com,huzaifa@onescreensolutions.com,shoaib@onescreensolutions.com,qursam@onescreensolutions.com,zaman@onescreensolutions.com,engineering@onescreensolutions.com,ops@onescreensolutions.com"
        ).split(",")
        if email.strip()
    ]
    
    # Server Configuration
    PORT: int = int(os.getenv("PORT", "10000"))
    
    # Initial Import Mode - set to true for first run to import from Jan 1, 2026
    # After successful import, set to false to only fetch last 7 days
    INITIAL_IMPORT: bool = os.getenv("INITIAL_IMPORT", "false").lower() == "true"
    
    # Gmail API Scopes
    GMAIL_SCOPES = [
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.modify"
    ]
    
    # Google Sheets API Scopes
    SHEETS_SCOPES = [
        "https://www.googleapis.com/auth/spreadsheets"
    ]
    
    @classmethod
    def validate(cls) -> list[str]:
        """Validate required configuration."""
        errors = []
        if not cls.GROQ_API_KEY:
            errors.append("GROQ_API_KEY is required")
        if not cls.GOOGLE_SHEET_ID:
            errors.append("GOOGLE_SHEET_ID is required")
        return errors
