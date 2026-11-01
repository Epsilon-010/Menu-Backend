import uuid

import pytest

from app.shared.domain.pagination import MAX_CURSOR_KEY_LENGTH, Cursor
from app.shared.infrastructure.http.pagination import decode_cursor, encode_cursor


@pytest.mark.parametrize("char", ["a", "ñ", "語", "🌮"])
def test_every_cursor_the_server_makes_decodes_back(char: str) -> None:
    # The longest key, in characters of 1 to 4 UTF-8 bytes: a long name with emoji must page too.
    cursor = Cursor(key=char * MAX_CURSOR_KEY_LENGTH, id=uuid.uuid4())

    assert decode_cursor(encode_cursor(cursor)) == cursor
