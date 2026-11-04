"""Authenticate before parsing request bodies, then apply a default-deny policy."""

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from app.auth.policy import PUBLIC_GET, permits
from app.auth.tokens import authenticate


class AccessMiddleware:
    def __init__(self, app, *, engine, mode):
        self.app = app
        self.engine = engine
        self.mode = mode

    def lookup(self, value):
        with Session(self.engine) as db:
            return authenticate(db, value)

    async def __call__(self, scope, receive, send):
        if scope["type"] == "websocket" and self.mode == "token":
            return await send({"type": "websocket.close", "code": 1008})
        if scope["type"] != "http" or self.mode == "local":
            return await self.app(scope, receive, send)
        if scope["method"] == "GET" and scope["path"] in PUBLIC_GET:
            return await self.app(scope, receive, send)
        headers = [v for k, v in scope["headers"] if k.lower() == b"authorization"]
        principal = None
        status, detail = 401, "A valid access token is required."
        if len(headers) == 1 and len(headers[0]) <= 100:
            scheme, _, token = headers[0].partition(b" ")
            if scheme.lower() == b"bearer":
                try:
                    principal = await run_in_threadpool(
                        self.lookup, token.decode("ascii")
                    )
                except UnicodeDecodeError:
                    pass
                except (SQLAlchemyError, ValueError):
                    status, detail = 503, "Access verification is unavailable."
        if principal is not None:
            if permits(principal.role, scope["method"], scope["path"]):
                scope.setdefault("state", {})["principal"] = principal

                async def private_send(message):
                    if message["type"] == "http.response.start":
                        message["headers"] = [
                            (k, v)
                            for k, v in message["headers"]
                            if k.lower() != b"cache-control"
                        ]
                        message["headers"].append((b"cache-control", b"no-store"))
                    await send(message)

                return await self.app(scope, receive, private_send)
            status, detail = 403, "This access token cannot perform that operation."
        response_headers = {"Cache-Control": "no-store"}
        if status == 401:
            response_headers["WWW-Authenticate"] = "Bearer"
        await JSONResponse(
            {"detail": detail}, status_code=status, headers=response_headers
        )(scope, receive, send)
