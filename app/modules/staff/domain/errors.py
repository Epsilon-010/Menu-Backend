class InvalidUserData(ValueError):
    pass


class EmailAlreadyInUse(Exception):
    pass


class StaffCodeTaken(Exception):
    """The generated staff code (stored in the unique username column) is already in use."""


class StaffMemberNotFound(Exception):
    """No waiter or cook with that id in the caller's tenant."""


class StaffIdTaken(Exception):
    """A client-supplied id already belongs to another user (or another tenant)."""


class StaffAlreadyCreated(Exception):
    """The client-supplied id already is a member of this tenant: a replay of the create.

    The PIN only exists as a hash, so the replay cannot return it; a new PIN shows the credentials.
    """
