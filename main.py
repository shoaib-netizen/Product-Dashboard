"""
Email-to-Sheets Agent - Main Application Entry Point

This Agentic AI application:
1. Monitors Gmail for new emails
2. Uses Groq LLM to intelligently parse and extract task data
3. Stores structured data in Google Sheets

Run modes:
- python main.py          : Run once (process current unread emails)
- python main.py --watch  : Continuous monitoring mode
- python main.py --server : Start web server for Render deployment
"""
import argparse
import sys
import time
import schedule

from config import Config
from src.agents import EmailParserAgent
from src.services import GmailService, GoogleSheetsService
from src.utils import setup_logger

# Initialize logger
logger = setup_logger("email_agent")


class EmailToSheetsAgent:
    """
    Main orchestrator that coordinates the email processing pipeline.
    
    Pipeline:
    Gmail → Email Parser Agent (Groq LLM) → Google Sheets
    """
    
    def __init__(self):
        """Initialize all components."""
        logger.info("Initializing Email-to-Sheets Agent...")
        
        # Validate configuration
        errors = Config.validate()
        if errors:
            for error in errors:
                logger.error(f"Config error: {error}")
            sys.exit(1)
        
        # Initialize components
        self.gmail = GmailService()
        self.parser = EmailParserAgent()
        self.sheets = GoogleSheetsService()
        
        logger.info("✓ All components initialized successfully")
    
    def process_emails(self, max_emails: int = 10) -> int:
        """
        Process unread emails and store in Google Sheets.
        
        Args:
            max_emails: Maximum number of emails to process
            
        Returns:
            Number of emails processed
        """
        logger.info(f"Checking for new emails (max: {max_emails})...")
        
        # Fetch unread emails
        emails = self.gmail.fetch_unread_emails(max_results=max_emails)
        
        if not emails:
            logger.info("No new emails found")
            return 0
        
        logger.info(f"Found {len(emails)} new email(s)")
        
        # Process each email
        processed_count = 0
        for email in emails:
            try:
                subject = email.get('subject', 'No Subject')
                thread_id = email.get('thread_id', '')
                logger.info(f"Processing: {subject[:50]}...")
                
                # Check if this thread already exists in the sheet
                existing_row = self.sheets.find_thread_row(thread_id) if thread_id else None
                
                # Determine if this is a reply (subject starts with Re: or thread exists)
                is_reply = subject.startswith('Re:') or subject.startswith('回复：')
                
                if is_reply and existing_row:
                    # This is a reply to an existing thread - update the row
                    logger.info(f"  → Reply detected for existing thread")
                    
                    # Parse the reply with AI to get summary
                    reply_task = self.parser.parse_email(email)
                    
                    # Get current reply count and increment
                    current_count = 0
                    try:
                        current_count_val = self.sheets.sheet.cell(existing_row, 12).value  # Column L
                        current_count = int(current_count_val) if current_count_val else 0
                    except:
                        pass
                    
                    # Get current replied_by list and append new responder
                    current_replied_by = ""
                    try:
                        current_replied_by = self.sheets.sheet.cell(existing_row, 13).value or ""  # Column M
                    except:
                        pass
                    
                    # Format new responder with email
                    new_responder = email.get('from', 'Unknown')
                    
                    # Append to list if not already there
                    if current_replied_by:
                        # Check if this person already replied
                        if new_responder not in current_replied_by:
                            replied_by_list = current_replied_by + "; " + new_responder
                        else:
                            replied_by_list = current_replied_by
                    else:
                        replied_by_list = new_responder
                    
                    # Update the thread with reply information
                    reply_data = {
                        'reply_count': current_count + 1,
                        'replied_by': replied_by_list,
                        'reply_date': reply_task.date_sent if reply_task else email.get('date_sent', ''),
                        'reply_summary': reply_task.email_summary if reply_task else ''
                    }
                    
                    if self.sheets.update_thread_reply(thread_id, reply_data):
                        self.gmail.mark_as_read(email['message_id'])
                        processed_count += 1
                        logger.info(f"  ✓ Updated thread with reply from {reply_data['replied_by']}")
                    else:
                        logger.warning(f"  ✗ Failed to update thread")
                        
                elif is_reply and not existing_row and thread_id:
                    # Reply detected but original thread not in sheet - fetch full thread
                    logger.info(f"  → Reply detected, fetching full thread...")
                    
                    # Fetch all messages in the thread
                    thread_messages = self.gmail.fetch_thread_messages(thread_id)
                    
                    if thread_messages and len(thread_messages) > 0:
                        # First message is the original email
                        original_email = thread_messages[0]
                        logger.info(f"  → Found {len(thread_messages)} messages in thread")
                        
                        # Parse the original email
                        original_task = self.parser.parse_email(original_email)
                        
                        if original_task:
                            # Add the original email as a new row
                            if self.sheets.add_task(original_task):
                                logger.info(f"  ✓ Added original: {original_task.task_name}")
                                
                                # If there are replies (more than 1 message), update with reply info
                                if len(thread_messages) > 1:
                                    latest_reply = thread_messages[-1]  # Last message is latest reply
                                    reply_task = self.parser.parse_email(latest_reply)
                                    
                                    # Collect all unique responders from the thread (skip original sender)
                                    original_from = original_email.get('from', '')
                                    responders = []
                                    seen = set()
                                    
                                    for msg in thread_messages[1:]:  # Skip first message (original)
                                        responder = msg.get('from', 'Unknown')
                                        if responder and responder not in seen and responder != original_from:
                                            responders.append(responder)
                                            seen.add(responder)
                                    
                                    replied_by_list = "; ".join(responders) if responders else latest_reply.get('from', 'Unknown')
                                    
                                    reply_data = {
                                        'reply_count': len(thread_messages) - 1,  # Total replies
                                        'replied_by': replied_by_list,
                                        'reply_date': reply_task.date_sent if reply_task else latest_reply.get('date_sent', ''),
                                        'reply_summary': reply_task.email_summary if reply_task else ''
                                    }
                                    
                                    self.sheets.update_thread_reply(thread_id, reply_data)
                                    logger.info(f"  ✓ Updated with {len(thread_messages) - 1} reply(s) from {len(responders)} person(s)")
                                
                                # Mark the current email as read
                                self.gmail.mark_as_read(email['message_id'])
                                processed_count += 1
                            else:
                                logger.warning(f"  ✗ Failed to add original email")
                        else:
                            logger.warning(f"  ✗ Failed to parse original email")
                    else:
                        logger.warning(f"  ✗ Could not fetch thread messages")
                else:
                    # New thread - parse and add as new row
                    task_data = self.parser.parse_email(email)
                    
                    if task_data:
                        # Store in Google Sheets
                        if self.sheets.add_task(task_data):
                            # Mark email as read
                            self.gmail.mark_as_read(email['message_id'])
                            processed_count += 1
                            logger.info(f"  ✓ Added: {task_data.task_name}")
                        else:
                            logger.warning(f"  ✗ Failed to add to sheets")
                    else:
                        logger.warning(f"  ✗ Failed to parse email")
                    
            except Exception as e:
                logger.error(f"  ✗ Error processing email: {e}")
        
        logger.info(f"Processed {processed_count}/{len(emails)} emails")
        return processed_count
    
    def run_once(self):
        """Run single processing cycle."""
        logger.info("=" * 50)
        logger.info("Running single processing cycle")
        count = self.process_emails()
        logger.info(f"Completed. Processed {count} emails.")
        return count
    
    def run_historical_import(self, start_date: str = "2026/01/01", max_emails: int = 500):
        """
        Import historical emails from a specific date.
        
        Args:
            start_date: Start date in YYYY/MM/DD format (default: 2026/01/01)
            max_emails: Maximum number of emails to fetch (default: 500)
        """
        logger.info("=" * 50)
        logger.info(f"Starting historical import from {start_date}")
        logger.info(f"Fetching up to {max_emails} emails...")
        
        # Fetch historical emails
        emails = self.gmail.fetch_emails_by_date_range(start_date, max_results=max_emails)
        
        if not emails:
            logger.info("No emails found in date range")
            return 0
        
        logger.info(f"Found {len(emails)} emails to process")
        
        # Track unique threads to avoid duplicates
        processed_threads = set()
        processed_count = 0
        
        for i, email in enumerate(emails, 1):
            try:
                subject = email.get('subject', 'No Subject')
                thread_id = email.get('thread_id', '')
                
                # Skip if we already processed this thread
                if thread_id in processed_threads:
                    continue
                
                logger.info(f"[{i}/{len(emails)}] Processing: {subject[:50]}...")
                
                # Check if this thread already exists in the sheet
                existing_row = self.sheets.find_thread_row(thread_id) if thread_id else None
                
                if existing_row:
                    logger.info(f"  → Thread already in sheet, skipping")
                    processed_threads.add(thread_id)
                    continue
                
                # Fetch full thread to get complete conversation
                thread_messages = self.gmail.fetch_thread_messages(thread_id) if thread_id else [email]
                
                if thread_messages and len(thread_messages) > 0:
                    # First message is the original email
                    original_email = thread_messages[0]
                    
                    # Parse the original email
                    original_task = self.parser.parse_email(original_email)
                    
                    if original_task:
                        # Add the original email as a new row
                        if self.sheets.add_task(original_task):
                            logger.info(f"  ✓ Added: {original_task.task_name}")
                            
                            # If there are replies, update with reply info
                            if len(thread_messages) > 1:
                                latest_reply = thread_messages[-1]
                                reply_task = self.parser.parse_email(latest_reply)
                                
                                # Collect all unique responders from the thread
                                original_from = original_email.get('from', '')
                                responders = []
                                seen = set()
                                
                                for msg in thread_messages[1:]:  # Skip first message (original)
                                    responder = msg.get('from', 'Unknown')
                                    if responder and responder not in seen and responder != original_from:
                                        responders.append(responder)
                                        seen.add(responder)
                                
                                replied_by_list = "; ".join(responders) if responders else latest_reply.get('from', 'Unknown')
                                
                                reply_data = {
                                    'reply_count': len(thread_messages) - 1,
                                    'replied_by': replied_by_list,
                                    'reply_date': reply_task.date_sent if reply_task else latest_reply.get('date_sent', ''),
                                    'reply_summary': reply_task.email_summary if reply_task else ''
                                }
                                
                                self.sheets.update_thread_reply(thread_id, reply_data)
                                logger.info(f"  ✓ Updated with {len(thread_messages) - 1} reply(s)")
                            
                            processed_count += 1
                            processed_threads.add(thread_id)
                        else:
                            logger.warning(f"  ✗ Failed to add to sheets")
                    else:
                        logger.warning(f"  ✗ Failed to parse email")
                else:
                    logger.warning(f"  ✗ Could not fetch thread")
                    
            except Exception as e:
                logger.error(f"  ✗ Error processing email: {e}")
        
        logger.info(f"Historical import completed. Processed {processed_count} threads.")
        return processed_count
    
    def run_watch_mode(self):
        """Run in continuous watch mode with scheduling."""
        interval = Config.GMAIL_CHECK_INTERVAL_MINUTES
        logger.info("=" * 50)
        logger.info(f"Starting watch mode (checking every {interval} minutes)")
        logger.info("Press Ctrl+C to stop")
        
        # Run immediately on start
        self.process_emails()
        
        # Schedule periodic checks
        schedule.every(interval).minutes.do(self.process_emails)
        
        try:
            while True:
                schedule.run_pending()
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("\nStopping watch mode...")


def create_flask_app():
    """Create Flask app for Render deployment."""
    from flask import Flask, jsonify
    
    app = Flask(__name__)
    agent = None
    
    @app.route('/')
    def home():
        return jsonify({
            "status": "running",
            "service": "Email-to-Sheets Agent",
            "version": "1.0.0"
        })
    
    @app.route('/health')
    def health():
        return jsonify({"status": "healthy"})
    
    @app.route('/process', methods=['POST'])
    def process_now():
        """Manually trigger email processing."""
        global agent
        if agent is None:
            agent = EmailToSheetsAgent()
        
        count = agent.process_emails()
        return jsonify({
            "status": "success",
            "processed": count
        })
    
    @app.route('/status')
    def status():
        return jsonify({
            "gmail_filter": Config.GMAIL_LABEL_FILTER,
            "sheet_id": Config.GOOGLE_SHEET_ID[:10] + "...",
            "check_interval": Config.GMAIL_CHECK_INTERVAL_MINUTES
        })
    
    return app


def main():
    """Main entry point with argument parsing."""
    parser = argparse.ArgumentParser(
        description="Email-to-Sheets Agentic AI Application"
    )
    parser.add_argument(
        '--watch', 
        action='store_true',
        help='Run in continuous watch mode'
    )
    parser.add_argument(
        '--server',
        action='store_true', 
        help='Start web server for Render deployment'
    )
    parser.add_argument(
        '--historical',
        action='store_true',
        help='Import historical emails from January 1, 2026'
    )
    parser.add_argument(
        '--start-date',
        type=str,
        default='2026/01/01',
        help='Start date for historical import (YYYY/MM/DD format, default: 2026/01/01)'
    )
    parser.add_argument(
        '--max-emails',
        type=int,
        default=500,
        help='Maximum number of emails to fetch in historical import (default: 500)'
    )
    
    args = parser.parse_args()
    
    if args.server:
        # Server mode for Render
        app = create_flask_app()
        logger.info(f"Starting server on port {Config.PORT}")
        app.run(host='0.0.0.0', port=Config.PORT)
    else:
        # Direct run mode
        agent = EmailToSheetsAgent()
        
        if args.historical:
            # Historical import mode
            agent.run_historical_import(
                start_date=args.start_date,
                max_emails=args.max_emails
            )
        elif args.watch:
            # Continuous watch mode
            agent.run_watch_mode()
        else:
            # Single run mode
            agent.run_once()


if __name__ == "__main__":
    main()
