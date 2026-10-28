class InvalidCatalogData(ValueError):
    pass


class CategoryNameNotAvailable(Exception):
    """Another category of the same tenant already has that name."""


class CategoryNotFound(Exception):
    """No category with that id in the caller's tenant."""


class CategoryNotEmpty(Exception):
    """A category with items cannot be deleted."""


class ItemNotFound(Exception):
    """No item with that id in the caller's tenant."""


class CatalogIdTaken(Exception):
    """A client-supplied id already belongs to another category or item (other data or another tenant)."""
