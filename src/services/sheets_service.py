"""
Google Sheets Service - Handles storing task data in Google Sheets.
"""
import os
import gspread
from google.oauth2.service_account import Credentials
from typing import Optional

from config import Config
from src.agents.email_parser_agent import TaskData


class GoogleSheetsService:
    """
    Service for interacting with Google Sheets API.
    
    Handles:
    - Authentication (Service Account)
    - Appending task data to sheets
    - Reading existing data
    - Managing sheet structure
    """
    
    # Expected headers in the sheet - Product Engineering Team Format
    HEADERS = [
        "SN",
        "Thread ID",
        "Email Subject",
        "Sender Name",
        "Sender Email",
        "Date Sent",
        "Email Summary",
        "Team Origin",
        "Origin Type",
        "Reply Status",
        "Replied By",
        "Reply Date",
        "Reply Summary",
        "Task Status"
    ]
    
    def __init__(self):
        """Initialize Google Sheets service."""
        self.creds = self._authenticate()
        self.client = gspread.authorize(self.creds)
        self.sheet = self._get_sheet()
        self._ensure_headers()
        self._format_as_table()   # <-- important
    
    def _authenticate(self) -> Credentials:
        """Authenticate with Google Sheets using service account."""
        # For Render deployment, credentials can be from env var
        creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
        
        if creds_json:
            import json
            creds_dict = json.loads(creds_json)
            return Credentials.from_service_account_info(
                creds_dict,
                scopes=Config.SHEETS_SCOPES
            )
        else:
            # Local development - use file
            creds_path = os.getenv("GOOGLE_SERVICE_ACCOUNT_PATH", "service_account.json")
            if not os.path.exists(creds_path):
                raise FileNotFoundError(
                    f"Service account credentials not found at {creds_path}. "
                    "Please download from Google Cloud Console."
                )
            return Credentials.from_service_account_file(
                creds_path,
                scopes=Config.SHEETS_SCOPES
            )
    
    def _get_sheet(self) -> gspread.Worksheet:
        """Get the worksheet to write data to."""
        spreadsheet = self.client.open_by_key(Config.GOOGLE_SHEET_ID)
        
        try:
            return spreadsheet.worksheet(Config.GOOGLE_SHEET_NAME)
        except gspread.WorksheetNotFound:
            # Create worksheet if not exists
            return spreadsheet.add_worksheet(
                title=Config.GOOGLE_SHEET_NAME,
                rows=1000,
                cols=14
            )
    
    def _ensure_headers(self):
        """Ensure headers exist in the first row with proper formatting."""
        try:
            first_row = self.sheet.row_values(1)
            if not first_row or first_row != self.HEADERS:
                # Update headers
                self.sheet.update([self.HEADERS], 'A1:N1')
            
            # Always apply header formatting
            self.sheet.format('A1:N1', {
                'backgroundColor': {'red': 0.27, 'green': 0.51, 'blue': 0.71},  # Professional blue
                'textFormat': {'bold': True, 'foregroundColor': {'red': 1.0, 'green': 1.0, 'blue': 1.0}, 'fontSize': 11},
                'horizontalAlignment': 'CENTER',
                'verticalAlignment': 'MIDDLE'
            })
            
            # Freeze header row
            self.sheet.freeze(rows=1)
            
            # Add filter to header row for easy filtering by date, status, etc.
            try:
                self.sheet.spreadsheet.batch_update({
                    "requests": [{
                        "setBasicFilter": {
                            "filter": {
                                "range": {
                                    "sheetId": self.sheet.id,
                                    "startRowIndex": 0,
                                    "endRowIndex": 1000,  # Cover up to 1000 rows
                                    "startColumnIndex": 0,
                                    "endColumnIndex": 14   # All 14 columns (A-N)
                                }
                            }
                        }
                    }]
                })
                print(f"[SheetsService] Headers formatted with filter enabled")
            except Exception as filter_error:
                print(f"[SheetsService] Headers formatted (filter may already exist)")
        except Exception as e:
            print(f"[SheetsService] Header setup: {e}")
            self.sheet.update([self.HEADERS], 'A1:N1')
    
    def _format_as_table(self):
        """Format the entire sheet as a professional table."""
        try:
            # Set column widths for better readability
            column_widths = [
                ("A", 60),   # SN
                ("B", 150),  # Thread ID
                ("C", 300),  # Email Subject (wider since no Task Name)
                ("D", 150),  # Sender Name
                ("E", 200),  # Sender Email
                ("F", 130),  # Date Sent
                ("G", 300),  # Email Summary
                ("H", 120),  # Team Origin
                ("I", 100),  # Origin Type
                ("J", 100),  # Reply Status
                ("K", 250),  # Replied By
                ("L", 130),  # Reply Date
                ("M", 300),  # Reply Summary
                ("N", 100),  # Task Status
            ]
            
            requests = []
            for col_letter, width in column_widths:
                col_index = ord(col_letter) - ord('A')
                requests.append({
                    "updateDimensionProperties": {
                        "range": {
                            "sheetId": self.sheet.id,
                            "dimension": "COLUMNS",
                            "startIndex": col_index,
                            "endIndex": col_index + 1
                        },
                        "properties": {
                            "pixelSize": width
                        },
                        "fields": "pixelSize"
                    }
                })
            
            # Add borders to all cells (table look)
            requests.append({
                "updateBorders": {
                    "range": {
                        "sheetId": self.sheet.id,
                        "startRowIndex": 0,
                        "endRowIndex": 1000,
                        "startColumnIndex": 0,
                        "endColumnIndex": 14
                    },
                    "top": {"style": "SOLID", "width": 1, "color": {"red": 0.8, "green": 0.8, "blue": 0.8}},
                    "bottom": {"style": "SOLID", "width": 1, "color": {"red": 0.8, "green": 0.8, "blue": 0.8}},
                    "left": {"style": "SOLID", "width": 1, "color": {"red": 0.8, "green": 0.8, "blue": 0.8}},
                    "right": {"style": "SOLID", "width": 1, "color": {"red": 0.8, "green": 0.8, "blue": 0.8}},
                    "innerHorizontal": {"style": "SOLID", "width": 1, "color": {"red": 0.8, "green": 0.8, "blue": 0.8}},
                    "innerVertical": {"style": "SOLID", "width": 1, "color": {"red": 0.8, "green": 0.8, "blue": 0.8}}
                }
            })
            
            # Clear any existing banding first to avoid conflicts
            try:
                sheet_metadata = self.sheet.spreadsheet.fetch_sheet_metadata()
                for sheet in sheet_metadata.get('sheets', []):
                    if sheet['properties']['sheetId'] == self.sheet.id:
                        banded_ranges = sheet.get('bandedRanges', [])
                        for banded_range in banded_ranges:
                            requests.append({
                                "deleteBanding": {
                                    "bandedRangeId": banded_range['bandedRangeId']
                                }
                            })
            except Exception as e:
                pass  # Silently skip if no banding exists
            
            # Add alternating row colors (banding) - light gray and white
            requests.append({
                "addBanding": {
                    "bandedRange": {
                        "range": {
                            "sheetId": self.sheet.id,
                            "startRowIndex": 1,  # Skip header
                            "endRowIndex": 1000,
                            "startColumnIndex": 0,
                            "endColumnIndex": 14
                        },
                        "rowProperties": {
                            "firstBandColor": {"red": 1.0, "green": 1.0, "blue": 1.0},
                            "secondBandColor": {"red": 0.95, "green": 0.95, "blue": 0.95}
                        }
                    }
                }
            })
            
            # Add data validation for Reply Status column (J)
            requests.append({
                "setDataValidation": {
                    "range": {
                        "sheetId": self.sheet.id,
                        "startRowIndex": 1,
                        "endRowIndex": 1000,
                        "startColumnIndex": 9,  # Column J (Reply Status)
                        "endColumnIndex": 10
                    },
                    "rule": {
                        "condition": {
                            "type": "ONE_OF_LIST",
                            "values": [
                                {"userEnteredValue": "No Reply"},
                                {"userEnteredValue": "Replied"}
                            ]
                        },
                        "showCustomUi": True,
                        "strict": False
                    }
                }
            })
            
            # Add data validation for Team Origin column (H)
            requests.append({
                "setDataValidation": {
                    "range": {
                        "sheetId": self.sheet.id,
                        "startRowIndex": 1,
                        "endRowIndex": 1000,
                        "startColumnIndex": 7,  # Column H (Team Origin)
                        "endColumnIndex": 8
                    },
                    "rule": {
                        "condition": {
                            "type": "ONE_OF_LIST",
                            "values": [
                                {"userEnteredValue": "Product Ops"},
                                {"userEnteredValue": "Sales"},
                                {"userEnteredValue": "Supply Chain & Logistics"},
                                {"userEnteredValue": "Engineering"},
                                {"userEnteredValue": "Finance"},
                                {"userEnteredValue": "Marketing"},
                                {"userEnteredValue": "Support"},
                                {"userEnteredValue": "HR"},
                                {"userEnteredValue": "Legal"},
                                {"userEnteredValue": "Other"}
                            ]
                        },
                        "showCustomUi": True,
                        "strict": False
                    }
                }
            })
            
            # Add data validation for Origin Type column (I)
            requests.append({
                "setDataValidation": {
                    "range": {
                        "sheetId": self.sheet.id,
                        "startRowIndex": 1,
                        "endRowIndex": 1000,
                        "startColumnIndex": 8,  # Column I (Origin Type)
                        "endColumnIndex": 9
                    },
                    "rule": {
                        "condition": {
                            "type": "ONE_OF_LIST",
                            "values": [
                                {"userEnteredValue": "Internal"},
                                {"userEnteredValue": "External"}
                            ]
                        },
                        "showCustomUi": True,
                        "strict": False
                    }
                }
            })
            
            # Add data validation for Task Status column (N)
            requests.append({
                "setDataValidation": {
                    "range": {
                        "sheetId": self.sheet.id,
                        "startRowIndex": 1,
                        "endRowIndex": 1000,
                        "startColumnIndex": 13,  # Column N (Task Status)
                        "endColumnIndex": 14
                    },
                    "rule": {
                        "condition": {
                            "type": "ONE_OF_LIST",
                            "values": [
                                {"userEnteredValue": "Pending"},
                                {"userEnteredValue": "In Progress"},
                                {"userEnteredValue": "Completed"},
                                {"userEnteredValue": "On Hold"},
                                {"userEnteredValue": "Cancelled"}
                            ]
                        },
                        "showCustomUi": True,
                        "strict": False
                    }
                }
            })
            
            # Clear existing conditional format rules to avoid duplicates
            try:
                sheet_metadata = self.sheet.spreadsheet.fetch_sheet_metadata()
                for sheet in sheet_metadata.get('sheets', []):
                    if sheet['properties']['sheetId'] == self.sheet.id:
                        cond_formats = sheet.get('conditionalFormats', [])
                        for i in range(len(cond_formats) - 1, -1, -1):
                            requests.append({
                                "deleteConditionalFormatRule": {
                                    "sheetId": self.sheet.id,
                                    "index": i
                                }
                            })
            except Exception:
                pass  # No existing rules to clear

            # Clear data validation from text-only columns (Email Summary, Replied By, Reply Date, etc.)
            # These should NOT have dropdowns
            text_only_columns = [
                (6, 7),   # Column G: Email Summary
                (10, 11), # Column K: Replied By
                (11, 12), # Column L: Reply Date
                (12, 13), # Column M: Reply Summary
            ]
            
            for start_col, end_col in text_only_columns:
                requests.append({
                    "setDataValidation": {
                        "range": {
                            "sheetId": self.sheet.id,
                            "startRowIndex": 1,
                            "endRowIndex": 1000,
                            "startColumnIndex": start_col,
                            "endColumnIndex": end_col
                        },
                        "rule": None  # Remove validation
                    }
                })

            # Conditional formatting: Origin Type (Column I) - Blue for "Internal", Green for "External"
            requests.append({
                "addConditionalFormatRule": {
                    "rule": {
                        "ranges": [{
                            "sheetId": self.sheet.id,
                            "startRowIndex": 1,
                            "endRowIndex": 1000,
                            "startColumnIndex": 8,  # Column I
                            "endColumnIndex": 9
                        }],
                        "booleanRule": {
                            "condition": {
                                "type": "TEXT_EQ",
                                "values": [{"userEnteredValue": "Internal"}]
                            },
                            "format": {
                                "backgroundColor": {"red": 0.85, "green": 0.92, "blue": 1.0},
                                "textFormat": {"foregroundColor": {"red": 0.13, "green": 0.40, "blue": 0.80}, "bold": True}
                            }
                        }
                    },
                    "index": 0
                }
            })
            requests.append({
                "addConditionalFormatRule": {
                    "rule": {
                        "ranges": [{
                            "sheetId": self.sheet.id,
                            "startRowIndex": 1,
                            "endRowIndex": 1000,
                            "startColumnIndex": 8,  # Column I
                            "endColumnIndex": 9
                        }],
                        "booleanRule": {
                            "condition": {
                                "type": "TEXT_EQ",
                                "values": [{"userEnteredValue": "External"}]
                            },
                            "format": {
                                "backgroundColor": {"red": 0.88, "green": 0.96, "blue": 0.88},
                                "textFormat": {"foregroundColor": {"red": 0.20, "green": 0.60, "blue": 0.20}, "bold": True}
                            }
                        }
                    },
                    "index": 1
                }
            })
            
            # Conditional formatting: Reply Status (Column J) - Red for "No Reply", Green for "Replied"
            requests.append({
                "addConditionalFormatRule": {
                    "rule": {
                        "ranges": [{
                            "sheetId": self.sheet.id,
                            "startRowIndex": 1,
                            "endRowIndex": 1000,
                            "startColumnIndex": 9,  # Column J
                            "endColumnIndex": 10
                        }],
                        "booleanRule": {
                            "condition": {
                                "type": "TEXT_EQ",
                                "values": [{"userEnteredValue": "No Reply"}]
                            },
                            "format": {
                                "backgroundColor": {"red": 0.96, "green": 0.80, "blue": 0.80},
                                "textFormat": {"foregroundColor": {"red": 0.80, "green": 0.11, "blue": 0.11}, "bold": True}
                            }
                        }
                    },
                    "index": 2
                }
            })
            requests.append({
                "addConditionalFormatRule": {
                    "rule": {
                        "ranges": [{
                            "sheetId": self.sheet.id,
                            "startRowIndex": 1,
                            "endRowIndex": 1000,
                            "startColumnIndex": 9,  # Column J
                            "endColumnIndex": 10
                        }],
                        "booleanRule": {
                            "condition": {
                                "type": "TEXT_EQ",
                                "values": [{"userEnteredValue": "Replied"}]
                            },
                            "format": {
                                "backgroundColor": {"red": 0.80, "green": 0.94, "blue": 0.80},
                                "textFormat": {"foregroundColor": {"red": 0.13, "green": 0.55, "blue": 0.13}, "bold": True}
                            }
                        }
                    },
                    "index": 3
                }
            })
            
            # Conditional formatting: Task Status column (N)
            # Pending - Orange
            requests.append({
                "addConditionalFormatRule": {
                    "rule": {
                        "ranges": [{
                            "sheetId": self.sheet.id,
                            "startRowIndex": 1,
                            "endRowIndex": 1000,
                            "startColumnIndex": 13,  # Column N
                            "endColumnIndex": 14
                        }],
                        "booleanRule": {
                            "condition": {
                                "type": "TEXT_EQ",
                                "values": [{"userEnteredValue": "Pending"}]
                            },
                            "format": {
                                "backgroundColor": {"red": 1.0, "green": 0.90, "blue": 0.70},
                                "textFormat": {"foregroundColor": {"red": 0.80, "green": 0.52, "blue": 0.0}, "bold": True}
                            }
                        }
                    },
                    "index": 4
                }
            })
            # In Progress - Blue
            requests.append({
                "addConditionalFormatRule": {
                    "rule": {
                        "ranges": [{
                            "sheetId": self.sheet.id,
                            "startRowIndex": 1,
                            "endRowIndex": 1000,
                            "startColumnIndex": 13,  # Column N
                            "endColumnIndex": 14
                        }],
                        "booleanRule": {
                            "condition": {
                                "type": "TEXT_EQ",
                                "values": [{"userEnteredValue": "In Progress"}]
                            },
                            "format": {
                                "backgroundColor": {"red": 0.80, "green": 0.88, "blue": 1.0},
                                "textFormat": {"foregroundColor": {"red": 0.10, "green": 0.33, "blue": 0.80}, "bold": True}
                            }
                        }
                    },
                    "index": 5
                }
            })
            # Completed - Green
            requests.append({
                "addConditionalFormatRule": {
                    "rule": {
                        "ranges": [{
                            "sheetId": self.sheet.id,
                            "startRowIndex": 1,
                            "endRowIndex": 1000,
                            "startColumnIndex": 13,  # Column N
                            "endColumnIndex": 14
                        }],
                        "booleanRule": {
                            "condition": {
                                "type": "TEXT_EQ",
                                "values": [{"userEnteredValue": "Completed"}]
                            },
                            "format": {
                                "backgroundColor": {"red": 0.80, "green": 0.94, "blue": 0.80},
                                "textFormat": {"foregroundColor": {"red": 0.13, "green": 0.55, "blue": 0.13}, "bold": True}
                            }
                        }
                    },
                    "index": 6
                }
            })
            # On Hold - Purple
            requests.append({
                "addConditionalFormatRule": {
                    "rule": {
                        "ranges": [{
                            "sheetId": self.sheet.id,
                            "startRowIndex": 1,
                            "endRowIndex": 1000,
                            "startColumnIndex": 13,  # Column N
                            "endColumnIndex": 14
                        }],
                        "booleanRule": {
                            "condition": {
                                "type": "TEXT_EQ",
                                "values": [{"userEnteredValue": "On Hold"}]
                            },
                            "format": {
                                "backgroundColor": {"red": 0.90, "green": 0.82, "blue": 0.96},
                                "textFormat": {"foregroundColor": {"red": 0.50, "green": 0.20, "blue": 0.70}, "bold": True}
                            }
                        }
                    },
                    "index": 7
                }
            })
            # Cancelled - Gray
            requests.append({
                "addConditionalFormatRule": {
                    "rule": {
                        "ranges": [{
                            "sheetId": self.sheet.id,
                            "startRowIndex": 1,
                            "endRowIndex": 1000,
                            "startColumnIndex": 13,  # Column N
                            "endColumnIndex": 14
                        }],
                        "booleanRule": {
                            "condition": {
                                "type": "TEXT_EQ",
                                "values": [{"userEnteredValue": "Cancelled"}]
                            },
                            "format": {
                                "backgroundColor": {"red": 0.90, "green": 0.90, "blue": 0.90},
                                "textFormat": {"foregroundColor": {"red": 0.50, "green": 0.50, "blue": 0.50}, "bold": True}
                            }
                        }
                    },
                    "index": 8
                }
            })
            
            # Execute all formatting requests
            self.sheet.spreadsheet.batch_update({"requests": requests})
            print(f"[SheetsService] Table formatting applied successfully")
            
        except Exception as e:
            print(f"[SheetsService] Error formatting table: {e}")
    
    def clear_sheet(self):
        """Clear all data rows from the sheet, keeping the header row."""
        try:
            all_values = self.sheet.get_all_values()
            if len(all_values) > 1:
                # Delete all rows after header
                self.sheet.delete_rows(2, len(all_values))
            # Re-apply table formatting (dropdowns, conditional formatting, etc.)
            self._format_as_table()
            print(f"[SheetsService] Sheet cleared (header preserved)")
        except Exception as e:
            print(f"[SheetsService] Error clearing sheet: {e}")

    # NEW — PASTE THIS
    def _get_next_sn(self) -> int:
        """Get the next serial number based on row count.
        Row count is always accurate even under rapid appends,
        unlike max+1 which suffers from Google Sheets API cache lag.
        """
        try:
            all_values = self.sheet.col_values(1)  # Get SN column
            # Count non-empty data rows (skip header row)
            data_rows = [v for v in all_values[1:] if v.strip() != '']
            return len(data_rows) + 1
        except:
            return 1
    
    def add_task(self, task: TaskData) -> bool:
        """
        Add a task to the Google Sheet with enhanced email tracking.
        
        Args:
            task: TaskData object with task information
            
        Returns:
            True if successful, False otherwise
        """
        try:
            sn = self._get_next_sn()
            
            row = [
                str(sn),
                task.thread_id,
                task.email_subject,
                task.sender_name,
                task.sender_email,
                task.date_sent,
                task.email_summary,
                task.team_origin,
                task.origin_type,
                task.reply_status,
                task.replied_by,
                task.reply_date,
                task.reply_summary,
                task.status
            ]
            
            self.sheet.append_row(row, value_input_option='USER_ENTERED')
            
            print(f"[SheetsService] Added task SN#{sn}: {task.email_subject[:50]}...")
            return True
            
        except Exception as e:
            print(f"[SheetsService] Error adding task: {e}")
            return False
    
    def find_thread_row(self, thread_id: str) -> Optional[int]:
        """
        Find the row number for a given thread ID.
        
        Args:
            thread_id: Gmail thread ID to search for
            
        Returns:
            Row number if found, None otherwise
        """
        try:
            # Get all thread IDs (column B)
            thread_ids = self.sheet.col_values(2)  # Column B (Thread ID)
            
            # Search for matching thread_id (skip header row)
            for i, tid in enumerate(thread_ids[1:], start=2):
                if tid == thread_id:
                    return i
            
            return None
        except Exception as e:
            print(f"[SheetsService] Error finding thread: {e}")
            return None
    
    def update_thread_reply(self, thread_id: str, reply_data: dict) -> bool:
        """
        Update an existing thread with reply information.
        
        Args:
            thread_id: Gmail thread ID
            reply_data: Dictionary with reply information (replied_by, reply_date, reply_summary, reply_count)
            
        Returns:
            True if successful, False otherwise
        """
        try:
            row_num = self.find_thread_row(thread_id)
            
            if not row_num:
                print(f"[SheetsService] Thread {thread_id} not found")
                return False
            
            # Update columns: J=Reply Status, K=Replied By, L=Reply Date, M=Reply Summary, N=Task Status
            updates = []
            
            # Column J (10): Reply Status
            updates.append({
                'range': f'J{row_num}',
                'values': [['Replied']]
            })
            
            # Column K (11): Replied By
            if 'replied_by' in reply_data:
                updates.append({
                    'range': f'K{row_num}',
                    'values': [[reply_data['replied_by']]]
                })
            
            # Column L (12): Reply Date
            if 'reply_date' in reply_data:
                updates.append({
                    'range': f'L{row_num}',
                    'values': [[reply_data['reply_date']]]
                })
            
            # Column M (13): Reply Summary
            if 'reply_summary' in reply_data:
                updates.append({
                    'range': f'M{row_num}',
                    'values': [[reply_data['reply_summary']]]
                })
            
            # Column N (14): Task Status
            if 'task_status' in reply_data:
                updates.append({
                    'range': f'N{row_num}',
                    'values': [[reply_data['task_status']]]
                })
                        # Batch update
            self.sheet.batch_update(updates)
            
            print(f"[SheetsService] Updated thread {thread_id} at row {row_num}")
            return True
            
        except Exception as e:
            print(f"[SheetsService] Error updating thread: {e}")
            return False
    
    def get_all_data(self) -> list[dict]:
        """
        Fetch all data from the sheet as a list of dictionaries.
        
        Returns:
            List of dictionaries with column headers as keys
        """
        try:
            # Get all values from the sheet
            all_values = self.sheet.get_all_values()
            
            if not all_values or len(all_values) < 2:
                return []
            
            # First row is headers
            headers = all_values[0]
            
            # Convert rows to dictionaries
            data = []
            for row in all_values[1:]:  # Skip header row
                # Pad row if it has fewer columns than headers
                while len(row) < len(headers):
                    row.append('')
                
                row_dict = {headers[i]: row[i] for i in range(len(headers))}
                data.append(row_dict)
            
            return data
            
        except Exception as e:
            print(f"[SheetsService] Error fetching all data: {e}")
            return []
    
    def add_tasks_batch(self, tasks: list[TaskData]) -> int:
        """
        Add multiple tasks in batch.
        
        Args:
            tasks: List of TaskData objects
            
        Returns:
            Number of successfully added tasks
        """
        success_count = 0
        start_sn = self._get_next_sn()
        
        rows = []
        for i, task in enumerate(tasks):
            rows.append([
                str(start_sn + i),
                task.thread_id,
                task.email_subject,
                task.sender_name,
                task.sender_email,
                task.date_sent,
                task.email_summary,
                task.team_origin,
                task.origin_type,
                task.reply_status,
                task.replied_by,
                task.reply_date,
                task.reply_summary,
                task.status
            ])
        
        try:
            if rows:
                self.sheet.append_rows(rows, value_input_option='USER_ENTERED')
                success_count = len(rows)
                print(f"[SheetsService] Added {success_count} tasks in batch")
        except Exception as e:
            print(f"[SheetsService] Error in batch add: {e}")
            # Fallback to individual adds
            for task in tasks:
                if self.add_task(task):
                    success_count += 1
        
        return success_count
    
    def get_all_tasks(self) -> list[dict]:
        """Get all tasks from the sheet."""
        try:
            records = self.sheet.get_all_records()
            return records
        except Exception as e:
            print(f"[SheetsService] Error getting tasks: {e}")
            return []
    
    def update_task_status(self, sn: int, status: str, date_of_solution: str = "") -> bool:
        """Update the status of a task by SN."""
        try:
            cell = self.sheet.find(str(sn), in_column=1)
            if cell:
                self.sheet.update_cell(cell.row, 4, status)  # Status column
                if date_of_solution:
                    self.sheet.update_cell(cell.row, 6, date_of_solution)  # Date of Solution
                return True
        except Exception as e:
            print(f"[SheetsService] Error updating task: {e}")
        return False
