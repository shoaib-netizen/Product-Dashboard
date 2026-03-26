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
        "Email Subject",
        "Sender Name",
        "Sender Email",
        "Recipient Email",
        "Date Sent",
        "Date Received",
        "Task Name",
        "Email Summary",
        "Team Origin",
        "Reply Status",
        "Replied By",
        "Reply Date",
        "Reply Summary",
        "Task Status",
        "Date of Solution"
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
                self.sheet.update('A1:P1', [self.HEADERS])
                
                # Format header row (blue background, white bold text, centered)
                self.sheet.format('A1:P1', {
                    'backgroundColor': {'red': 0.2, 'green': 0.4, 'blue': 0.8},
                    'textFormat': {'bold': True, 'foregroundColor': {'red': 1.0, 'green': 1.0, 'blue': 1.0}},
                    'horizontalAlignment': 'CENTER',
                    'verticalAlignment': 'MIDDLE'
                })
                
                # Freeze header row
                self.sheet.freeze(rows=1)
                
                print(f"[SheetsService] Headers formatted with 16 columns")
        except Exception as e:
            print(f"[SheetsService] Header setup: {e}")
            self.sheet.update('A1:P1', [self.HEADERS])
    
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
                task.email_subject,
                task.sender_name,
                task.sender_email,
                task.recipient_email,
                task.date_sent,
                task.date_received,
                task.task_name,
                task.email_summary,
                task.team_origin,
                task.reply_status,
                task.replied_by,
                task.reply_date,
                task.reply_summary,
                task.status,
                task.date_of_solution
            ]
            
            self.sheet.append_row(row, value_input_option='USER_ENTERED')
            
            # Apply conditional formatting based on reply status
            row_num = sn + 1  # +1 for header row
            self._apply_row_formatting(row_num, task.reply_status)
            
            print(f"[SheetsService] Added task SN#{sn}: {task.task_name}")
            return True
            
        except Exception as e:
            print(f"[SheetsService] Error adding task: {e}")
            return False
    
    def _apply_row_formatting(self, row_num: int, reply_status: str):
        """Apply conditional formatting based on reply status."""
        try:
            # Color code based on reply status
            if reply_status == "Replied":
                bg_color = {'red': 0.85, 'green': 0.95, 'blue': 0.85}  # Light green
            elif reply_status == "Pending":
                bg_color = {'red': 1.0, 'green': 0.95, 'blue': 0.8}  # Light yellow
            else:  # No Reply
                bg_color = {'red': 1.0, 'green': 1.0, 'blue': 1.0}  # White
                
            self.sheet.format(f'A{row_num}:P{row_num}', {
                'backgroundColor': bg_color
            })
        except:
            pass  # Silently fail if formatting doesn't work
    
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
