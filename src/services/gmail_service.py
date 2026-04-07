"""
Gmail Service - Handles Gmail API integration for fetching emails.
"""
import os
import base64
import json
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Optional
import requests as _requests
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
        self.service = build('gmail', 'v1', credentials=self.creds, cache_discovery=False)
        self.processed_label = "PROCESSED_BY_AGENT"
    
    def _authenticate(self) -> Credentials:
        """Authenticate with Gmail API using OAuth2."""
        creds = None
        
        # Try loading token from environment variable first (for Render deployment)
        gmail_token_json = os.getenv("GMAIL_TOKEN_JSON")
        gmail_credentials_json = os.getenv("GMAIL_CREDENTIALS_JSON")
        
        if gmail_token_json:
            # Load token from env var (Render deployment)
            token_data = json.loads(gmail_token_json)
            creds = Credentials.from_authorized_user_info(token_data, Config.GMAIL_SCOPES)
        elif os.path.exists(Config.GMAIL_TOKEN_PATH):
            # Load token from file (local development)
            creds = Credentials.from_authorized_user_file(
                Config.GMAIL_TOKEN_PATH, 
                Config.GMAIL_SCOPES
            )
        
        # Refresh or create new credentials
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    session = _requests.Session()
                    session.timeout = 30
                    creds.refresh(Request(session=session))
                    print("[GmailService] Token refreshed successfully ✓")
                    # Save to file if local
                    if not gmail_token_json:
                        with open(Config.GMAIL_TOKEN_PATH, 'w') as token:
                            token.write(creds.to_json())
                except Exception as refresh_error:
                    print(f"[GmailService] Token refresh failed: {refresh_error}")
                    raise RuntimeError(
                        f"Gmail token refresh failed on Render: {refresh_error}. "
                        "Please regenerate token.json locally and update GMAIL_TOKEN_JSON env var."
                    )
            else:
                # Browser flow only works locally
                if gmail_token_json or gmail_credentials_json:
                    raise RuntimeError(
                        "Gmail token expired and cannot re-authenticate on Render. "
                        "Please regenerate token.json locally and update GMAIL_TOKEN_JSON env var."
                    )
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
    
    # AFTER
    def fetch_recent_emails(self, existing_thread_ids: set = None) -> list[dict]:
        """
        Fetch ALL recent emails from inbox (read or unread).
        
        If INITIAL_IMPORT=true: fetches ALL emails from Jan 1, 2026
        If INITIAL_IMPORT=false: fetches ALL emails from last 7 days

        Args:
            existing_thread_ids: Set of thread IDs already in the sheet.
                                 Threads in this set are fetched as stubs only
                                 (no expensive _get_email_details call) so reply
                                 status can still be updated in process_emails.
        
        Returns:
            List of email dictionaries with subject, from, date, body
        """
        from datetime import datetime, timedelta
        
        if existing_thread_ids is None:
            existing_thread_ids = set()

        # Determine start date based on INITIAL_IMPORT setting
        if Config.INITIAL_IMPORT:
            start_date = "2026/01/01"
            print(f"[GmailService] INITIAL_IMPORT mode: fetching ALL from {start_date}")
        else:
            start_date = (datetime.now() - timedelta(days=7)).strftime('%Y/%m/%d')
            print(f"[GmailService] Normal mode: fetching ALL from {start_date}")
        
        # Fetch ALL emails (read or unread) - we'll filter by what's in the sheet later
        query = f"label:{Config.GMAIL_LABEL_FILTER} after:{start_date}"
        
        # Filter for Product Engineering emails only
        if Config.FILTER_PRODUCT_ENGINEERING:
            query += f" (to:{Config.PRODUCT_ENGINEERING_EMAIL} OR cc:{Config.PRODUCT_ENGINEERING_EMAIL})"
        
        # Exclude specific senders from config
        for ignored_email in Config.IGNORED_EMAILS:
            if ignored_email.strip():  # Skip empty entries
                query += f" -from:{ignored_email.strip()}"
        
        if Config.FILTER_FROM_EMAIL:
            query += f" from:{Config.FILTER_FROM_EMAIL}"
        
        try:
            # Paginate through ALL results (get IDs only — fast, no body)
            all_messages = []
            page_token = None
            
            while True:
                results = self.service.users().messages().list(
                    userId='me',
                    q=query,
                    maxResults=500,  # Max allowed by Gmail API per request
                    pageToken=page_token
                ).execute()
                
                messages = results.get('messages', [])
                all_messages.extend(messages)
                
                page_token = results.get('nextPageToken')
                if not page_token:
                    break
                    
                print(f"[GmailService] Fetched {len(all_messages)} emails so far...")
            
            print(f"[GmailService] Total emails found: {len(all_messages)}")
            
            emails = []
            skipped = 0
            for i, msg in enumerate(all_messages):
                thread_id = msg.get('threadId', '')

                # If this thread is already in the sheet, return a lightweight stub.
                # process_emails() will fetch full thread details only when needed for reply updates.
                # This avoids one expensive API call per already-processed email.
                if thread_id and thread_id in existing_thread_ids:
                    emails.append({
                        'subject': '',
                        'from': '',
                        'to': '',
                        'date': '',
                        'date_sent': '',
                        'date_received': '',
                        'body': '',
                        'thread_id': thread_id,
                        'message_id': msg['id'],
                        '_stub': True  # Mark so process_emails knows this is a stub
                    })
                    skipped += 1
                    continue

                email_data = self._get_email_details(msg['id'])
                if email_data:
                    email_data['message_id'] = msg['id']
                    emails.append(email_data)
                
                # Progress update every 50 emails
                if (i + 1) % 50 == 0:
                    print(f"[GmailService] Processed {i + 1}/{len(all_messages)} email details...")
            
            print(f"[GmailService] Skipped {skipped} already-in-sheet threads, fetched details for {len(emails) - skipped} new ones")

            # Sort by date sent (oldest first - ascending order)
            # Stubs have empty date_sent so they sort to front — that's fine,
            # they'll be handled by the "thread already exists" branch and skipped for insert
            emails.sort(key=lambda x: x.get('date_sent', ''), reverse=False)
            
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
        
        # Exclude specific senders from config
        for ignored_email in Config.IGNORED_EMAILS:
            if ignored_email.strip():  # Skip empty entries
                query += f" -from:{ignored_email.strip()}"
        
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
            
            # Sort by date sent (oldest first - ascending order)
            emails.sort(key=lambda x: x.get('date_sent', ''), reverse=False)
            
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
            # Get thread details — format='full' already contains all message data
            thread = self.service.users().threads().get(
                userId='me',
                id=thread_id,
                format='full'
            ).execute()
            
            messages = thread.get('messages', [])
            emails = []
            
            for msg in messages:
                # Parse directly from the already-fetched thread data
                # DO NOT call _get_email_details(msg['id']) again — that makes
                # a separate API call per message and silently drops replies on failure
                try:
                    headers = {h['name']: h['value'] for h in msg['payload']['headers']}
                    
                    # Parse date
                    from email.utils import parsedate_to_datetime
                    from datetime import datetime
                    date_str = headers.get('Date', '')
                    try:
                        dt = parsedate_to_datetime(date_str)
                        date_sent = dt.strftime('%Y-%m-%d')
                    except Exception:
                        date_sent = datetime.now().strftime('%Y-%m-%d')
                    
                    # Extract body from this message's payload
                    body = self._extract_body(msg['payload'])
                    
                    email_details = {
                        'subject': headers.get('Subject', 'No Subject'),
                        'from': headers.get('From', 'Unknown'),
                        'to': headers.get('To', ''),
                        'date': date_sent,
                        'date_sent': date_sent,
                        'date_received': date_sent,
                        'body': body,
                        'thread_id': msg.get('threadId', thread_id),
                        'message_id': msg['id']
                    }
                    emails.append(email_details)
                except Exception as parse_err:
                    print(f"[GmailService] Could not parse message {msg['id']} in thread, skipping: {parse_err}")
                    # Still append a stub so the message COUNT stays accurate
                    emails.append({
                        'subject': '',
                        'from': '',
                        'to': '',
                        'date': '',
                        'date_sent': '',
                        'date_received': '',
                        'body': '',
                        'thread_id': msg.get('threadId', thread_id),
                        'message_id': msg['id']
                    })
            
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
            
            # Parse date (date only, no time)
            date_str = headers.get('Date', '')
            try:
                dt = parsedate_to_datetime(date_str)
                date_sent = dt.strftime('%Y-%m-%d')
                date_received = dt.strftime('%Y-%m-%d')  # Approximate
            except:
                now = datetime.now()
                date_sent = now.strftime('%Y-%m-%d')
                date_received = now.strftime('%Y-%m-%d')
            
            # Extract all recipients (To + CC + BCC fields)
            to_field = headers.get('To', '')
            cc_field = headers.get('Cc', '')
            bcc_field = headers.get('Bcc', '')
            
            # Parse and extract email addresses from To, CC, and BCC fields
            def extract_emails(field_value):
                """Extract clean email addresses from a header field."""
                if not field_value:
                    return []
                
                emails = []
                # Use regex to properly extract emails from complex formats
                import re
                
                # Pattern to match email addresses in angle brackets or standalone
                email_pattern = r'<([^>]+)>|([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})'
                
                matches = re.findall(email_pattern, field_value)
                for match in matches:
                    # match is a tuple: (email_in_brackets, standalone_email)
                    email = match[0] if match[0] else match[1]
                    if email and '@' in email:
                        emails.append(email.strip())
                
                return emails
            
            # Combine all unique recipients from To, CC, and BCC
            all_recipient_emails = []
            all_recipient_emails.extend(extract_emails(to_field))
            all_recipient_emails.extend(extract_emails(cc_field))
            all_recipient_emails.extend(extract_emails(bcc_field))
            
            # Remove duplicates while preserving order
            seen = set()
            unique_recipients = []
            for email in all_recipient_emails:
                email_lower = email.lower()
                if email_lower not in seen:
                    seen.add(email_lower)
                    unique_recipients.append(email)
            
            recipients_str = ', '.join(unique_recipients) if unique_recipients else 'Unknown'
            
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
        """Extract email body from payload, preferring plain text and stripping HTML."""
        body = ""
        html_body = ""
        
        if 'parts' in payload:
            for part in payload['parts']:
                if part['mimeType'] == 'text/plain':
                    if part['body'].get('data'):
                        body = base64.urlsafe_b64decode(part['body']['data']).decode('utf-8')
                        break
                elif part['mimeType'] == 'text/html':
                    if part['body'].get('data'):
                        html_body = base64.urlsafe_b64decode(part['body']['data']).decode('utf-8')
                elif part['mimeType'] == 'multipart/alternative':
                    body = self._extract_body(part)
                    if body:
                        break
        
        # If no plain text found, try the payload body directly
        if not body and 'body' in payload and payload['body'].get('data'):
            raw = base64.urlsafe_b64decode(payload['body']['data']).decode('utf-8')
            # Check if it's HTML
            if '<html' in raw.lower() or '<div' in raw.lower() or '<p' in raw.lower():
                html_body = raw
            else:
                body = raw
        
        # If still no plain text, convert HTML to plain text
        if not body and html_body:
            body = self._html_to_text(html_body)
        
        # Clean up excessive whitespace
        import re
        body = re.sub(r'\n\s*\n\s*\n+', '\n\n', body)  # Collapse 3+ blank lines to 2
        body = re.sub(r'[ \t]+', ' ', body)  # Collapse multiple spaces/tabs
        body = body.strip()
        
        return body[:5000]  # Limit body length
    
    def _html_to_text(self, html: str) -> str:
        """Convert HTML email body to clean plain text."""
        import re
        
        text = html
        
        # Remove style and script blocks entirely
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)
        
        # Replace common block elements with newlines
        text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
        text = re.sub(r'</(p|div|tr|li|h[1-6])>', '\n', text, flags=re.IGNORECASE)
        text = re.sub(r'<(p|div|tr|li|h[1-6])[^>]*>', '\n', text, flags=re.IGNORECASE)
        
        # Replace table cells with spaces
        text = re.sub(r'</(td|th)>', ' ', text, flags=re.IGNORECASE)
        
        # Replace &nbsp; and other HTML entities
        text = text.replace('&nbsp;', ' ')
        text = text.replace('&amp;', '&')
        text = text.replace('&lt;', '<')
        text = text.replace('&gt;', '>')
        text = text.replace('&quot;', '"')
        text = text.replace('&#39;', "'")
        
        # Remove all remaining HTML tags
        text = re.sub(r'<[^>]+>', '', text)
        
        # Decode any remaining HTML entities
        try:
            import html
            text = html.unescape(text)
        except:
            pass
        
        # Clean up whitespace
        text = re.sub(r'\n\s*\n\s*\n+', '\n\n', text)
        text = re.sub(r'[ \t]+', ' ', text)
        lines = [line.strip() for line in text.splitlines()]
        text = '\n'.join(line for line in lines if line)
        
        return text.strip()
    
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