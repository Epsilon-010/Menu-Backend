class InvalidUserData(ValueError):
    pass


class EmailAlreadyInUse(Exception):
    pass


class UsernameNotAvailable(Exception):
    pass


class StaffMemberNotFound(Exception):
    """No waiter or cook with that id in the caller's tenant."""


class StaffIdTaken(Exception):
    """A client-supplied id already belongs to another user (or another tenant)."""
