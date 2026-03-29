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
        
        # Track processed threads within a session to prevent duplicates
        self.processed_threads = set()
        
        logger.info("✓ All components initialized successfully")
    
    def _is_internal_sender(self, email_address: str) -> bool:
        """Check if email address is from internal team."""
        if '<' in email_address and '>' in email_address:
            email_address = email_address.split('<')[1].split('>')[0].strip()
        return email_address.lower().strip() in Config.INTERNAL_TEAM_EMAILS
    
    def _should_skip_email(self, email: dict, is_reply: bool, thread_exists: bool) -> tuple[bool, str]:
        """
        Determine if an email should be skipped based on internal team filtering.
        
        Returns:
            Tuple of (should_skip: bool, reason: str)
        """
        sender = email.get('from', '')
        
        # Always process if it's a reply to an existing thread
        if is_reply and thread_exists:
            return False, ""
        
        # For new threads: skip if internal team is initiating
        if self._is_internal_sender(sender):
            if not is_reply:
                return True, f"Internal sender initiated thread: {sender}"
            return False, ""
        
        return False, ""
    
    def _determine_task_status(self, thread_messages: list) -> str:
        """
        Determine task status based on thread reply history.
        
        Logic:
        - No replies → "Pending" (awaiting response)
        - Internal team replied (last message is internal) → "In Progress" (team is handling)
        - External replied after internal → "Pending" (needs team follow-up)
        - Only 1 message (no replies) → "Pending"
        
        Args:
            thread_messages: List of message dicts in the thread (chronological order)
            
        Returns:
            Task status string
        """
        if len(thread_messages) <= 1:
            return "Pending"
        
        # Check if any internal team member has replied
        internal_replied = False
        last_sender_is_internal = False
        
        for msg in thread_messages[1:]:  # Skip original message
            sender = msg.get('from', '')
            if self._is_internal_sender(sender):
                internal_replied = True
                last_sender_is_internal = True
            else:
                last_sender_is_internal = False
        
        if internal_replied and last_sender_is_internal:
            # Internal team replied last - actively handling
            return "In Progress"
        elif internal_replied and not last_sender_is_internal:
            # Internal replied but external responded after - needs follow-up
            return "In Progress"
        else:
            # Only external replies, no internal response yet
            return "Pending"
    
    def process_emails(self) -> int:
        """
        Process emails and store in Google Sheets.
        Fetches ALL matching emails (no limit).
        
        Returns:
            Number of emails processed
        """
        logger.info("Checking for new emails...")
        
        # Fetch ALL recent emails (read or unread) - will skip those already in sheet
        # If INITIAL_IMPORT=true: fetches ALL from Jan 1, 2026
        # If INITIAL_IMPORT=false: fetches ALL from last 7 days
        emails = self.gmail.fetch_recent_emails()
        
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
                
                # Check if we should skip this email (internal team initiated)
                should_skip, skip_reason = self._should_skip_email(email, is_reply, existing_row is not None)
                if should_skip:
                    logger.info(f"  → Skipping: {skip_reason}")
                    self.gmail.mark_as_read(email['message_id'])
                    continue
                
                # Check if we already processed this thread in this session (prevent duplicates)
                if thread_id in self.processed_threads:
                    logger.info(f"  → Skipping: already processed this thread in this session")
                    self.gmail.mark_as_read(email['message_id'])
                    continue
                
                # Mark thread as processed IMMEDIATELY to prevent duplicates
                # even if an error occurs mid-processing
                if thread_id:
                    self.processed_threads.add(thread_id)
                
                if is_reply and existing_row:
                    # This is a reply to an existing thread - update the row
                    logger.info(f"  → Reply detected for existing thread")
                    
                    # Parse the reply with AI to get summary
                    reply_task = self.parser.parse_email(email)
                    
                    # Get original sender to exclude from responders list
                    original_sender = ""
                    try:
                        original_sender = self.sheets.sheet.cell(existing_row, 5).value or ""  # Column E (Sender Email)
                    except:
                        pass
                    
                    # Get current replied_by list and build unique responders list
                    current_replied_by = ""
                    try:
                        current_replied_by = self.sheets.sheet.cell(existing_row, 11).value or ""  # Column K (Replied By)
                    except:
                        pass
                    
                    # Format new responder
                    new_responder = email.get('from', 'Unknown')
                    
                    # Extract email address for comparison (handles "Name <email@domain.com>" format)
                    def extract_email(responder_str):
                        if '<' in responder_str and '>' in responder_str:
                            return responder_str.split('<')[1].split('>')[0].strip().lower()
                        return responder_str.strip().lower()
                    
                    # Extract just the name from "Name <email@domain.com>" format
                    def extract_name(responder_str):
                        if '<' in responder_str:
                            name = responder_str.split('<')[0].strip().strip('"').strip("'")
                            if name:
                                return name
                        return responder_str.strip()
                    
                    new_email = extract_email(new_responder)
                    original_email = extract_email(original_sender)
                    new_name = extract_name(new_responder)
                    
                    # Build unique responders list (exclude original sender)
                    responders_set = set()
                    responders_list = []
                    
                    # Add existing responders
                    if current_replied_by:
                        for resp in current_replied_by.split(';'):
                            resp = resp.strip()
                            if resp:
                                resp_lower = resp.lower()
                                if resp_lower not in responders_set:
                                    responders_set.add(resp_lower)
                                    responders_list.append(resp)
                    
                    # Add new responder name if not original sender and not duplicate
                    if new_email != original_email and new_name.lower() not in responders_set:
                        responders_set.add(new_name.lower())
                        responders_list.append(new_name)
                    
                    replied_by_list = "; ".join(responders_list) if responders_list else new_name
                    
                    # Determine task status based on who is replying
                    task_status = "In Progress" if self._is_internal_sender(new_email) else "In Progress"
                    
                    # Update the thread with reply information
                    reply_data = {
                        'replied_by': replied_by_list,
                        'reply_date': reply_task.date_sent if reply_task else email.get('date_sent', ''),
                        'reply_summary': reply_task.email_summary if reply_task else '',
                        'task_status': task_status
                    }
                    
                    if self.sheets.update_thread_reply(thread_id, reply_data):
                        self.gmail.mark_as_read(email['message_id'])
                        processed_count += 1
                        logger.info(f"  ✓ Updated thread with reply from {new_responder}")
                        logger.info(f"  → All responders: {replied_by_list}")
                        logger.info(f"  → Task status: {task_status}")
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
                        original_sender = original_email.get('from', '')
                        logger.info(f"  → Found {len(thread_messages)} messages in thread")
                        
                        # Check if original sender is internal - if so, skip entire thread
                        if self._is_internal_sender(original_sender):
                            logger.info(f"  → Skipping thread: initiated by internal team member {original_sender}")
                            self.gmail.mark_as_read(email['message_id'])
                            continue
                        
                        # Parse the original email
                        original_task = self.parser.parse_email(original_email)
                        
                        if original_task:
                            # If there are replies (more than 1 message), update task with reply info BEFORE adding
                            if len(thread_messages) > 1:
                                latest_reply = thread_messages[-1]  # Last message is latest reply
                                reply_task = self.parser.parse_email(latest_reply)
                                
                                # Collect all unique responder names from the thread (skip original sender)
                                original_from = original_email.get('from', '')
                                original_from_email = original_from.split('<')[1].split('>')[0].strip().lower() if '<' in original_from else original_from.strip().lower()
                                responder_names = []
                                seen_names = set()
                                
                                for msg in thread_messages[1:]:  # Skip first message (original)
                                    responder = msg.get('from', 'Unknown')
                                    # Extract email for comparison
                                    resp_email = responder.split('<')[1].split('>')[0].strip().lower() if '<' in responder else responder.strip().lower()
                                    # Extract just the name
                                    resp_name = responder.split('<')[0].strip().strip('"').strip("'") if '<' in responder else responder.strip()
                                    
                                    if resp_email != original_from_email and resp_name.lower() not in seen_names and resp_name:
                                        responder_names.append(resp_name)
                                        seen_names.add(resp_name.lower())
                                
                                latest_from = latest_reply.get('from', 'Unknown')
                                latest_name = latest_from.split('<')[0].strip().strip('"').strip("'") if '<' in latest_from else latest_from.strip()
                                replied_by_list = "; ".join(responder_names) if responder_names else latest_name
                                
                                # Update task object with reply info
                                original_task.reply_status = "Replied"
                                original_task.replied_by = replied_by_list
                                original_task.reply_date = reply_task.date_sent if reply_task else latest_reply.get('date_sent', '')
                                original_task.reply_summary = reply_task.email_summary if reply_task else ''
                                
                                # Determine task status based on who replied
                                original_task.status = self._determine_task_status(thread_messages)
                                 
                                logger.info(f"  → Thread has {len(thread_messages) - 1} reply(s) from: {replied_by_list}")
                                logger.info(f"  → Task status: {original_task.status}")
                            
                            # Add the task with all data included
                            if self.sheets.add_task(original_task):
                                logger.info(f"  ✓ Added original: {original_task.task_name}")
                                # Mark the current email as read
                                self.gmail.mark_as_read(email['message_id'])
                                processed_count += 1
                            else:
                                logger.warning(f"  ✗ Failed to add original email")
                        else:
                            logger.warning(f"  ✗ Failed to parse original email")
                    else:
                        logger.warning(f"  ✗ Could not fetch thread messages")
                elif existing_row:
                    # Thread already in sheet and this is not a reply - skip
                    logger.info(f"  → Skipping: thread already in sheet")
                    continue
                else:
                    # New thread - fetch full thread to check for any replies
                    thread_messages = self.gmail.fetch_thread_messages(thread_id) if thread_id else [email]
                    
                    if thread_messages and len(thread_messages) > 0:
                        # Use the first message (original) for parsing
                        original_email_msg = thread_messages[0]
                        
                        # Check if original sender is internal - skip entire thread
                        orig_sender = original_email_msg.get('from', '')
                        if self._is_internal_sender(orig_sender):
                            logger.info(f"  → Skipping thread: initiated by internal team member {orig_sender}")
                            self.gmail.mark_as_read(email['message_id'])
                            continue
                        
                        task_data = self.parser.parse_email(original_email_msg)
                        
                        if task_data:
                            # Check if thread has replies
                            if len(thread_messages) > 1:
                                latest_reply = thread_messages[-1]
                                reply_task = self.parser.parse_email(latest_reply)
                                
                                # Collect unique responder names (exclude original sender)
                                original_from = original_email_msg.get('from', '')
                                original_from_email = original_from.split('<')[1].split('>')[0].strip().lower() if '<' in original_from else original_from.strip().lower()
                                responder_names = []
                                seen_names = set()
                                
                                for msg in thread_messages[1:]:
                                    responder = msg.get('from', 'Unknown')
                                    resp_email = responder.split('<')[1].split('>')[0].strip().lower() if '<' in responder else responder.strip().lower()
                                    resp_name = responder.split('<')[0].strip().strip('"').strip("'") if '<' in responder else responder.strip()
                                    
                                    if resp_email != original_from_email and resp_name.lower() not in seen_names and resp_name:
                                        responder_names.append(resp_name)
                                        seen_names.add(resp_name.lower())
                                
                                latest_from = latest_reply.get('from', 'Unknown')
                                latest_name = latest_from.split('<')[0].strip().strip('"').strip("'") if '<' in latest_from else latest_from.strip()
                                replied_by_list = "; ".join(responder_names) if responder_names else latest_name
                                
                                task_data.reply_status = "Replied"
                                task_data.replied_by = replied_by_list
                                task_data.reply_date = reply_task.date_sent if reply_task else latest_reply.get('date_sent', '')
                                task_data.reply_summary = reply_task.email_summary if reply_task else ''
                                task_data.status = self._determine_task_status(thread_messages)
                                
                                logger.info(f"  → Thread has {len(thread_messages) - 1} reply(s) from: {replied_by_list}")
                                logger.info(f"  → Task status: {task_data.status}")
                            
                            # Store in Google Sheets
                            if self.sheets.add_task(task_data):
                                self.gmail.mark_as_read(email['message_id'])
                                processed_count += 1
                                logger.info(f"  ✓ Added: {task_data.task_name}")
                            else:
                                logger.warning(f"  ✗ Failed to add to sheets")
                        else:
                            logger.warning(f"  ✗ Failed to parse email")
                    else:
                        logger.warning(f"  ✗ Could not fetch thread")
                    
            except Exception as e:
                logger.error(f"  ✗ Error processing email: {e}")
        
        logger.info(f"Processed {processed_count}/{len(emails)} emails")
        return processed_count
    
    def run_once(self):
        """Run single processing cycle."""
        logger.info("=" * 50)
        logger.info("Running single processing cycle")
        logger.info(f"INITIAL_IMPORT={Config.INITIAL_IMPORT}")
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
                        # If there are replies, update the task with reply info BEFORE adding
                        if len(thread_messages) > 1:
                            latest_reply = thread_messages[-1]
                            reply_task = self.parser.parse_email(latest_reply)
                            
                            # Collect all unique responder names from the thread
                            original_from = original_email.get('from', '')
                            original_email_addr = original_from.split('<')[1].split('>')[0].strip().lower() if '<' in original_from else original_from.strip().lower()
                            responder_names = []
                            seen_names = set()
                            
                            for msg in thread_messages[1:]:  # Skip first message (original)
                                responder = msg.get('from', 'Unknown')
                                # Extract email for comparison
                                resp_email = responder.split('<')[1].split('>')[0].strip().lower() if '<' in responder else responder.strip().lower()
                                # Extract just the name
                                resp_name = responder.split('<')[0].strip().strip('"').strip("'") if '<' in responder else responder.strip()
                                
                                if resp_email != original_email_addr and resp_name.lower() not in seen_names and resp_name:
                                    responder_names.append(resp_name)
                                    seen_names.add(resp_name.lower())
                            
                            replied_by_list = "; ".join(responder_names) if responder_names else latest_reply.get('from', 'Unknown').split('<')[0].strip()
                            
                            # Update the task object with reply info
                            original_task.reply_status = "Replied"
                            original_task.replied_by = replied_by_list
                            original_task.reply_date = reply_task.date_sent if reply_task else latest_reply.get('date_sent', '')
                            original_task.reply_summary = reply_task.email_summary if reply_task else ''
                            
                            # Determine task status based on who replied
                            original_task.status = self._determine_task_status(thread_messages)
                            
                            logger.info(f"  → Thread has {len(thread_messages) - 1} reply(s) from: {replied_by_list}")
                            logger.info(f"  → Task status: {original_task.status}")
                        
                        # Add the task with all data included
                        if self.sheets.add_task(original_task):
                            logger.info(f"  ✓ Added: {original_task.task_name}")
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


# Global agent instance for Flask app
_flask_agent = None

def create_flask_app():
    """Create Flask app for Render deployment."""
    from flask import Flask, jsonify
    
    app = Flask(__name__)
    
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
    
    @app.route('/process', methods=['GET', 'POST'])
    def process_now():
        """Manually trigger email processing."""
        global _flask_agent
        if _flask_agent is None:
            _flask_agent = EmailToSheetsAgent()
        
        count = _flask_agent.process_emails()
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
