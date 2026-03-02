class DatabaseError(Exception):
    """Base class for database exceptions."""
    pass

class ProfileError(DatabaseError):
    """Raised when there is an issue with user profiles."""
    pass

class ExpenseError(DatabaseError):
    """Raised when there is an issue adding or deleting expenses."""
    pass
