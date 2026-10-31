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


class AdminNotFound(Exception):
    """No admin with that id in the caller's tenant."""


class AdminAlreadyCreated(Exception):
    """The client-supplied id already is an admin of this tenant: a replay of the create.

    The temporary password only exists as a hash, so the replay cannot return it.
    """


class CannotDeactivateSelf(Exception):
    """An admin tried to deactivate their own account (the business would risk having no admin)."""


class NotAnActiveAdmin(Exception):
    """The caller's account is no longer an active admin (deactivated while its token was still valid)."""


class WrongCurrentPassword(Exception):
    pass
