from __future__ import annotations

from io import BytesIO

import pymupdf

from .conftest import auth_headers


def make_pdf(text: str = "CS 101 syllabus. Midterm exam October 14, 2026.") -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    content = document.tobytes()
    document.close()
    return content


def create_semester(client) -> str:
    response = client.post(
        "/api/semesters",
        headers=auth_headers(),
        json={
            "name": "Fall 2026",
            "start_date": "2026-08-24",
            "end_date": "2026-12-18",
            "timezone": "America/New_York",
        },
    )
    return response.json()["id"]


def test_upload_creates_one_independent_queued_job_per_pdf(app_client):
    client, _ = app_client
    semester_id = create_semester(client)

    response = client.post(
        f"/api/semesters/{semester_id}/syllabi",
        headers=auth_headers(),
        files=[
            ("files", ("cs101.pdf", BytesIO(make_pdf()), "application/pdf")),
            ("files", ("math200.pdf", BytesIO(make_pdf()), "application/pdf")),
        ],
    )

    assert response.status_code == 202
    payload = response.json()
    assert len(payload["jobs"]) == 2
    assert {job["status"] for job in payload["jobs"]} == {"queued"}
    assert len({job["id"] for job in payload["jobs"]}) == 2

    jobs = client.get(
        f"/api/semesters/{semester_id}/jobs",
        headers=auth_headers(),
    )
    assert jobs.status_code == 200
    assert {job["filename"] for job in jobs.json()} == {"cs101.pdf", "math200.pdf"}


def test_upload_rejects_non_pdf_files(app_client):
    client, _ = app_client
    semester_id = create_semester(client)

    response = client.post(
        f"/api/semesters/{semester_id}/syllabi",
        headers=auth_headers(),
        files=[("files", ("notes.txt", BytesIO(b"not a pdf"), "text/plain"))],
    )

    assert response.status_code == 415


def test_upload_rejects_more_than_ten_files(app_client):
    client, _ = app_client
    semester_id = create_semester(client)
    files = [
        ("files", (f"course-{index}.pdf", BytesIO(make_pdf()), "application/pdf"))
        for index in range(11)
    ]

    response = client.post(
        f"/api/semesters/{semester_id}/syllabi",
        headers=auth_headers(),
        files=files,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Upload at most 10 PDF files at a time."
