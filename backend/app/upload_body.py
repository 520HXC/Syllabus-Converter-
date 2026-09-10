import asyncio
import tempfile
from time import monotonic

from starlette.responses import JSONResponse

from .config import Settings


class UploadBodyLimitMiddleware:
    """Bound raw multipart bodies before the framework spools any uploaded files."""

    def __init__(self, app, settings: Settings):
        self.app = app
        self.settings = settings
        self.slots = asyncio.Semaphore(4)

    async def __call__(self, scope, receive, send):
        if (scope["type"] != "http" or scope["method"] != "POST"
                or not scope["path"].endswith("/syllabi")):
            return await self.app(scope, receive, send)

        async def reject(status, message):
            await JSONResponse({"detail": message}, status_code=status)(scope, receive, send)

        # Reserve a small multipart envelope in addition to the actual PDF byte limit.
        maximum = self.settings.max_upload_total_bytes + 1024 * 1024
        headers = dict(scope.get("headers", []))
        if b"content-length" in headers:
            try:
                length = int(headers[b"content-length"])
                if length < 0:
                    raise ValueError
            except ValueError:
                return await reject(400, "Invalid upload length.")
            if length > maximum:
                return await reject(413, "The combined PDF upload is too large.")
        if self.slots.locked():
            return await reject(429, "Too many uploads. Please try again shortly.")
        async with self.slots:
            # Disk-backed from the start so a single large ASGI chunk is not copied into RAM.
            with tempfile.TemporaryFile() as body:
                total = 0
                deadline = monotonic() + 60
                while True:
                    try:
                        message = await asyncio.wait_for(receive(), max(0, deadline - monotonic()))
                    except TimeoutError:
                        return await reject(408, "The upload timed out. Please try again.")
                    if message["type"] == "http.disconnect":
                        return
                    chunk = message.get("body", b"")
                    total += len(chunk)
                    if total > maximum:
                        return await reject(413, "The combined PDF upload is too large.")
                    body.write(chunk)
                    if not message.get("more_body", False):
                        break
                body.seek(0)
                remaining = total

                async def replay():
                    nonlocal remaining
                    if remaining == 0:
                        return {"type": "http.request", "body": b"", "more_body": False}
                    chunk = body.read(min(64 * 1024, remaining))
                    remaining -= len(chunk)
                    return {"type": "http.request", "body": chunk, "more_body": remaining > 0}

                return await self.app(scope, replay, send)
