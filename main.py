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
from email.utils import parseaddr  # for robust name/email parsing

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
        logger.info("Step 1: Initializing Gmail...")
        self.gmail = GmailService()
        logger.info("Step 1 done ✓")
        
        logger.info("Step 2: Initializing Parser...")
        self.parser = EmailParserAgent()
        logger.info("Step 2 done ✓")
        
        logger.info("Step 3: Initializing Sheets...")
        self.sheets = GoogleSheetsService()
        logger.info("Step 3 done ✓")
        
        # Track processed threads within a session to prevent duplicates
        self.processed_threads = set()
        
        logger.info("✓ All components initialized successfully")
    
    def _is_internal_sender(self, email_address: str) -> bool:
        """Check if email address is from internal team."""
        if '<' in email_address and '>' in email_address:
            email_address = email_address.split('<')[1].split('>')[0].strip()
        return email_address.lower().strip() in Config.INTERNAL_TEAM_EMAILS
    
    def _determine_origin_type(self, email_address: str) -> str:
        """
        Determine if conversation origin is Internal or External.
        
        Args:
            email_address: Original sender's email address
            
        Returns:
            "Internal" if sender is in INTERNAL_TEAM_EMAILS, "External" otherwise
        """
        return "Internal" if self._is_internal_sender(email_address) else "External"
    
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

    def _extract_unique_repliers(self, thread_messages: list, exclude_email: str | None = None) -> list[str]:
        """
        Extract a list of unique responder names from a thread.

        This helper parses the "From" header of each message in ``thread_messages``
        (excluding the first element which is considered the original email) and
        returns a list of unique names in the order they appear. When
        ``exclude_email`` is provided, any messages sent from that email address
        will be ignored. Names are normalised to lowercase for de‑duplication
        but the original casing is preserved in the output.

        Args:
            thread_messages: List of message dictionaries representing the full thread.
            exclude_email: Optional email address to exclude from the results.

        Returns:
            A list of unique responder names.
        """
        # parseaddr is imported at module level
        seen = set()
        responders: list[str] = []

        # Determine lowercased email to exclude if provided
        excluded = exclude_email.lower().strip() if exclude_email else None

        for msg in thread_messages[1:]:  # skip the original message
            from_field = msg.get('from', '') or ''
            name, email = parseaddr(from_field)
            email = email.lower().strip() if email else ''

            # Skip excluded email address, if any
            if excluded and email == excluded:
                continue

            # Derive a name if none provided
            if not name:
                # Use the portion before '@' as a fallback name
                if email:
                    name = email.split('@')[0]
                else:
                    continue  # nothing to extract

            # Normalise name for de‑duplication
            name_clean = name.strip()
            name_key = name_clean.lower()
            if name_key and name_key not in seen:
                responders.append(name_clean)
                seen.add(name_key)

        return responders
    
    # NEW — PASTE THIS
    def process_emails(self) -> int:
        """
        Process emails and store in Google Sheets.
        Fetches ALL matching emails (no limit).

        Returns:
            Number of emails processed
        """
        # AFTER
        logger.info("Checking for new emails...")

        # Pre-load all existing thread IDs from sheet FIRST — before any Gmail calls.
        # This lets fetch_recent_emails skip expensive _get_email_details calls for
        # threads already in the sheet, dramatically cutting API usage and run time.
        try:
            existing_thread_ids = set(tid for tid in self.sheets.sheet.col_values(2)[1:] if tid)
            logger.info(f"Loaded {len(existing_thread_ids)} existing thread IDs from sheet")
        except Exception:
            existing_thread_ids = set()
            logger.warning("Could not load existing thread IDs from sheet — will fetch all email details")

        # Fetch ALL recent emails (read or unread) — already-in-sheet threads returned as stubs
        # If INITIAL_IMPORT=true: fetches ALL from Jan 1, 2026
        # If INITIAL_IMPORT=false: fetches ALL emails from last 7 days
        emails = self.gmail.fetch_recent_emails(existing_thread_ids=existing_thread_ids)

        if not emails:
            logger.info("No new emails found")
            return 0

        logger.info(f"Found {len(emails)} email(s) (including stubs for existing threads)")

        # Deduplicate by thread_id BEFORE processing anything
        # Gmail returns one message ID per email in a thread, so a thread with
        # 9 replies comes back as 10 separate entries in the list.
        # We collapse these to one entry per thread (the first/oldest message)
        # so each thread is only processed once.
        seen_thread_ids_dedup = set()
        unique_emails = []
        for email in emails:
            tid = email.get('thread_id', '')
            if not tid:
                unique_emails.append(email)
                continue
            if tid not in seen_thread_ids_dedup:
                seen_thread_ids_dedup.add(tid)
                unique_emails.append(email)

        logger.info(f"Unique threads to process: {len(unique_emails)} (from {len(emails)} messages)")

        # Process each unique thread
        processed_count = 0
        for email in unique_emails:
            try:
                subject = email.get('subject', 'No Subject')
                thread_id = email.get('thread_id', '')
                logger.info(f"Processing: {subject[:50]}...")

                # Skip if already processed in this session
                if thread_id and thread_id in self.processed_threads:
                    logger.info(f"  → Skipping: already processed this thread in this session")
                    continue

                # If thread already exists in the sheet, update reply info
                if thread_id and thread_id in existing_thread_ids:
                    # Fetch all messages in the thread once
                    thread_messages = self.gmail.fetch_thread_messages(thread_id)
                    if not thread_messages:
                        logger.warning(f"  → Thread {thread_id} fetched empty messages; skipping update")
                    else:
                        # Get original sender to exclude them from responder list
                        original_msg = thread_messages[0]
                        _, orig_email_addr = parseaddr(original_msg.get('from', '') or '')
                        orig_email_addr = orig_email_addr.lower().strip() if orig_email_addr else ''

                        # Extract unique responder names EXCLUDING the original sender
                        responder_names = self._extract_unique_repliers(thread_messages, exclude_email=orig_email_addr)

                        if responder_names:
                            latest_reply = thread_messages[-1]
                            reply_task = self.parser.parse_email(latest_reply)
                            reply_data = {
                                'reply_status': 'Replied',
                                'replied_by': '; '.join(responder_names),
                                'reply_date': reply_task.date_sent if reply_task else latest_reply.get('date_sent', ''),
                                'reply_summary': reply_task.email_summary if reply_task else '',
                                'task_status': self._determine_task_status(thread_messages)
                            }
                            updated = self.sheets.update_thread_reply(thread_id, reply_data)
                            if updated:
                                logger.info(
                                    f"  → Updated reply for existing thread: {thread_id} | Replied by: {reply_data['replied_by']}"
                                )
                            else:
                                logger.info(f"  → Thread exists but update failed: {thread_id}")
                        else:
                            # No real replies — do NOT touch the sheet at all
                            logger.info(f"  → No replies from others for thread {thread_id}, skipping update")

                    # Mark the triggering email as read to avoid reprocessing
                    if email.get('message_id'):
                        self.gmail.mark_as_read(email['message_id'])
                    continue

                # Mark thread as processed IMMEDIATELY to prevent duplicates
                if thread_id:
                    self.processed_threads.add(thread_id)


                # Fetch full thread to get complete conversation including all replies
                if thread_id:
                    thread_messages = self.gmail.fetch_thread_messages(thread_id)
                else:
                    thread_messages = []

                # Fallback: if thread fetch failed or returned empty, use the email itself
                # This ensures no email is ever silently dropped
                if not thread_messages:
                    logger.warning(f"  → Thread fetch returned empty, using email directly")
                    thread_messages = [email]

                # Always use the first (oldest) message as the original email
                original_email_msg = thread_messages[0]
                orig_sender = original_email_msg.get('from', '')

                logger.info(f"  → Found {len(thread_messages)} messages in thread")

                # Parse the original email
                original_task = self.parser.parse_email(original_email_msg)

                if not original_task:
                    logger.warning(f"  ✗ Failed to parse email, skipping")
                    continue

                # Set origin type based on original sender
                original_task.origin_type = self._determine_origin_type(orig_sender)
                logger.info(f"  → Origin Type: {original_task.origin_type}")

                # If thread has replies, enrich task with reply data before adding
                if len(thread_messages) > 1:
                    # Latest message used to obtain reply metadata
                    latest_reply = thread_messages[-1]
                    reply_task = self.parser.parse_email(latest_reply)

                    # Exclude the original sender from the responder list
                    orig_sender_field = original_email_msg.get('from', '') or ''
                    # Extract the raw email address of the original sender
                    _, orig_email_addr = parseaddr(orig_sender_field)
                    orig_email_addr = orig_email_addr.lower().strip() if orig_email_addr else ''

                    # Collect unique responder names excluding the original sender
                    responder_names = self._extract_unique_repliers(thread_messages, exclude_email=orig_email_addr)

                    if responder_names:
                        # Populate reply tracking fields on the task
                        original_task.reply_status = "Replied"
                        original_task.replied_by = "; ".join(responder_names)
                        original_task.reply_date = reply_task.date_sent if reply_task else latest_reply.get('date_sent', '')
                        original_task.reply_summary = reply_task.email_summary if reply_task else ''
                        original_task.status = self._determine_task_status(thread_messages)

                        logger.info(
                            f"  → Thread has {len(thread_messages) - 1} reply(s) from: {original_task.replied_by}"
                        )
                        logger.info(f"  → Task status: {original_task.status}")
                    else:
                        logger.info(f"  → Thread has {len(thread_messages) - 1} message(s) but only from original sender")

                # Add to Google Sheets
                if self.sheets.add_task(original_task):
                    if email.get('message_id'):
                        self.gmail.mark_as_read(email['message_id'])
                    processed_count += 1
                    existing_thread_ids.add(thread_id)  # Prevent re-check in same run
                    logger.info(f"  ✓ Added: {original_task.email_subject[:50]}...")
                else:
                    logger.warning(f"  ✗ Failed to add to sheets")

            except Exception as e:
                logger.error(f"  ✗ Error processing email: {e}")

        logger.info(f"Processed {processed_count}/{len(unique_emails)} unique threads")
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
                        # Set origin type based on original sender
                        original_sender = original_email.get('from', '')
                        original_task.origin_type = self._determine_origin_type(original_sender)
                        logger.info(f"  → Origin Type: {original_task.origin_type}")
                        
                        # If there are replies, update the task with reply info BEFORE adding
                        if len(thread_messages) > 1:
                            latest_reply = thread_messages[-1]
                            reply_task = self.parser.parse_email(latest_reply)
                            
                            # Collect all unique responder names from the thread
                            original_from = original_email.get('from', '')
                            original_email_addr = original_from.split('<')[1].split('>')[0].strip().lower() if '<' in original_from else original_from.strip().lower()
                            responder_names = []
                            seen_names = set()
                            
                            # Collect unique responder names excluding the original sender
                            responder_names = self._extract_unique_repliers(thread_messages, exclude_email=original_email_addr)
                            if responder_names:
                                replied_by_list = "; ".join(responder_names)
                                # Update the task object with reply info
                                original_task.reply_status = "Replied"
                                original_task.replied_by = replied_by_list
                                original_task.reply_date = reply_task.date_sent if reply_task else latest_reply.get('date_sent', '')
                                original_task.reply_summary = reply_task.email_summary if reply_task else ''
                                # Determine task status based on who replied
                                original_task.status = self._determine_task_status(thread_messages)
                                logger.info(f"  → Thread has {len(thread_messages) - 1} reply(s) from: {replied_by_list}")
                                logger.info(f"  → Task status: {original_task.status}")
                            else:
                                logger.info(f"  → Thread has {len(thread_messages) - 1} message(s) but only from original sender")
                        
                        # Add the task with all data included
                        if self.sheets.add_task(original_task):
                            logger.info(f"  ✓ Added: {original_task.email_subject[:50]}...")
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
