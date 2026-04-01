"""
Chat-only Background Scheduler

Runs as a background worker, periodically checking
for new Google Chat messages and writing them to the sheet.

Usage:
    python chat_scheduler.py
"""
import time
import schedule
from datetime import datetime

from config import Config
from src.utils import setup_logger

logger = setup_logger("chat_scheduler")


def run_chat_scheduler():
    """Run the chat-only scheduler."""
    logger.info("=" * 60)
    logger.info("Chat-to-Sheets Scheduler Starting")
    logger.info(f"Space ID       : {Config.CHAT_SPACE_ID}")
    logger.info(f"Check interval : {Config.CHAT_CHECK_INTERVAL_MINUTES} minute(s)")
    logger.info(f"Sheet name     : {Config.CHAT_SHEET_NAME}")
    logger.info("=" * 60)

    if not Config.CHAT_SPACE_ID:
        logger.error("CHAT_SPACE_ID is not set in .env — nothing to do.")
        return

    from src.agents import ChatToSheetsAgent
    try:
        chat_agent = ChatToSheetsAgent()
    except Exception as e:
        logger.error(f"Failed to initialize Chat agent: {e}")
        return

    def chat_job():
        logger.info(
            f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Running chat check..."
        )
        try:
            count = chat_agent.process_messages()
            logger.info(f"Chat check complete. Inserted: {count} new message(s)")
        except Exception as e:
            logger.error(f"Chat check failed: {e}")

    # Run once immediately on start
    chat_job()

    # Then run every N minutes
    schedule.every(Config.CHAT_CHECK_INTERVAL_MINUTES).minutes.do(chat_job)
    logger.info(f"Next check in {Config.CHAT_CHECK_INTERVAL_MINUTES} minute(s)...")

    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    run_chat_scheduler()