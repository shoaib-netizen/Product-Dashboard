"""
Chat Sheets Service - Handles storing Google Chat message data in a
dedicated worksheet.

This service is analogous to ``GoogleSheetsService`` but tailored for
Google Chat messages.  It uses a service account to authenticate with
Google Sheets and manages a secondary worksheet (specified via
``Config.CHAT_SHEET_NAME``) where chat messages are appended.  Each
message is uniquely identified by its ``message_id`` and duplicate
entries are automatically skipped.

The sheet columns are:

* ``SN`` – Serial number (1-based index for display)
* ``Message ID`` – Unique identifier returned by the Chat API
* ``Sender Name`` – Display name of the user who sent the message
* ``Sender Email`` – Email address mapped from ``Config.CHAT_USER_EMAILS`` (if
  known) otherwise left blank
* ``Message`` – The plain text content of the chat message
* ``Date`` – Date the message was sent (YYYY‑MM‑DD) in Asia/Karachi
* ``Time`` – Local time the message was sent (HH:MM) in Asia/Karachi
"""

from __future__ import annotations

import os
from typing import List, Dict, Optional

import gspread
from google.oauth2.service_account import Credentials

from config import Config


class ChatSheetsService:
    """Service for interacting with Google Sheets for Chat messages."""

    # Define the headers for the chat messages sheet
    #
    # A ninth column, ``Replied By``, has been added to track which users
    # responded to the original message.  This value is a comma‑separated list
    # of names or user identifiers of anyone who quoted/replied to the
    # message.  When no reply exists, the cell will remain blank.  The
    # ``Status`` column is still used to indicate whether at least one reply
    # exists (``Replied`` vs. ``Not Replied``).
    HEADERS = [
        "SN",
        "Message ID",
        "Sender Name",
        "Sender Email",
        "Message",
        "Date",
        "Time",
        "Status",
        "Replied By",
    ]

    def __init__(self):
        """Authenticate and initialize the worksheet."""
        self.creds = self._authenticate()
        self.client = gspread.authorize(self.creds)
        self._is_new_sheet = False
        self.sheet = self._get_sheet()
        self._ensure_headers()
        if self._is_new_sheet:
            self._format_as_table()

    def _authenticate(self) -> Credentials:
        """Authenticate with Google Sheets using a service account."""
        creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
        if creds_json:
            import json
            creds_dict = json.loads(creds_json)
            return Credentials.from_service_account_info(
                creds_dict,
                scopes=Config.SHEETS_SCOPES,
            )
        else:
            creds_path = os.getenv("GOOGLE_SERVICE_ACCOUNT_PATH", "service_account.json")
            if not os.path.exists(creds_path):
                raise FileNotFoundError(
                    f"Service account credentials not found at {creds_path}. "
                    "Please download from Google Cloud Console."
                )
            return Credentials.from_service_account_file(
                creds_path,
                scopes=Config.SHEETS_SCOPES,
            )

    def _get_sheet(self) -> gspread.Worksheet:
        """Retrieve or create the worksheet for Chat messages."""
        spreadsheet = self.client.open_by_key(Config.GOOGLE_SHEET_ID)
        try:
            sheet = spreadsheet.worksheet(Config.CHAT_SHEET_NAME)
            self._is_new_sheet = False
            return sheet
        except gspread.WorksheetNotFound:
            self._is_new_sheet = True
            return spreadsheet.add_worksheet(
                title=Config.CHAT_SHEET_NAME,
                rows=1000,
                cols=len(self.HEADERS),
            )

    def _ensure_headers(self) -> None:
        """Ensure that the header row exists and is formatted."""
        try:
            first_row = self.sheet.row_values(1)
            if not first_row or first_row != self.HEADERS:
                # Update header range to include the new "Replied By" column (column I)
                end_col = chr(ord('A') + len(self.HEADERS) - 1)
                self.sheet.update([self.HEADERS], f'A1:{end_col}1')

            # Apply header formatting: professional blue background, white bold text
            end_col = chr(ord('A') + len(self.HEADERS) - 1)
            self.sheet.format(f'A1:{end_col}1', {
                'backgroundColor': {'red': 0.27, 'green': 0.51, 'blue': 0.71},
                'textFormat': {'bold': True, 'foregroundColor': {'red': 1.0, 'green': 1.0, 'blue': 1.0}, 'fontSize': 11},
                'horizontalAlignment': 'CENTER',
                'verticalAlignment': 'MIDDLE',
            })
            # Freeze header row
            self.sheet.freeze(rows=1)
            # Wrap text in Replied By column so multiple names stay inside cell
            try:
                self.sheet.spreadsheet.batch_update({
                    "requests": [{
                        "repeatCell": {
                            "range": {
                                "sheetId": self.sheet.id,
                                "startRowIndex": 1,
                                "endRowIndex": 1000,
                                "startColumnIndex": 8,  # Column I
                                "endColumnIndex": 9,
                            },
                            "cell": {
                                "userEnteredFormat": {
                                    "wrapStrategy": "WRAP",
                                    "verticalAlignment": "TOP",
                                }
                            },
                            "fields": "userEnteredFormat(wrapStrategy,verticalAlignment)",
                        }
                    }]
                })
            except Exception:
                pass

            # Apply filter over entire range (including the Replied By column)
            try:
                self.sheet.spreadsheet.batch_update({
                    "requests": [{
                        "setBasicFilter": {
                            "filter": {
                                "range": {
                                    "sheetId": self.sheet.id,
                                    "startRowIndex": 0,
                                    "endRowIndex": 1000,
                                    "startColumnIndex": 0,
                                    "endColumnIndex": len(self.HEADERS),
                                }
                            }
                        }
                    }]
                })
            except Exception:
                # It's okay if the filter already exists
                pass
        except Exception as e:
            print(f"[ChatSheetsService] Header setup error: {e}")
            self.sheet.update([self.HEADERS], 'A1:H1')

    def _format_as_table(self) -> None:
        """Set column widths and borders for a professional table appearance."""
        try:
            column_widths = [
                ("A", 50),   # SN
                ("B", 200),  # Message ID
                ("C", 200),  # Sender Name
                ("D", 250),  # Sender Email
                ("E", 400),  # Message
                ("F", 130),  # Date
                ("G", 80),   # Time
                ("H", 130),  # Status
                ("I", 450),  # Replied By
            ]
            requests = []
            for letter, width in column_widths:
                idx = ord(letter) - ord('A')
                requests.append({
                    "updateDimensionProperties": {
                        "range": {
                            "sheetId": self.sheet.id,
                            "dimension": "COLUMNS",
                            "startIndex": idx,
                            "endIndex": idx + 1,
                        },
                        "properties": {"pixelSize": width},
                        "fields": "pixelSize",
                    }
                })
            # Apply borders
            requests.append({
                "updateBorders": {
                    "range": {
                        "sheetId": self.sheet.id,
                        "startRowIndex": 0,
                        "endRowIndex": 1000,
                        "startColumnIndex": 0,
                "endColumnIndex": len(self.HEADERS),
                    },
                    "top": {"style": "SOLID", "width": 1, "color": {"red": 0.8, "green": 0.8, "blue": 0.8}},
                    "bottom": {"style": "SOLID", "width": 1, "color": {"red": 0.8, "green": 0.8, "blue": 0.8}},
                    "left": {"style": "SOLID", "width": 1, "color": {"red": 0.8, "green": 0.8, "blue": 0.8}},
                    "right": {"style": "SOLID", "width": 1, "color": {"red": 0.8, "green": 0.8, "blue": 0.8}},
                    "innerHorizontal": {"style": "SOLID", "width": 1, "color": {"red": 0.9, "green": 0.9, "blue": 0.9}},
                    "innerVertical": {"style": "SOLID", "width": 1, "color": {"red": 0.9, "green": 0.9, "blue": 0.9}},
                }
            })
            self.sheet.spreadsheet.batch_update({"requests": requests})
        except Exception as e:
            # Formatting is optional; log and continue
            print(f"[ChatSheetsService] Table formatting error: {e}")

    def _get_existing_message_ids(self) -> set[str]:
        """Return a set of message IDs already present in the sheet."""
        try:
            # Column B (Message ID) values excluding header
            ids = self.sheet.col_values(2)[1:]
            return set(id_val for id_val in ids if id_val)
        except Exception as e:
            print(f"[ChatSheetsService] Could not fetch existing message IDs: {e}")
            return set()

    def append_messages(self, messages: List[Dict[str, str]], reply_map: Optional[Dict[str, set]] = None) -> int:
        """Append new chat messages to the sheet, skipping duplicates.

        Args:
            messages: List of message dictionaries produced by
                ``GoogleChatService.fetch_messages``.
            reply_map: Mapping of message IDs to sets of reply sender names.  If
                provided, this will be used to populate the ``Status`` and
                ``Replied By`` columns.

        Returns:
            The number of rows appended to the sheet.
        """
        if not messages:
            return 0

        # Default to empty mapping if none provided
        if reply_map is None:
            reply_map = {}

        existing_ids = self._get_existing_message_ids()
        rows_to_add: List[List[str]] = []

        # Determine current SN by counting existing rows (excluding header)
        try:
            current_rows = len(self.sheet.get_all_values())
        except Exception:
            current_rows = 1  # Only header
        sn_counter = current_rows

        # Build rows for insertion
        for msg in messages:
            msg_id = msg.get("message_id")
            if not msg_id or msg_id in existing_ids:
                continue
            sender_name = msg.get("sender_name", "")
            # Hardcoded name → email mapping
            EMAIL_MAP = {
                "Talha Khalid": "talha@onescreensolutions.com",
                "Sijjil Shabbir": "sijjil@onescreensolutions.com",
                "Junaid": "junaid@onescreensolutions.com",
                "David Khan": "david@onescreensolutions.com",
                "Ali Sheikh": "alis@onescreensolutions.com",
            }
            sender_email = EMAIL_MAP.get(sender_name, "")
            # Determine status and list of reply names
            reply_names_set = reply_map.get(msg_id, set())
            status = "Replied" if reply_names_set else "Not Replied"
            # Convert set of names to a comma‑separated string in a deterministic order
            replied_by = ", ".join(sorted(reply_names_set)) if reply_names_set else ""
            row = [
                str(sn_counter),       # SN
                msg_id or "",          # Message ID
                sender_name or "",     # Sender Name
                sender_email,          # Sender Email
                msg.get("text", ""),   # Message
                msg.get("date", ""),   # Date
                msg.get("time", ""),   # Time
                status,                # Status (Replied / Not Replied)
                replied_by,            # Replied By (comma‑separated names)
            ]
            rows_to_add.append(row)
            sn_counter += 1

        if not rows_to_add:
            return 0

        try:
            self.sheet.append_rows(rows_to_add, value_input_option="USER_ENTERED")
            # Add dropdown validation to Status column (H) for new rows
            start_row = current_rows + 1
            end_row = start_row + len(rows_to_add) - 1
            self._add_status_dropdown(start_row, end_row)
            self._apply_status_colors(start_row, end_row, rows_to_add)
            self._apply_replied_by_wrap(start_row, end_row)
        except Exception as e:
            print(f"[ChatSheetsService] Error appending rows: {e}")
            return 0
        return len(rows_to_add)

    def _add_status_dropdown(self, start_row: int, end_row: int) -> None:
        """Add Replied / Not Replied dropdown to Status column for given rows."""
        try:
            self.sheet.spreadsheet.batch_update({
                "requests": [{
                    "setDataValidation": {
                        "range": {
                            "sheetId": self.sheet.id,
                            "startRowIndex": start_row - 1,
                            "endRowIndex": end_row,
                            "startColumnIndex": 7,  # Column H
                            "endColumnIndex": 8,
                        },
                        "rule": {
                            "condition": {
                                "type": "ONE_OF_LIST",
                                "values": [
                                    {"userEnteredValue": "Replied"},
                                    {"userEnteredValue": "Not Replied"},
                                ],
                            },
                            "showCustomUi": True,
                            "strict": True,
                        }
                    }
                }]
            })
        except Exception as e:
            print(f"[ChatSheetsService] Dropdown error: {e}")

    def _apply_status_colors(self, start_row: int, end_row: int, rows_data: list) -> None:
        """Color Status cells: green for Replied, yellow for Not Replied."""
        requests = []
        for i, row in enumerate(rows_data):
            status = row[7] if len(row) > 7 else ""
            sheet_row = start_row + i
            if status == "Replied":
                bg = {"red": 0.2, "green": 0.78, "blue": 0.35}
                fg = {"red": 1.0, "green": 1.0, "blue": 1.0}
            else:
                bg = {"red": 1.0, "green": 0.84, "blue": 0.0}
                fg = {"red": 0.0, "green": 0.0, "blue": 0.0}
            requests.append({
                "repeatCell": {
                    "range": {
                        "sheetId": self.sheet.id,
                        "startRowIndex": sheet_row - 1,
                        "endRowIndex": sheet_row,
                        "startColumnIndex": 7,
                        "endColumnIndex": 8,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": bg,
                            "textFormat": {"foregroundColor": fg, "bold": True},
                            "horizontalAlignment": "CENTER",
                        }
                    },
                    "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment)",
                }
            })
        if requests:
            try:
                self.sheet.spreadsheet.batch_update({"requests": requests})
            except Exception as e:
                print(f"[ChatSheetsService] Color formatting error: {e}")


    def _apply_replied_by_wrap(self, start_row: int, end_row: int) -> None:
        """Enable text wrap on Replied By column so multiple names stay inside cell."""
        try:
            self.sheet.spreadsheet.batch_update({
                "requests": [{
                    "repeatCell": {
                        "range": {
                            "sheetId": self.sheet.id,
                            "startRowIndex": start_row - 1,
                            "endRowIndex": end_row,
                            "startColumnIndex": 8,  # Column I
                            "endColumnIndex": 9,
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "wrapStrategy": "WRAP",
                                "verticalAlignment": "TOP",
                            }
                        },
                        "fields": "userEnteredFormat(wrapStrategy,verticalAlignment)",
                    }
                }]
            })
        except Exception as e:
            print(f"[ChatSheetsService] Wrap formatting error: {e}")

    def update_reply_statuses(self, reply_map: Dict[str, set]) -> int:
        """Update Status and Replied By columns for existing rows.

        Args:
            reply_map: Mapping of message IDs to sets of names that replied to that message.

        Returns:
            The number of rows updated.
        """
        if not reply_map:
            return 0

        try:
            msg_ids = self.sheet.col_values(2)[1:]       # Column B, skip header
            statuses = self.sheet.col_values(8)[1:]      # Column H, skip header
            replied_bys = self.sheet.col_values(9)[1:]   # Column I, skip header
        except Exception as e:
            print(f"[ChatSheetsService] Could not read sheet: {e}")
            return 0

        # Pad shorter lists so zip doesn't stop early on rows missing column I
        max_len = len(msg_ids)
        statuses = statuses + [""] * (max_len - len(statuses))
        replied_bys = replied_bys + [""] * (max_len - len(replied_bys))

        updates: List[Dict[str, any]] = []
        updated_count = 0
        for row_index, (msg_id, status, current_replied_by) in enumerate(zip(msg_ids, statuses, replied_bys), start=2):
            if not msg_id or msg_id not in reply_map:
                continue
            # Determine new status and reply string
            names_set = reply_map.get(msg_id, set())
            new_status = "Replied" if names_set else "Not Replied"
            new_replied_by = ", ".join(sorted(names_set)) if names_set else ""
            row_updates = []
            # Update status if changed
            if status != new_status:
                row_updates.append({
                    "range": f"'{self.sheet.title}'!H{row_index}",
                    "values": [[new_status]],
                })
            # Update replied by if changed
            if current_replied_by != new_replied_by:
                row_updates.append({
                    "range": f"'{self.sheet.title}'!I{row_index}",
                    "values": [[new_replied_by]],
                })
            if row_updates:
                updates.extend(row_updates)
                updated_count += 1

        if not updates:
            return 0

        try:
            self.sheet.spreadsheet.values_batch_update({
                "valueInputOption": "USER_ENTERED",
                "data": updates,
            })
        except Exception as e:
            print(f"[ChatSheetsService] Error updating reply statuses: {e}")
            return 0

        # Re-apply status colours to updated rows
        try:
            # Determine which rows had their Status updated (i.e., range targets column H)
            colored_rows: set[int] = set()
            for upd in updates:
                rng = upd["range"]
                # Extract column letter and row number (e.g. 'Sheet'!H5)
                cell_ref = rng.split("!")[-1]
                col_letter = cell_ref[0]
                row_num = int(cell_ref[1:])
                if col_letter == "H":
                    colored_rows.add(row_num)
            for row_num in colored_rows:
                # Determine new status for this row
                idx = row_num - 2  # msg_ids list index
                msg_id = msg_ids[idx] if idx < len(msg_ids) else ""
                status = "Replied" if msg_id in reply_map and reply_map.get(msg_id) else "Not Replied"
                row_data = [[None]*7 + [status]]
                self._apply_status_colors(row_num, row_num, row_data)
        except Exception:
            pass

        return updated_count