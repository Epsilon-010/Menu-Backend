class InvalidCredentials(Exception):
    """Wrong email, wrong password or inactive account; callers must not tell them apart."""


class TooManyLoginAttempts(Exception):
    def __init__(self, retry_after: int) -> None:
        super().__init__(f"Too many login attempts, retry in {retry_after}s")
        self.retry_after = retry_after


class InvalidRefreshToken(Exception):
    pass


class AccountNotFound(Exception):
    """The token's subject does not exist (or is inactive) inside the token's tenant."""
