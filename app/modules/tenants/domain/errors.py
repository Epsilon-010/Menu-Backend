class InvalidTenantData(ValueError):
    pass


class TenantIdTaken(Exception):
    """A client-supplied tenant id already belongs to another tenant."""
