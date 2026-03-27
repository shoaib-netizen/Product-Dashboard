"""
Gmail Service - Handles Gmail API integration for fetching emails.
"""
import os
import base64
import json
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Optional
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from config import Config


class GmailService:
    """
    Service for interacting with Gmail API.
    
    Handles:
    - Authentication (OAuth2)
    - Fetching unread emails
    - Marking emails as processed
    """
    
    def __init__(self):
        """Initialize Gmail service with authentication."""
        self.creds = self._authenticate()
        self.service = build('gmail', 'v1', credentials=self.creds)
        self.processed_label = "PROCESSED_BY_AGENT"
    
    def _authenticate(self) -> Credentials:
        """Authenticate with Gmail API using OAuth2."""
        creds = None
        
        # Load existing token
        if os.path.exists(Config.GMAIL_TOKEN_PATH):
            creds = Credentials.from_authorized_user_file(
                Config.GMAIL_TOKEN_PATH, 
                Config.GMAIL_SCOPES
            )
        
        # Refresh or create new credentials
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not os.path.exists(Config.GMAIL_CREDENTIALS_PATH):
                    raise FileNotFoundError(
                        f"Gmail credentials not found at {Config.GMAIL_CREDENTIALS_PATH}. "
                        "Please download from Google Cloud Console."
                    )
                flow = InstalledAppFlow.from_client_secrets_file(
                    Config.GMAIL_CREDENTIALS_PATH, 
                    Config.GMAIL_SCOPES
                )
                creds = flow.run_local_server(port=0)
            
            # Save credentials for future use
            with open(Config.GMAIL_TOKEN_PATH, 'w') as token:
                token.write(creds.to_json())
        
        return creds
    
    def fetch_unread_emails(self, max_results: int = 10) -> list[dict]:
        """
        Fetch unread emails from inbox.
        
        Args:
            max_results: Maximum number of emails to fetch
            
        Returns:
            List of email dictionaries with subject, from, date, body
        """
        from datetime import datetime, timedelta
        
        # Get yesterday's date for filtering (after yesterday = today and onwards)
        yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y/%m/%d')
        
        # Fetch ALL emails from today (including already read ones)
        query = f"label:{Config.GMAIL_LABEL_FILTER} after:{yesterday}"
        
        # Filter for Product Engineering emails only
        if Config.FILTER_PRODUCT_ENGINEERING:
            query += f" (to:{Config.PRODUCT_ENGINEERING_EMAIL} OR cc:{Config.PRODUCT_ENGINEERING_EMAIL})"
        
        # Exclude specific senders
        query += f" -from:donotreply@onescreensolutions.com -from:sage@onescreensolutions.com"
        
        if Config.FILTER_FROM_EMAIL:
            query += f" from:{Config.FILTER_FROM_EMAIL}"
        
        try:
            results = self.service.users().messages().list(
                userId='me',
                q=query,
                maxResults=max_results
            ).execute()
            
            messages = results.get('messages', [])
            emails = []
            
            for msg in messages:
                email_data = self._get_email_details(msg['id'])
                if email_data:
                    email_data['message_id'] = msg['id']
                    emails.append(email_data)
            
            # Sort by date sent (newest first - descending order)
            emails.sort(key=lambda x: x.get('date_sent', ''), reverse=True)
            
            return emails
            
        except Exception as e:
            print(f"[GmailService] Error fetching emails: {e}")
            return []
    
    def fetch_emails_by_date_range(self, start_date: str, end_date: str = None, max_results: int = 500) -> list[dict]:
        """
        Fetch emails within a date range (for historical import).
        
        Args:
            start_date: Start date in YYYY/MM/DD format (e.g., "2026/01/01")
            end_date: End date in YYYY/MM/DD format (optional, defaults to today)
            max_results: Maximum number of emails to fetch
            
        Returns:
            List of email dictionaries
        """
        from datetime import datetime
        
        if end_date is None:
            end_date = datetime.now().strftime('%Y/%m/%d')
        
        query = f"after:{start_date} before:{end_date} label:{Config.GMAIL_LABEL_FILTER}"
        
        # Filter for Product Engineering emails only
        if Config.FILTER_PRODUCT_ENGINEERING:
            query += f" (to:{Config.PRODUCT_ENGINEERING_EMAIL} OR cc:{Config.PRODUCT_ENGINEERING_EMAIL})"
        
        # Exclude specific senders
        query += f" -from:donotreply@onescreensolutions.com -from:sage@onescreensolutions.com"
        
        if Config.FILTER_FROM_EMAIL:
            query += f" from:{Config.FILTER_FROM_EMAIL}"
        
        try:
            emails = []
            page_token = None
            
            while True:
                results = self.service.users().messages().list(
                    userId='me',
                    q=query,
                    maxResults=min(max_results - len(emails), 500),
                    pageToken=page_token
                ).execute()
                
                messages = results.get('messages', [])
                
                for msg in messages:
                    email_data = self._get_email_details(msg['id'])
                    if email_data:
                        email_data['message_id'] = msg['id']
                        emails.append(email_data)
                
                page_token = results.get('nextPageToken')
                
                # Stop if we've fetched enough or no more pages
                if not page_token or len(emails) >= max_results:
                    break
            
            # Sort by date sent (newest first - descending order)
            emails.sort(key=lambda x: x.get('date_sent', ''), reverse=True)
            
            print(f"[GmailService] Fetched {len(emails)} emails from {start_date} to {end_date}")
            return emails
            
        except Exception as e:
            print(f"[GmailService] Error fetching emails by date range: {e}")
            return []
    
    def fetch_thread_messages(self, thread_id: str) -> list[dict]:
        """
        Fetch all messages in a thread.
        
        Args:
            thread_id: Gmail thread ID
            
        Returns:
            List of email dictionaries sorted by date (oldest first)
        """
        try:
            # Get thread details
            thread = self.service.users().threads().get(
                userId='me',
                id=thread_id,
                format='full'
            ).execute()
            
            messages = thread.get('messages', [])
            emails = []
            
            for msg in messages:
                email_details = self._get_email_details(msg['id'])
                if email_details:
                    email_details['message_id'] = msg['id']
                    emails.append(email_details)
            
            # Sort by date (oldest first) to get original email first
            emails.sort(key=lambda x: x.get('date_sent', ''))
            
            print(f"[GmailService] Fetched {len(emails)} messages from thread {thread_id}")
            return emails
            
        except Exception as e:
            print(f"[GmailService] Error fetching thread: {e}")
            return []
    
    def _get_email_details(self, message_id: str) -> Optional[dict]:
        """Get full details of a specific email with enhanced metadata."""
        try:
            msg = self.service.users().messages().get(
                userId='me',
                id=message_id,
                format='full'
            ).execute()
            
            headers = {h['name']: h['value'] for h in msg['payload']['headers']}
            
            # Extract body
            body = self._extract_body(msg['payload'])
            
            # Parse date with time
            date_str = headers.get('Date', '')
            try:
                dt = parsedate_to_datetime(date_str)
                date_sent = dt.strftime('%Y-%m-%d %H:%M')
                date_received = dt.strftime('%Y-%m-%d %H:%M')  # Approximate
            except:
                now = datetime.now()
                date_sent = now.strftime('%Y-%m-%d %H:%M')
                date_received = now.strftime('%Y-%m-%d %H:%M')
            
            # Extract all recipients (To + CC fields)
            to_field = headers.get('To', '')
            cc_field = headers.get('Cc', '')
            
            # Combine To and CC recipients
            all_recipients = []
            if to_field:
                all_recipients.append(to_field)
            if cc_field:
                all_recipients.append(cc_field)
            
            recipients_str = ', '.join(all_recipients) if all_recipients else 'Unknown'
            
            return {
                'subject': headers.get('Subject', 'No Subject'),
                'from': headers.get('From', 'Unknown'),
                'to': recipients_str,
                'date': date_sent.split(' ')[0],  # Keep for backward compatibility
                'date_sent': date_sent,
                'date_received': date_received,
                'body': body,
                'thread_id': msg.get('threadId', '')
            }
            
        except Exception as e:
            print(f"[GmailService] Error getting email details: {e}")
            return None
    
    def _extract_body(self, payload: dict) -> str:
        """Extract email body from payload."""
        body = ""
        
        if 'body' in payload and payload['body'].get('data'):
            body = base64.urlsafe_b64decode(payload['body']['data']).decode('utf-8')
        elif 'parts' in payload:
            for part in payload['parts']:
                if part['mimeType'] == 'text/plain':
                    if part['body'].get('data'):
                        body = base64.urlsafe_b64decode(part['body']['data']).decode('utf-8')
                        break
                elif part['mimeType'] == 'multipart/alternative':
                    body = self._extract_body(part)
                    if body:
                        break
        
        return body[:5000]  # Limit body length
    
    def mark_as_read(self, message_id: str) -> bool:
        """Mark an email as read."""
        try:
            self.service.users().messages().modify(
                userId='me',
                id=message_id,
                body={'removeLabelIds': ['UNREAD']}
            ).execute()
            return True
        except Exception as e:
            print(f"[GmailService] Error marking as read: {e}")
            return False
    
    def add_label(self, message_id: str, label_name: str) -> bool:
        """Add a label to an email (for tracking processed emails)."""
        try:
            # Get or create label
            label_id = self._get_or_create_label(label_name)
            if label_id:
                self.service.users().messages().modify(
                    userId='me',
                    id=message_id,
                    body={'addLabelIds': [label_id]}
                ).execute()
                return True
        except Exception as e:
            print(f"[GmailService] Error adding label: {e}")
        return False
    
    def _get_or_create_label(self, label_name: str) -> Optional[str]:
        """Get label ID or create new label."""
        try:
            results = self.service.users().labels().list(userId='me').execute()
            for label in results.get('labels', []):
                if label['name'] == label_name:
                    return label['id']
            
            # Create label if not exists
            label = self.service.users().labels().create(
                userId='me',
                body={'name': label_name}
            ).execute()
            return label['id']
        except:
            return None
