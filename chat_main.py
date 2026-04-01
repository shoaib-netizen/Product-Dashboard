"""
Chat Pipeline Entry Point
-------------------------

This script allows you to fetch messages from a Google Chat space and write
them into a separate worksheet within your Google Sheet.  It can be run
manually from the command line and accepts optional date parameters to
control the timeframe of messages to import.

Usage:

    python chat_main.py                 # process messages from default window
    python chat_main.py --start 2026-03-01 --end 2026-03-31

The default window is determined by the ``CHAT_INITIAL_IMPORT`` setting: if
true, all messages since January 1, 2026 are imported; otherwise only
messages from the last seven days are fetched.  You can override this
behaviour by specifying ``--start`` and optionally ``--end``.
"""

from __future__ import annotations

import argparse
from datetime import datetime

from src.agents import ChatToSheetsAgent
from src.utils import setup_logger

logger = setup_logger("chat_main")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Process Google Chat messages and store in Sheets")
    parser.add_argument(
        "--start",
        dest="start_date",
        help="Optional start date (YYYY-MM-DD) to fetch messages after",
    )
    parser.add_argument(
        "--end",
        dest="end_date",
        help="Optional end date (YYYY-MM-DD) to fetch messages before",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    start = args.start_date
    end = args.end_date

    # Validate date formats if provided
    for label, date_str in {"start": start, "end": end}.items():
        if date_str:
            try:
                datetime.strptime(date_str, "%Y-%m-%d")
            except ValueError:
                logger.error(f"Invalid {label} date format: {date_str}. Use YYYY-MM-DD.")
                return

    agent = ChatToSheetsAgent()
    inserted = agent.process_messages(start_date=start, end_date=end)
    logger.info(f"Done. Inserted {inserted} chat message(s) into the sheet.")


if __name__ == "__main__":
    main()
