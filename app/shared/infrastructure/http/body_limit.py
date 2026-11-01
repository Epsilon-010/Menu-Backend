"""Caps the size of request bodies before any route (or the NUL check, which reads every JSON body) runs.

The proxy in front may cap them too (nginx), but the API never relies on it: the dev proxy and direct
callers send whatever they like. A declared Content-Length over the cap is refused at once; a body
without one (chunked) is read up to the cap and then handed on as if it had just arrived.
"""

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.shared.infrastructure.http.problems import problem

TOO_LARGE = "The request body is too large"


class BodySizeLimit:
    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self._app = app
        self._max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        declared = dict(scope["headers"]).get(b"content-length")
        if declared is not None:
            if not declared.isdigit() or int(declared) > self._max_bytes:
                await problem(413, TOO_LARGE)(scope, receive, send)
                return
            # The server never delivers more than the declared length.
            await self._app(scope, receive, send)
            return

        chunks: list[bytes] = []
        size = 0
        while True:
            message = await receive()
            if message["type"] != "http.request":
                # The client left before sending it all: let the app see that as usual.
                await self._app(scope, _replay([message], receive), send)
                return
            chunk = message.get("body", b"")
            size += len(chunk)
            if size > self._max_bytes:
                await problem(413, TOO_LARGE)(scope, receive, send)
                return
            chunks.append(chunk)
            if not message.get("more_body", False):
                break
        whole: Message = {"type": "http.request", "body": b"".join(chunks), "more_body": False}
        await self._app(scope, _replay([whole], receive), send)


def _replay(messages: list[Message], receive: Receive) -> Receive:
    """Gives `messages` first, then whatever the client sends next (a disconnect, for streams)."""

    async def replayed() -> Message:
        if messages:
            return messages.pop(0)
        return await receive()

    return replayed
