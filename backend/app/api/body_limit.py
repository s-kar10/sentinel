"""Bound HTTP request bodies before JSON parsing or schema validation.

Field-level Pydantic limits run only after the full body has been buffered and
decoded, so they cannot stop a client from making the API read an arbitrarily
large body. This ASGI layer rejects an oversized declared Content-Length without
reading it, and counts streamed/chunked bytes so an undeclared body is cut off
as soon as it crosses the limit.
"""

from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse

TOO_LARGE_DETAIL = "The request body exceeds the configured size limit."


class RequestBodyTooLarge(HTTPException):
    """Raised from the wrapped receive channel once the byte budget is exceeded.

    FastAPI re-raises Starlette HTTP exceptions during body parsing (other errors
    become a generic 400), so its exception middleware converts this to 413.
    """

    def __init__(self) -> None:
        super().__init__(status_code=413, detail=TOO_LARGE_DETAIL)


class RequestBodyLimitMiddleware:
    def __init__(self, app, *, max_bytes: int):
        if max_bytes < 1:
            raise ValueError("max_bytes must be positive.")
        self.app = app
        self.max_bytes = max_bytes

    @staticmethod
    async def _reject(scope, receive, send, status: int, detail: str) -> None:
        await JSONResponse(
            {"detail": detail},
            status_code=status,
            headers={"Connection": "close"},
        )(scope, receive, send)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        declared = {
            value.strip()
            for key, value in scope["headers"]
            if key.lower() == b"content-length"
        }
        if declared:
            value = next(iter(declared))
            if len(declared) != 1 or not value.isdigit() or len(value) > 19:
                return await self._reject(
                    scope, receive, send, 400, "Invalid Content-Length header."
                )
            if int(value) > self.max_bytes:
                return await self._reject(scope, receive, send, 413, TOO_LARGE_DETAIL)

        received = 0
        response_started = False

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise RequestBodyTooLarge()
            return message

        async def tracking_send(message):
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except RequestBodyTooLarge:
            # Reached only when the body was read outside FastAPI's handler.
            if response_started:
                raise
            await self._reject(scope, receive, send, 413, TOO_LARGE_DETAIL)
