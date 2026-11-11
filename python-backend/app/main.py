import hmac

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.routes import router
from app.core.config import settings


class CsrfMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path.startswith("/api/"):
            content_length = request.headers.get("content-length")
            if content_length and content_length.isdigit() and int(content_length) > 262_144:
                return JSONResponse(status_code=413, content={"detail": "Request body is too large."})
        if request.method in {"POST", "PUT", "PATCH", "DELETE"} and request.url.path.startswith("/api/"):
            origin = request.headers.get("origin")
            if origin and origin not in settings.cors_origins:
                return JSONResponse(status_code=403, content={"detail": "Untrusted request origin."})
            cookie = request.cookies.get("louf_csrf")
            header = request.headers.get("x-csrf-token")
            if not cookie or not header or not hmac.compare_digest(cookie, header):
                return JSONResponse(
                    status_code=403,
                    content={"detail": "CSRF validation failed. Refresh and try again."},
                )
        return await call_next(request)


app = FastAPI(
    title="LOUF AI API",
    version="0.1.0",
    description=(
        "Assistant API. Chat uses a configured Bionic-compatible endpoint; "
        "image and video generation use configured local ComfyUI workflows."
    ),
)
app.add_middleware(CsrfMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "X-CSRF-Token"],
)
app.include_router(router)
