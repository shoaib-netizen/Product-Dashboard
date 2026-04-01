"""
Background Scheduler for Render Deployment

This runs as a background worker on Render, periodically checking 
for new emails and processing them.

Usage:
    python scheduler.py
"""
import time
import schedule
from datetime import datetime

from config import Config
from src.utils import setup_logger

logger = setup_logger("scheduler")


def run_scheduler():
    """Run the email processing scheduler."""
    from main import EmailToSheetsAgent
    
    logger.info("=" * 60)
    logger.info("Email-to-Sheets Scheduler Starting")
    logger.info(f"Check interval: {Config.GMAIL_CHECK_INTERVAL_MINUTES} minutes")
    logger.info("=" * 60)
    
    # Initialize agents
    email_agent = EmailToSheetsAgent()
    chat_agent = None
    chat_enabled = False
    try:
        # Attempt to import ChatToSheetsAgent lazily to avoid circular dependency
        from src.agents import ChatToSheetsAgent
        # Enable chat pipeline only if configured
        if Config.CHAT_SPACE_ID and Config.CHAT_CHECK_INTERVAL_MINUTES > 0:
            chat_agent = ChatToSheetsAgent()
            chat_enabled = True
    except Exception as e:
        logger.error(f"Chat agent could not be initialized: {e}")
    
    def email_job():
        """Scheduled job to process emails."""
        logger.info(
            f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Running scheduled email check..."
        )
        try:
            count = email_agent.process_emails()
            logger.info(f"Scheduled email run complete. Processed: {count} email(s)")
        except Exception as e:
            logger.error(f"Scheduled email run failed: {e}")

    def chat_job():
        """Scheduled job to process chat messages."""
        logger.info(
            f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Running scheduled chat check..."
        )
        try:
            count = chat_agent.process_messages()
            logger.info(f"Scheduled chat run complete. Processed: {count} chat message(s)")
        except Exception as e:
            logger.error(f"Scheduled chat run failed: {e}")
    
    # Run immediately on start
    email_job()
    if chat_enabled and chat_agent:
        chat_job()
    
    # Schedule periodic runs
    schedule.every(Config.GMAIL_CHECK_INTERVAL_MINUTES).minutes.do(email_job)
    if chat_enabled and chat_agent:
        schedule.every(Config.CHAT_CHECK_INTERVAL_MINUTES).minutes.do(chat_job)
    
    if chat_enabled:
        logger.info(
            f"Scheduler running. Next email check in {Config.GMAIL_CHECK_INTERVAL_MINUTES} minute(s), "
            f"next chat check in {Config.CHAT_CHECK_INTERVAL_MINUTES} minute(s)..."
        )
    else:
        logger.info(
            f"Scheduler running. Next email check in {Config.GMAIL_CHECK_INTERVAL_MINUTES} minute(s)."
        )
    
    # Keep running
    while True:
        schedule.run_pending()
        time.sleep(30)  # Check every 30 seconds if job is due


if __name__ == "__main__":
    run_scheduler()
