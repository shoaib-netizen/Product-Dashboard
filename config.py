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
    
    # Server Configuration
    PORT: int = int(os.getenv("PORT", "10000"))
    
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
