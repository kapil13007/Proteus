"""Parsers for the user's context files: schemas, STTM sheet, and repo folder structure."""


class InputError(Exception):
    """An uploaded file could not be understood. The message is shown to the user as-is."""
