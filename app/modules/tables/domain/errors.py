class InvalidTableData(ValueError):
    pass


class TableNameNotAvailable(Exception):
    """Another table of the same tenant already has that name."""


class TableNotFound(Exception):
    """No table with that id in the caller's tenant."""


class TableAlreadyCreated(Exception):
    """A repeated create of a table that exists: its PIN was shown once and cannot be shown again."""


class TableCodeTaken(Exception):
    """A concurrent create took the same random code between the check and the insert."""


class TableIdTaken(Exception):
    """A client-supplied id already belongs to another table (or another tenant)."""
