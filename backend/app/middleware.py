import secrets

from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse


class GuardMiddleware:
    """Authenticate before multipart parsing; limit streamed/chunked request bodies too."""

    def __init__(self, app, api_key: str, max_bytes: int):
        self.app = app
        self.api_key = api_key.encode()
        self.max_bytes = max_bytes + 1024 * 1024  # Allow multipart headers.

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith("/api/"):
            return await self.app(scope, receive, send)
        if scope["method"] == "OPTIONS":
            return await self.app(scope, receive, send)
        headers = dict(scope["headers"])
        if not secrets.compare_digest(headers.get(b"x-api-key", b""), self.api_key):
            return await JSONResponse(
                {"detail": "Неверный или отсутствующий X-API-Key."}, status_code=401
            )(scope, receive, send)
        try:
            length = int(headers.get(b"content-length", b"0"))
        except ValueError:
            return await JSONResponse({"detail": "Invalid Content-Length"}, 400)(
                scope, receive, send
            )
        if length < 0 or length > self.max_bytes:
            return await JSONResponse({"detail": "Файл превышает допустимый размер."}, 413)(
                scope, receive, send
            )
        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    # HTTPException lets Starlette close any temporary multipart files.
                    raise HTTPException(413, "Файл превышает допустимый размер.")
            return message

        await self.app(scope, limited_receive, send)
