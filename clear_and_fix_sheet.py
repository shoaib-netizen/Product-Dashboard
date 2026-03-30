"""
Quick script to clear sheet data and remove the old Task Name column.
Run this once to migrate to the new 14-column structure.
"""
import sys
from src.services import GoogleSheetsService
from src.utils import setup_logger

logger = setup_logger("clear_sheet")

def main():
    """Clear sheet and update to new column structure."""
    try:
        logger.info("Initializing Google Sheets service...")
        sheets = GoogleSheetsService()
        
        # Step 1: Clear all data except header
        logger.info("Clearing all data rows (keeping header)...")
        all_values = sheets.sheet.get_all_values()
        
        if len(all_values) > 1:
            # Delete all rows except header (row 1)
            sheets.sheet.delete_rows(2, len(all_values))
            logger.info(f"✓ Deleted {len(all_values) - 1} data rows")
        else:
            logger.info("✓ Sheet already empty (header only)")
        
        # Step 2: Delete column G (old Task Name column)
        logger.info("Removing old 'Task Name' column (column G)...")
        try:
            # Column G is index 7 (A=1, B=2, ..., G=7)
            sheets.sheet.delete_columns(7)
            logger.info("✓ Deleted old Task Name column")
        except Exception as e:
            logger.warning(f"Column may already be deleted: {e}")
        
        # Step 3: Update headers to new structure
        logger.info("Updating headers to new 14-column structure...")
        sheets._ensure_headers()
        logger.info("✓ Headers updated")
        
        # Step 4: Apply formatting
        logger.info("Applying table formatting...")
        sheets._format_as_table()
        logger.info("✓ Formatting applied")
        
        logger.info("")
        logger.info("=" * 60)
        logger.info("✅ MIGRATION COMPLETE!")
        logger.info("=" * 60)
        logger.info("Sheet is now ready with 14 columns (A-N)")
        logger.info("New structure:")
        logger.info("  A: SN")
        logger.info("  B: Thread ID")
        logger.info("  C: Email Subject")
        logger.info("  D: Sender Name")
        logger.info("  E: Sender Email")
        logger.info("  F: Date Sent")
        logger.info("  G: Email Summary")
        logger.info("  H: Team Origin")
        logger.info("  I: Origin Type")
        logger.info("  J: Reply Status")
        logger.info("  K: Replied By")
        logger.info("  L: Reply Date")
        logger.info("  M: Reply Summary")
        logger.info("  N: Task Status")
        logger.info("")
        logger.info("You can now run: python main.py")
        logger.info("=" * 60)
        
        return 0
        
    except Exception as e:
        logger.error(f"Error during migration: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())
