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
        "Recipient Email",
        "Date Sent",
        "Task Name",
        "Email Summary",
        "Team Origin",
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
                cols=10
            )
    
    def _ensure_headers(self):
        """Ensure headers exist in the first row with proper formatting."""
        try:
            first_row = self.sheet.row_values(1)
            if not first_row or first_row != self.HEADERS:
                # Update headers
                self.sheet.update('A1:O1', [self.HEADERS])
            
            # Always apply header formatting
            self.sheet.format('A1:O1', {
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
                                    "endColumnIndex": 15   # All 15 columns (A-O)
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
            self.sheet.update('A1:O1', [self.HEADERS])
    
    def _format_as_table(self):
        """Format the entire sheet as a professional table."""
        try:
            # Set column widths for better readability
            column_widths = [
                ("A", 60),   # SN
                ("B", 150),  # Thread ID
                ("C", 250),  # Email Subject
                ("D", 150),  # Sender Name
                ("E", 200),  # Sender Email
                ("F", 250),  # Recipient Email
                ("G", 130),  # Date Sent
                ("H", 200),  # Task Name
                ("I", 300),  # Email Summary
                ("J", 120),  # Team Origin
                ("K", 100),  # Reply Status
                ("L", 100),  # Reply Count
                ("M", 250),  # Replied By
                ("N", 130),  # Reply Date
                ("O", 300),  # Reply Summary
                ("P", 100),  # Task Status
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
                        "endColumnIndex": 16
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
                            "endColumnIndex": 16
                        },
                        "rowProperties": {
                            "firstBandColor": {"red": 1.0, "green": 1.0, "blue": 1.0},
                            "secondBandColor": {"red": 0.95, "green": 0.95, "blue": 0.95}
                        }
                    }
                }
            })
            
            # Add data validation for Reply Status column (K)
            requests.append({
                "setDataValidation": {
                    "range": {
                        "sheetId": self.sheet.id,
                        "startRowIndex": 1,
                        "endRowIndex": 1000,
                        "startColumnIndex": 10,  # Column K (Reply Status)
                        "endColumnIndex": 11
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
            
            # Add data validation for Task Status column (P)
            requests.append({
                "setDataValidation": {
                    "range": {
                        "sheetId": self.sheet.id,
                        "startRowIndex": 1,
                        "endRowIndex": 1000,
                        "startColumnIndex": 15,  # Column P (Task Status)
                        "endColumnIndex": 16
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
            
            # Execute all formatting requests
            self.sheet.spreadsheet.batch_update({"requests": requests})
            print(f"[SheetsService] Table formatting applied successfully")
            
        except Exception as e:
            print(f"[SheetsService] Error formatting table: {e}")
    
    def _get_next_sn(self) -> int:
        """Get the next serial number."""
        try:
            all_values = self.sheet.col_values(1)  # Get SN column
            # Filter out header and empty values
            numbers = [int(v) for v in all_values[1:] if v.isdigit()]
            return max(numbers, default=0) + 1
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
                task.recipient_email,
                task.date_sent,
                task.task_name,
                task.email_summary,
                task.team_origin,
                task.reply_status,
                task.replied_by,
                task.reply_date,
                task.reply_summary,
                task.status
            ]
            
            self.sheet.append_row(row, value_input_option='USER_ENTERED')
            
            print(f"[SheetsService] Added task SN#{sn}: {task.task_name}")
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
            
            # Update columns: K=Reply Status, L=Replied By, M=Reply Date, N=Reply Summary
            updates = []
            
            # Column K (11): Reply Status
            updates.append({
                'range': f'K{row_num}',
                'values': [['Replied']]
            })
            
            # Column L (12): Replied By
            if 'replied_by' in reply_data:
                updates.append({
                    'range': f'L{row_num}',
                    'values': [[reply_data['replied_by']]]
                })
            
            # Column M (13): Reply Date
            if 'reply_date' in reply_data:
                updates.append({
                    'range': f'M{row_num}',
                    'values': [[reply_data['reply_date']]]
                })
            
            # Column N (14): Reply Summary
            if 'reply_summary' in reply_data:
                updates.append({
                    'range': f'N{row_num}',
                    'values': [[reply_data['reply_summary']]]
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
                task.task_name,
                task.description,
                task.status,
                task.date_of_query,
                task.date_of_solution,
                task.request_came_from,
                task.team_origin
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
