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
                is_reply = subject.startswith('Re:') or existing_row is not None
                
                if is_reply and existing_row:
                    # This is a reply to an existing thread - update the row
                    logger.info(f"  → Reply detected for existing thread")
                    
                    # Parse the reply with AI to get summary
                    reply_task = self.parser.parse_email(email)
                    
                    # Get current reply count and increment
                    current_count = 0
                    try:
                        current_count_val = self.sheets.sheet.cell(existing_row, 13).value  # Column M
                        current_count = int(current_count_val) if current_count_val else 0
                    except:
                        pass
                    
                    # Update the thread with reply information
                    reply_data = {
                        'reply_count': current_count + 1,
                        'replied_by': reply_task.sender_name if reply_task else email.get('from', 'Unknown'),
                        'reply_date': reply_task.date_sent if reply_task else email.get('date_sent', ''),
                        'reply_summary': reply_task.email_summary if reply_task else ''
                    }
                    
                    if self.sheets.update_thread_reply(thread_id, reply_data):
                        self.gmail.mark_as_read(email['message_id'])
                        processed_count += 1
                        logger.info(f"  ✓ Updated thread with reply from {reply_data['replied_by']}")
                    else:
                        logger.warning(f"  ✗ Failed to update thread")
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
    
    args = parser.parse_args()
    
    if args.server:
        # Server mode for Render
        app = create_flask_app()
        logger.info(f"Starting server on port {Config.PORT}")
        app.run(host='0.0.0.0', port=Config.PORT)
    else:
        # Direct run mode
        agent = EmailToSheetsAgent()
        
        if args.watch:
            agent.run_watch_mode()
        else:
            agent.run_once()


if __name__ == "__main__":
    main()
