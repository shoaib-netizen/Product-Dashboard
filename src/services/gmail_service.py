"""
Gmail Service - Handles Gmail API integration for fetching emails.
"""
import os
import base64
import json
import concurrent.futures
from datetime import datetime, timezone, timedelta
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

    # ------------------------------------------------------------------
    # NEW: helper that actually enforces a timeout on creds.refresh()
    # ------------------------------------------------------------------
    def _refresh_with_timeout(self, creds, timeout=45):
        """
        Refresh credentials with a hard wall-clock timeout.

        WHY: session.timeout=30 on a requests.Session object is silently
        ignored by google-auth — it only works when passed per-request.
        signal.alarm() only fires on the main thread, so it is useless
        inside the background daemon thread where email processing runs.
        A ThreadPoolExecutor future.result(timeout=N) is the only reliable
        way to enforce a deadline from any thread.
        """
        def _do_refresh():
            # Pass timeout per-request via a custom Session.request wrapper
            session = _requests.Session()
            original_request = session.request
            def request_with_timeout(method, url, **kwargs):
                kwargs.setdefault('timeout', 30)
                return original_request(method, url, **kwargs)
            session.request = request_with_timeout
            creds.refresh(Request(session=session))

        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        future = executor.submit(_do_refresh)
        try:
            future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            executor.shutdown(wait=False)
            raise
        executor.shutdown(wait=False)

    def _authenticate(self) -> Credentials:
        """Authenticate with Gmail API using OAuth2, persisting token to Supabase."""
        creds = None

        # 1. Try loading from Supabase DB first (production — always has latest refreshed token)
        token_data = self._load_token_from_db()
        if token_data:
            creds = Credentials.from_authorized_user_info(token_data, Config.GMAIL_SCOPES)
            print("[GmailService] Token loaded from Supabase ✓")

        # 2. Fallback to GMAIL_TOKEN_JSON env var (first deploy bootstrap)
        elif os.getenv("GMAIL_TOKEN_JSON"):
            token_data = json.loads(os.getenv("GMAIL_TOKEN_JSON"))
            creds = Credentials.from_authorized_user_info(token_data, Config.GMAIL_SCOPES)
            print("[GmailService] Token loaded from GMAIL_TOKEN_JSON env var ✓")

        # 3. Fallback to local token.json file (local development)
        elif os.path.exists(Config.GMAIL_TOKEN_PATH):
            creds = Credentials.from_authorized_user_file(Config.GMAIL_TOKEN_PATH, Config.GMAIL_SCOPES)
            print("[GmailService] Token loaded from token.json file ✓")

        if not creds:
            raise RuntimeError(
                "No Gmail credentials found anywhere (Supabase, GMAIL_TOKEN_JSON env, or token.json)."
            )

        # ------------------------------------------------------------------
        # Proactive refresh: refresh if already expired OR expiring in <5 min.
        # This avoids the harder-to-handle "already fully expired" case and
        # ensures Supabase always has a fresh token for the next run.
        # ------------------------------------------------------------------
        needs_refresh = not creds.valid
        if not needs_refresh and creds.expiry:
            expiry_utc = (
                creds.expiry.replace(tzinfo=timezone.utc)
                if creds.expiry.tzinfo is None
                else creds.expiry
            )
            minutes_left = (expiry_utc - datetime.now(timezone.utc)).total_seconds() / 60
            if minutes_left < 5:
                needs_refresh = True
                print(f"[GmailService] Token expires in {minutes_left:.1f} min — refreshing proactively")

        if needs_refresh:
            if not creds.refresh_token:
                raise RuntimeError(
                    "Gmail token expired and has no refresh_token. "
                    "Regenerate token.json locally and update the oauth_tokens row in Supabase."
                )
            try:
                print("[GmailService] Refreshing token (45s hard timeout)...")
                self._refresh_with_timeout(creds, timeout=45)
                print("[GmailService] Token refreshed successfully ✓")
                # Save refreshed token back to Supabase so next run loads it fresh
                self._save_token_to_db(json.loads(creds.to_json()))
                # Also write locally when running outside Render (local dev)
                if not os.getenv("RENDER") and not os.getenv("GMAIL_TOKEN_JSON"):
                    with open(Config.GMAIL_TOKEN_PATH, 'w') as f:
                        f.write(creds.to_json())
            except concurrent.futures.TimeoutError:
                print("[GmailService] ⚠ Token refresh timed out after 45s (Render network issue)")
                raise RuntimeError(
                    "Gmail token refresh timed out after 45s. "
                    "Render network was slow — will auto-retry on next scheduled run."
                )
            except Exception as e:
                print(f"[GmailService] Token refresh failed: {e}")
                raise RuntimeError(f"Gmail token refresh failed: {e}")

        return creds

    def _load_token_from_db(self):
        """Load OAuth token from Supabase."""
        try:
            from supabase import create_client
            if not Config.SUPABASE_URL or not Config.SUPABASE_KEY:
                return None
            sb = create_client(Config.SUPABASE_URL, Config.SUPABASE_KEY)
            result = sb.table("oauth_tokens").select("token_data").eq("id", "gmail").execute()
            if result.data and result.data[0]["token_data"]:
                data = result.data[0]["token_data"]
                if data != {}:  # Skip empty bootstrap row
                    return data
        except Exception as e:
            print(f"[GmailService] Could not load token from Supabase: {e}")
        return None

    def _save_token_to_db(self, token_data: dict):
        """Save refreshed OAuth token to Supabase."""
        try:
            from supabase import create_client
            if not Config.SUPABASE_URL or not Config.SUPABASE_KEY:
                print("[GmailService] Supabase not configured, skipping DB save")
                return
            sb = create_client(Config.SUPABASE_URL, Config.SUPABASE_KEY)
            sb.table("oauth_tokens").upsert({
                "id": "gmail",
                "token_data": token_data
            }).execute()
            print("[GmailService] Token saved to Supabase ✓")
        except Exception as e:
            print(f"[GmailService] Could not save token to Supabase: {e}")

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
                        '_stub': True
                    })
                    skipped += 1
                    continue

                email_data = self._get_email_details(msg['id'])
                if email_data:
                    email_data['message_id'] = msg['id']
                    emails.append(email_data)
                
                if (i + 1) % 50 == 0:
                    print(f"[GmailService] Processed {i + 1}/{len(all_messages)} email details...")
            
            print(f"[GmailService] Skipped {skipped} already-in-sheet threads, fetched details for {len(emails) - skipped} new ones")

            emails.sort(key=lambda x: x.get('date_sent', ''), reverse=False)
            
            return emails
            
        except Exception as e:
            print(f"[GmailService] Error fetching emails: {e}")
            return []
    
    def fetch_emails_by_date_range(self, start_date: str, end_date: str = None, max_results: int = 500) -> list[dict]:
        """
        Fetch emails within a date range (for historical import).
        """
        from datetime import datetime
        
        if end_date is None:
            end_date = datetime.now().strftime('%Y/%m/%d')
        
        query = f"after:{start_date} before:{end_date} label:{Config.GMAIL_LABEL_FILTER}"
        
        if Config.FILTER_PRODUCT_ENGINEERING:
            query += f" (to:{Config.PRODUCT_ENGINEERING_EMAIL} OR cc:{Config.PRODUCT_ENGINEERING_EMAIL})"
        
        for ignored_email in Config.IGNORED_EMAILS:
            if ignored_email.strip():
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
                
                if not page_token or len(emails) >= max_results:
                    break
            
            emails.sort(key=lambda x: x.get('date_sent', ''), reverse=False)
            
            print(f"[GmailService] Fetched {len(emails)} emails from {start_date} to {end_date}")
            return emails
            
        except Exception as e:
            print(f"[GmailService] Error fetching emails by date range: {e}")
            return []
    
    def fetch_thread_messages(self, thread_id: str) -> list[dict]:
        """
        Fetch all messages in a thread.
        """
        try:
            thread = self.service.users().threads().get(
                userId='me',
                id=thread_id,
                format='full'
            ).execute()
            
            messages = thread.get('messages', [])
            emails = []
            
            for msg in messages:
                try:
                    headers = {h['name']: h['value'] for h in msg['payload']['headers']}
                    
                    from email.utils import parsedate_to_datetime
                    from datetime import datetime
                    date_str = headers.get('Date', '')
                    try:
                        dt = parsedate_to_datetime(date_str)
                        date_sent = dt.strftime('%Y-%m-%d')
                    except Exception:
                        date_sent = datetime.now().strftime('%Y-%m-%d')
                    
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
            
            body = self._extract_body(msg['payload'])
            
            date_str = headers.get('Date', '')
            try:
                dt = parsedate_to_datetime(date_str)
                date_sent = dt.strftime('%Y-%m-%d')
                date_received = dt.strftime('%Y-%m-%d')
            except:
                now = datetime.now()
                date_sent = now.strftime('%Y-%m-%d')
                date_received = now.strftime('%Y-%m-%d')
            
            to_field = headers.get('To', '')
            cc_field = headers.get('Cc', '')
            bcc_field = headers.get('Bcc', '')
            
            def extract_emails(field_value):
                """Extract clean email addresses from a header field."""
                if not field_value:
                    return []
                emails = []
                import re
                email_pattern = r'<([^>]+)>|([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})'
                matches = re.findall(email_pattern, field_value)
                for match in matches:
                    email = match[0] if match[0] else match[1]
                    if email and '@' in email:
                        emails.append(email.strip())
                return emails
            
            all_recipient_emails = []
            all_recipient_emails.extend(extract_emails(to_field))
            all_recipient_emails.extend(extract_emails(cc_field))
            all_recipient_emails.extend(extract_emails(bcc_field))
            
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
                'date': date_sent.split(' ')[0],
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
        
        if not body and 'body' in payload and payload['body'].get('data'):
            raw = base64.urlsafe_b64decode(payload['body']['data']).decode('utf-8')
            if '<html' in raw.lower() or '<div' in raw.lower() or '<p' in raw.lower():
                html_body = raw
            else:
                body = raw
        
        if not body and html_body:
            body = self._html_to_text(html_body)
        
        import re
        body = re.sub(r'\n\s*\n\s*\n+', '\n\n', body)
        body = re.sub(r'[ \t]+', ' ', body)
        body = body.strip()
        
        return body[:5000]
    
    def _html_to_text(self, html: str) -> str:
        """Convert HTML email body to clean plain text."""
        import re
        
        text = html
        
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)
        
        text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
        text = re.sub(r'</(p|div|tr|li|h[1-6])>', '\n', text, flags=re.IGNORECASE)
        text = re.sub(r'<(p|div|tr|li|h[1-6])[^>]*>', '\n', text, flags=re.IGNORECASE)
        
        text = re.sub(r'</(td|th)>', ' ', text, flags=re.IGNORECASE)
        
        text = text.replace('&nbsp;', ' ')
        text = text.replace('&amp;', '&')
        text = text.replace('&lt;', '<')
        text = text.replace('&gt;', '>')
        text = text.replace('&quot;', '"')
        text = text.replace('&#39;', "'")
        
        text = re.sub(r'<[^>]+>', '', text)
        
        try:
            import html
            text = html.unescape(text)
        except:
            pass
        
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
            
            label = self.service.users().labels().create(
                userId='me',
                body={'name': label_name}
            ).execute()
            return label['id']
        except:
            return None