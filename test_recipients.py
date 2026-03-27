"""Test recipient extraction"""
from src.services.gmail_service import GmailService

g = GmailService()
emails = g.fetch_unread_emails(max_results=20)

# Find the OTA email thread
for i, email in enumerate(emails):
    if 'OTA' in email.get('subject', '') or 'Panels Unable' in email.get('subject', ''):
        print(f"\n=== Found OTA Email #{i+1} ===")
        print(f"Subject: {email['subject']}")
        print(f"Thread ID: {email['thread_id']}")
        print(f"Recipients: {email['to']}")
        
        # Now fetch the entire thread
        thread_id = email['thread_id']
        thread_messages = g.fetch_thread_messages(thread_id)
        print(f"\n=== Thread has {len(thread_messages)} messages ===")
        
        # Check the FIRST (original) message
        if thread_messages:
            print(f"\nOriginal email in thread:")
            print(f"Subject: {thread_messages[0].get('subject', '')}")
            print(f"Recipients: {thread_messages[0].get('to', '')}")
        break 
