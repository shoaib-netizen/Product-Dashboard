"""
Chat-to-Sheets Agent
====================

This module defines a simple orchestration agent that monitors a Google Chat
space, extracts messages from allowed users, and writes them into a
secondary worksheet in your Google Sheet.  It relies on the
``GoogleChatService`` for interacting with the Chat API and the
``ChatSheetsService`` for persisting data to Sheets.

The ``ChatToSheetsAgent`` can be invoked directly via a command‐line script
(see ``chat_main.py``) or scheduled to run periodically via the existing
``scheduler.py``.  When running in scheduled mode, it will respect the
``CHAT_CHECK_INTERVAL_MINUTES`` configuration and only run if
``CHAT_SPACE_ID`` is set.
"""

from __future__ import annotations

import logging
from typing import Optional

from config import Config

# Import directly from specific files instead of from src.services package.
# This avoids a circular import that occurs because src.services.__init__.py
# loads sheets_service, which loads src.agents, which loads this file,
# which then tries to import from src.services before it has finished loading.
from src.services.chat_service import GoogleChatService
from src.services.chat_sheets_service import ChatSheetsService

from src.utils import setup_logger


logger = setup_logger("chat_agent")


class ChatToSheetsAgent:
    """Coordinate fetching chat messages and writing them to Sheets."""

    def __init__(self) -> None:
        """Initialize the chat and sheet services."""
        logger.info("Initializing Chat-to-Sheets Agent...")
        # Validate that Chat is configured
        if not Config.CHAT_SPACE_ID:
            logger.warning(
                "CHAT_SPACE_ID is not configured. Chat-to-Sheets pipeline will not run."
            )
        # Initialize services
        self.chat_service = GoogleChatService()
        self.sheets_service = ChatSheetsService()
        logger.info("✓ Chat services initialized successfully")

    def process_messages(
        self, start_date: Optional[str] = None, end_date: Optional[str] = None
    ) -> int:
        """
        Fetch and store chat messages from the configured space.

        Args:
            start_date: Optional start date in ``YYYY-MM-DD`` format.  If
                provided, messages created after this date will be fetched.
            end_date: Optional end date in ``YYYY-MM-DD`` format.  If
                provided, messages created before this date will be fetched.

        Returns:
            The number of chat messages inserted into the sheet.
        """
        if not Config.CHAT_SPACE_ID:
            logger.info("Chat pipeline is disabled because CHAT_SPACE_ID is not set")
            return 0

        logger.info("Fetching messages from Google Chat space...")
        messages = self.chat_service.fetch_messages(start_date=start_date, end_date=end_date)
        if not messages:
            logger.info("No chat messages found in the given period")
            return 0

        logger.info(f"Fetched {len(messages)} chat message(s) after filtering allowed senders")
        logger.info("Checking reply statuses...")
        replied_message_ids = self.chat_service.fetch_replied_message_ids()
        logger.info(f"Found {len(replied_message_ids)} message(s) that have been replied to")

        # Insert new messages
        inserted = self.sheets_service.append_messages(messages, replied_message_ids=replied_message_ids)
        logger.info(f"Inserted {inserted} new chat message(s) into sheet '{Config.CHAT_SHEET_NAME}'")

        # Update existing rows that were previously Not Replied but now have a reply
        updated = self.sheets_service.update_reply_statuses(replied_message_ids)
        if updated:
            logger.info(f"Updated {updated} existing message(s) from 'Not Replied' to 'Replied'")

        return inserted