"""Logging filters."""

import logging


class DropTraceback(logging.Filter):
    """Log the message only: for expected rejections a traceback is noise, not information."""

    def filter(self, record):
        record.exc_info = None
        record.exc_text = None
        record.stack_info = None
        return True
