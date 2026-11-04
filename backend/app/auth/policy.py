"""Default-deny route policy; test coverage requires classifying new API routes."""

import re

from app.auth.tokens import Role

PUBLIC_GET = frozenset({"/health", "/ready", "/auth/status"})
READ_PATHS = (
    r"/auth/me",
    r"/targets",
    r"/targets/[0-9]+",
    r"/targets/[0-9]+/protected-values",
    r"/attack-packs",
    r"/evaluations",
    r"/evaluations/[0-9]+",
    r"/evaluations/[0-9]+/results",
    r"/targets/[0-9]+/baselines",
    r"/evaluations/[0-9]+/comparison",
    r"/targets/[0-9]+/analytics",
    r"/openapi.json",
)
RUN_PATHS = (
    r"/targets/[0-9]+/evaluation-jobs",
    r"/evaluations/[0-9]+/cancel",
    r"/targets/[0-9]+/baselines",
)
ADMIN_PATHS = {
    "POST": (r"/targets", r"/targets/[0-9]+/protected-values"),
    "PUT": (r"/targets/[0-9]+",),
    "DELETE": (r"/targets/[0-9]+", r"/protected-values/[0-9]+"),
}


def required_role(method: str, path: str) -> Role | None:
    # FastAPI redirects a single trailing slash to its canonical route. Protect
    # the redirect too; do not redirect an unauthenticated request with credentials.
    path = path.removesuffix("/")
    if method == "GET" and any(re.fullmatch(p, path) for p in READ_PATHS):
        return Role.READER
    if method == "POST" and any(re.fullmatch(p, path) for p in RUN_PATHS):
        return Role.RUNNER
    if any(re.fullmatch(p, path) for p in ADMIN_PATHS.get(method, ())):
        return Role.ADMIN
    # Synchronous execution bypasses queue limits. It remains available only in
    # explicit local mode, including for admin tokens.
    return None


def permits(role: Role, method: str, path: str) -> bool:
    required = required_role(method, path)
    return required is not None and list(Role).index(role) >= list(Role).index(required)
