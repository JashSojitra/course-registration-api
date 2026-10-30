"""Real HTTP tests: set API_BASE_URL to target a locally running API."""

import os
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

pytestmark = pytest.mark.integration


@pytest.fixture
def api():
    url = os.environ.get("API_BASE_URL")
    if not url:
        pytest.skip("API_BASE_URL is required for live integration tests")
    with httpx.Client(base_url=url, timeout=10) as client:
        yield client


def test_live_catalog_history_plan_audit_lifecycle(api):
    assert api.get("/").status_code == 200
    catalog = Path(__file__).resolve().parents[1] / "sample_catalog.html"
    assert api.post("/api/v1/admin/catalog/import", files={"file": ("c.html", catalog.read_bytes())}).status_code == 200
    assert api.get("/api/v1/catalog/courses/cosc-3506").json()["credits"] == 3
    base = f"/api/v1/students/integration-{uuid4().hex}"
    assert api.get(base + "/audit-report").status_code == 404
    transcript = """<table><tr><th>Status</th><th>Course</th><th>Grade</th>
    <th>Term</th><th>Credits</th></tr>
    <tr><td>Completed</td><td>cosc-2007</td><td>A</td><td>25F</td><td>3</td></tr>
    <tr><td>Attempted</td><td>COSC2007</td><td>F</td><td>24W</td><td>0</td></tr>
    <tr><td>Completed</td><td>COSC 2007</td><td>A</td><td>26W</td><td>3</td></tr>
    </table>"""
    assert api.post(base + "/history/import", files={"file": ("t.html", transcript)}).status_code == 201
    assert api.post(base + "/plan", json={"planned_courses": [{"course_code": "COSC3506", "term": "26SP"}]}).status_code == 200
    report = api.get(base + "/audit-report?strict=true")
    assert report.status_code == 200
    assert report.json()["status"] == "ok"
    assert report.json()["credit_summary"] == {"total_earned": 3, "total_planned": 3, "total_remaining_for_graduation": 114}
    assert api.put(base + "/history", json={"history": [{"course_code": "ITEC3506", "term": "26W", "status": "Completed", "credits_earned": 3}]}).status_code == 200
    report = api.get(base + "/audit-report").json()
    assert report["status"] == "warning"
    assert report["timeline_validation"] == [{"term": "26SP", "errors": [{
        "course_code": "COSC3506", "type": "MISSING_PREREQUISITE",
        "message": "Missing prerequisite: COSC2007",
    }]}]
    assert report["cross_list_violations"] == [{
        "course_code": "COSC3506", "type": "CROSS_LIST_CONFLICT",
        "message": "Cross-listed with completed course ITEC3506",
    }]
    assert api.get(base + "/audit-report?strict=true").json()["status"] == "failed"
    assert api.put(base + "/plan", json={"planned_courses": []}).status_code == 200
    assert api.delete(base + "/history").status_code == 200
    assert api.delete(base + "/plan").status_code == 200
    assert api.get(base + "/profile").json()["history"] == []
    assert api.get(base + "/audit-report").json()["status"] == "ok"
