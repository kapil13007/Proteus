"""Everything Dataform-specific: compiling SQLX with the team's JS includes, and rendering files."""


class CompileError(Exception):
    """A SQLX file or JS include could not be compiled. The message is shown to the user."""
