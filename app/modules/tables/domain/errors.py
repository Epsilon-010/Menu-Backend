class InvalidTableData(ValueError):
    pass


class TableNameNotAvailable(Exception):
    """Another table of the same tenant already has that name."""


class TableNotFound(Exception):
    """No table with that id in the caller's tenant."""
