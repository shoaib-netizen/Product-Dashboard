"""
Google Chat Service - Handles Google Chat API integration for fetching
messages from a space.

This service authenticates using OAuth2 on behalf of a user and supports
fetching messages from a specified Google Chat space.  Only messages
authored by users in ALLOWED_USER_IDS will be returned.  Messages can be
fetched either from a configurable date window (last seven days vs. full
import) or from explicit start and end dates.  Each returned message is
normalized into a simple dictionary containing fields required for sheet
insertion.
"""

from __future__ import annotations

import os
import json
from datetime import datetime, timedelta
from typing import List, Dict, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from config import Config

try:
    # Python 3.9+ provides the zoneinfo module in the standard library.
    from zoneinfo import ZoneInfo  # type: ignore
except ImportError:
    # zoneinfo is not available on Python <3.9; fallback to UTC
    ZoneInfo = None  # type: ignore


# ---------------------------------------------------------------------------
# Hardcoded user ID → display name mapping.
# The Google Chat API does not return displayName for space members with
# this OAuth setup, so we match by numeric user ID instead.
# To add or remove a person, simply add/remove their entry here.
# ---------------------------------------------------------------------------
def _load_allowed_users() -> dict:
    raw = os.getenv("CHAT_ALLOWED_USERS", "")
    result = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if ":" in entry:
            user_id, name = entry.split(":", 1)
            result[user_id.strip()] = name.strip()
    return result

ALLOWED_USER_IDS = _load_allowed_users()


class GoogleChatService:
    """Service for interacting with the Google Chat API."""

    def __init__(self):
        """Authenticate and build the Chat service."""
        self.creds = self._authenticate()
        self.service = build("chat", "v1", credentials=self.creds, cache_discovery=False)

    def _authenticate(self) -> Credentials:
        """Authenticate with the Chat API using OAuth2."""
        creds: Optional[Credentials] = None

        # Attempt to load token from environment variable (Render deployment)
        chat_token_json = os.getenv("CHAT_TOKEN_JSON")
        # Use shared env variable for credentials if provided
        chat_credentials_json = os.getenv("CHAT_CREDENTIALS_JSON") or os.getenv("GMAIL_CREDENTIALS_JSON")

        # 1. Load token from env var if available
        if chat_token_json:
            try:
                token_data = json.loads(chat_token_json)
                creds = Credentials.from_authorized_user_info(token_data, Config.CHAT_SCOPES)
            except Exception:
                creds = None

        # 2. Load token from local file if available
        if not creds and os.path.exists(Config.CHAT_TOKEN_PATH):
            try:
                creds = Credentials.from_authorized_user_file(Config.CHAT_TOKEN_PATH, Config.CHAT_SCOPES)
            except Exception:
                creds = None

        # 3. If no valid credentials or token is expired, refresh or run flow
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                # Attempt to refresh the token
                creds.refresh(Request())
                # Always persist refreshed token to local file so next run
                # doesn't need to re-authenticate from scratch
                try:
                    with open(Config.CHAT_TOKEN_PATH, "w") as token_file:
                        token_file.write(creds.to_json())
                except Exception:
                    pass
            else:
                # If running on a hosted environment without credentials we
                # cannot perform the interactive flow.  Inform the caller.
                if chat_token_json or chat_credentials_json:
                    raise RuntimeError(
                        "Chat token expired and cannot re-authenticate on this platform. "
                        "Please regenerate chat_token.json locally and set CHAT_TOKEN_JSON."
                    )
                # Ensure the OAuth client secrets file exists
                if not os.path.exists(Config.CHAT_CREDENTIALS_PATH):
                    raise FileNotFoundError(
                        f"Chat credentials not found at {Config.CHAT_CREDENTIALS_PATH}. "
                        "Please download your OAuth client JSON from Google Cloud Console."
                    )
                # Run the local web flow to obtain a new token
                flow = InstalledAppFlow.from_client_secrets_file(
                    Config.CHAT_CREDENTIALS_PATH,
                    scopes=Config.CHAT_SCOPES,
                )
                creds = flow.run_local_server(port=0)
                # Save the new token for subsequent runs
                with open(Config.CHAT_TOKEN_PATH, "w") as token_file:
                    token_file.write(creds.to_json())

        if not creds:
            raise RuntimeError("Unable to obtain valid credentials for Google Chat API")

        return creds

    def _build_time_filter(self, start_date: str, end_date: Optional[str] = None) -> str:
        """Construct a filter expression for createTime based on start and end dates.

        Args:
            start_date: A date string in YYYY-MM-DD format.
            end_date: An optional end date in YYYY-MM-DD format.  If provided
                messages created after start_date AND before end_date will be
                returned.

        Returns:
            A filter string understood by the Chat API.
        """
        def to_rfc3339(date_str: str, end: bool = False) -> str:
            # Convert YYYY-MM-DD to RFC3339 with timezone Z.  If end=True set
            # time to end of day.
            if not date_str:
                return ""
            try:
                dt = datetime.strptime(date_str, "%Y-%m-%d")
            except ValueError:
                # Accept YYYY/MM/DD as well
                dt = datetime.strptime(date_str, "%Y/%m/%d")
            if end:
                dt = dt.replace(hour=23, minute=59, second=59)
            # Represent in UTC; Chat API accepts Z suffix
            return dt.isoformat(timespec="seconds") + "Z"

        start_ts = to_rfc3339(start_date, end=False)
        filter_parts = [f'createTime > "{start_ts}"'] if start_ts else []
        if end_date:
            end_ts = to_rfc3339(end_date, end=True)
            filter_parts.append(f'createTime < "{end_ts}"')
        return " AND ".join(filter_parts)

    def _is_allowed_sender(self, sender: Dict) -> bool:
        """Return True if the sender's user ID is in ALLOWED_USER_IDS.

        Args:
            sender: The sender field from a Chat message.

        Returns:
            True if the sender is one of the allowed users, False otherwise.
        """
        user_id = sender.get("name", "")
        return user_id in ALLOWED_USER_IDS

    def _get_sender_name(self, sender: Dict) -> str:
        """Return the friendly display name for a sender.

        Falls back to the raw user ID if not found in ALLOWED_USER_IDS.

        Args:
            sender: The sender field from a Chat message.

        Returns:
            A human-readable name string.
        """
        user_id = sender.get("name", "Unknown")
        return ALLOWED_USER_IDS.get(user_id, user_id)
    def fetch_replied_message_ids(self) -> set:
        """Return message IDs that have been directly replied to by non-allowed users.

        Uses quotedMessageMetadata to detect when someone (Faizan, Abdullah, etc.)
        directly quoted/replied to a specific message from an allowed sender.
        """
        replied_message_ids = set()
        next_page = None

        while True:
            try:
                resp = (
                    self.service.spaces()
                    .messages()
                    .list(
                        parent=f"spaces/{Config.CHAT_SPACE_ID}",
                        pageSize=100,
                        pageToken=next_page,
                        filter='createTime > "2020-01-01T00:00:00Z"',
                        orderBy="createTime ASC",
                        showDeleted=False,
                    )
                    .execute()
                )
            except Exception as e:
                print(f"[ChatService] Error fetching reply data: {e}")
                break

            for msg in resp.get("messages", []):
                sender_id = msg.get("sender", {}).get("name", "")

                # Only care about replies from non-allowed users (Faizan, Abdullah etc.)
                if sender_id in ALLOWED_USER_IDS:
                    continue

                # Check if this message is a direct reply/quote to another message
                quoted = msg.get("quotedMessageMetadata", {})
                quoted_msg_id = quoted.get("name", "")  # e.g. "spaces/xxx/messages/yyy"
                if quoted_msg_id:
                    replied_message_ids.add(quoted_msg_id)

            next_page = resp.get("nextPageToken")
            if not next_page:
                break

        return replied_message_ids
    
    def fetch_messages(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> List[Dict[str, str]]:
        """Fetch messages from the configured Chat space.

        Args:
            start_date: Optional start date (YYYY-MM-DD).  If omitted the
                default is determined by ``Config.CHAT_INITIAL_IMPORT`` (all
                history vs. last seven days).
            end_date: Optional end date (YYYY-MM-DD).  If omitted the current
                date is assumed.

        Returns:
            A list of dictionaries representing messages.  Each dictionary
            contains the following keys:

            - ``message_id``: unique identifier of the message
            - ``sender_name``: friendly name from ALLOWED_USER_IDS
            - ``sender_id``: Chat API resource name of the sender
            - ``text``: the plain text content of the message
            - ``date``: date portion (YYYY-MM-DD) in the user's time zone
            - ``time``: time portion (HH:MM) in the user's time zone
        """
        if not Config.CHAT_SPACE_ID:
            # No space configured; nothing to fetch
            return []

        # Determine default start date
        if not start_date:
            if Config.CHAT_INITIAL_IMPORT:
                start_date = "2020-01-01"
            else:
                # Last 7 days
                start_date = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")

        # Build filter expression
        filter_expr = self._build_time_filter(start_date, end_date)

        messages: List[Dict[str, str]] = []
        next_page: Optional[str] = None

        # Pagination: continue until no nextPageToken or results exhausted
        while True:
            try:
                resp = (
                    self.service.spaces()
                    .messages()
                    .list(
                        parent=f"spaces/{Config.CHAT_SPACE_ID}",
                        pageSize=100,
                        pageToken=next_page,
                        filter=filter_expr or None,
                        orderBy="createTime ASC",
                        showDeleted=False,
                    )
                    .execute()
                )
            except Exception as e:
                print(f"[ChatService] Error fetching messages: {e}")
                break

            for msg in resp.get("messages", []):
                sender = msg.get("sender", {})

                # Skip messages from users not in our allowed list
                if not self._is_allowed_sender(sender):
                    continue

                message_id = msg.get("name", "")
                text = msg.get("text", "") or msg.get("argumentText", "") or msg.get("fallbackText", "")
                # Skip empty messages (system events, attachments only, etc.)
                if not text:
                    continue

                # Parse timestamps
                create_time = msg.get("createTime", "")
                try:
                    dt = datetime.fromisoformat(create_time.replace("Z", "+00:00"))
                except Exception:
                    dt = None

                if dt:
                    # Convert to user's timezone if available
                    if ZoneInfo:
                        try:
                            tz = ZoneInfo("Asia/Karachi")
                            dt_local = dt.astimezone(tz)
                        except Exception:
                            dt_local = dt
                    else:
                        dt_local = dt
                    date_str = dt_local.strftime("%Y-%m-%d")
                    time_str = dt_local.strftime("%H:%M")
                else:
                    # Fallback to current time
                    now = datetime.now()
                    date_str = now.strftime("%Y-%m-%d")
                    time_str = now.strftime("%H:%M")

                messages.append(
                    {
                        "message_id": message_id,
                        "sender_name": self._get_sender_name(sender),
                        "sender_id": sender.get("name", "Unknown"),
                        "text": text,
                        "date": date_str,
                        "time": time_str,
                        "thread_name": msg.get("thread", {}).get("name", ""),
                    }
                )

            # Next page
            next_page = resp.get("nextPageToken")
            if not next_page:
                break

        # Sort messages chronologically ascending
        messages.sort(key=lambda m: (m["date"], m["time"]))
        return messages