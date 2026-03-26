"""
Logging configuration for the application.
"""
import logging
import sys
from datetime import datetime


def setup_logger(name: str = "email_agent", level: int = logging.INFO) -> logging.Logger:
    """
    Set up and configure logger.
    
    Args:
        name: Logger name
        level: Logging level
        
    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    # Avoid duplicate handlers
    if logger.handlers:
        return logger
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    
    # Format
    formatter = logging.Formatter(
        '%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_handler.setFormatter(formatter)
    
    logger.addHandler(console_handler)
    
    return logger


def get_logger(name: str = "email_agent") -> logging.Logger:
    """Get existing logger or create new one."""
    return logging.getLogger(name)
