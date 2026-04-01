"""
Configuration management for Email-to-Sheets Agent
"""
import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Application configuration loaded from environment variables."""
    
    # Groq Configuration (multiple keys for fallback)
    GROQ_API_KEYS: list = [
        key.strip() for key in os.getenv("GROQ_API_KEYS", os.getenv("GROQ_API_KEY", "")).split(",")
        if key.strip()
    ]
    GROQ_API_KEY: str = GROQ_API_KEYS[0] if GROQ_API_KEYS else ""  # Backward compatibility
    GROQ_MODEL: str = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
    
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

    # ----------------------------------------------------------------------
    # Google Chat Configuration
    #
    # The following settings enable an optional pipeline for monitoring a
    # Google Chat space and writing selected messages to a secondary sheet.
    # If CHAT_SPACE_ID is not provided then the Chat pipeline is disabled by
    # default.  When enabled, only messages from specific users are captured.

    # Space ID of the Google Chat room to monitor.  This is the identifier
    # following the `spaces/` prefix in the space resource name.  It can be
    # found in the Chat web URL (for example the segment after `#chat/`).
    CHAT_SPACE_ID: str = os.getenv("CHAT_SPACE_ID", "")

    # Name of the worksheet within the Google spreadsheet used for Chat
    # messages.  The sheet will be created if it doesn't already exist.  The
    # default name is ``Sheet2`` to avoid clashing with the primary sheet.
    CHAT_SHEET_NAME: str = os.getenv("CHAT_SHEET_NAME", "Sheet2")

    # Comma‑separated list of email addresses whose messages should be
    # recorded from the Chat space.  All addresses are converted to lower
    # case.  Messages sent by users outside of this list will be ignored.
    CHAT_USER_EMAILS: list = [
        email.strip().lower()
        for email in os.getenv(
            "CHAT_USER_EMAILS",
            "talha@onescreensolutions.com,sijjil@onescreensolutions.com,junaid@onescreensolutions.com,david@onescreensolutions.com,alis@onescreensolutions.com",
        ).split(",")
        if email.strip()
    ]

    # Frequency in minutes at which to poll the Chat space for new
    # messages.  Setting this to zero disables automatic polling; the Chat
    # agent can still be invoked manually via the command line.  The default
    # mirrors the email polling interval.
    CHAT_CHECK_INTERVAL_MINUTES: int = int(os.getenv("CHAT_CHECK_INTERVAL_MINUTES", "5"))

    # When true, the Chat agent will import all messages from the space
    # starting from January 1, 2026 on the first run.  After a successful
    # import, set this to false to only fetch messages from the last seven
    # days.  You can override this behaviour by passing explicit date
    # parameters when invoking the Chat agent programmatically.
    CHAT_INITIAL_IMPORT: bool = os.getenv("CHAT_INITIAL_IMPORT", "false").lower() == "true"

    # OAuth2 scopes required for reading chat messages and membership data.  The
    # readonly scopes ensure that the integration cannot modify or delete
    # messages within the space.  The memberships scope allows lookup of
    # membership details by email when necessary.
    CHAT_SCOPES = [
        "https://www.googleapis.com/auth/chat.messages.readonly",
        "https://www.googleapis.com/auth/chat.memberships.readonly",
    ]

    # Path to the OAuth2 client secrets file used for Chat authentication.
    # Defaults to the same file used by the Gmail integration.  Modify
    # CHAT_CREDENTIALS_PATH if you wish to use a different client for Chat.
    CHAT_CREDENTIALS_PATH: str = os.getenv("CHAT_CREDENTIALS_PATH", GMAIL_CREDENTIALS_PATH)

    # Location of the locally stored OAuth2 token for Chat.  When running
    # locally for the first time, you will be prompted to complete the
    # authentication flow and the resulting token will be persisted at this
    # path.  On Render, provide a `CHAT_TOKEN_JSON` environment variable
    # containing the JSON representation of the token.
    CHAT_TOKEN_PATH: str = os.getenv("CHAT_TOKEN_PATH", "chat_token.json")
    
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
