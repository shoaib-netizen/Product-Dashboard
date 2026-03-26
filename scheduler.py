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
    
    # Initialize agent
    agent = EmailToSheetsAgent()
    
    def job():
        """Scheduled job to process emails."""
        logger.info(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Running scheduled check...")
        try:
            count = agent.process_emails()
            logger.info(f"Scheduled run complete. Processed: {count} emails")
        except Exception as e:
            logger.error(f"Scheduled run failed: {e}")
    
    # Run immediately on start
    job()
    
    # Schedule periodic runs
    schedule.every(Config.GMAIL_CHECK_INTERVAL_MINUTES).minutes.do(job)
    
    logger.info(f"Scheduler running. Next check in {Config.GMAIL_CHECK_INTERVAL_MINUTES} minutes...")
    
    # Keep running
    while True:
        schedule.run_pending()
        time.sleep(30)  # Check every 30 seconds if job is due


if __name__ == "__main__":
    run_scheduler()
