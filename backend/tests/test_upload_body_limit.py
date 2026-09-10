import asyncio
from types import SimpleNamespace


def test_chunked_body_rejected_before_multipart_parser():
    from app.upload_body import UploadBodyLimitMiddleware

    reached = []
    output = []
    chunks = iter([
        {"type": "http.request", "body": b"a" * 700_000, "more_body": True},
        {"type": "http.request", "body": b"a" * 700_000, "more_body": False},
    ])

    async def downstream(scope, receive, send):
        reached.append(True)

    async def receive():
        return next(chunks)

    async def send(message):
        output.append(message)

    middleware = UploadBodyLimitMiddleware(
        downstream, settings=SimpleNamespace(max_upload_total_bytes=10),
    )
    asyncio.run(middleware(
        {"type": "http", "method": "POST", "path": "/api/semesters/id/syllabi", "headers": []},
        receive, send,
    ))
    assert not reached
    assert output[0]["status"] == 413


def test_accepted_body_is_replayed_exactly():
    from app.upload_body import UploadBodyLimitMiddleware

    original = b"%PDF" * 100_000
    chunks = iter([
        {"type": "http.request", "body": original[:15], "more_body": True},
        {"type": "http.request", "body": original[15:], "more_body": False},
    ])
    seen = bytearray()

    async def downstream(scope, receive, send):
        while True:
            message = await receive()
            seen.extend(message["body"])
            if not message.get("more_body"):
                break

    async def receive():
        return next(chunks)

    async def send(message):
        pass

    middleware = UploadBodyLimitMiddleware(
        downstream, settings=SimpleNamespace(max_upload_total_bytes=len(original)),
    )
    asyncio.run(middleware(
        {"type": "http", "method": "POST", "path": "/api/semesters/id/syllabi", "headers": []},
        receive, send,
    ))
    assert seen == original
