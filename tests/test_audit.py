"""Unit and API contract coverage for Phase 3."""

from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from audit import build_audit, normalize_code, term_key
from main import app, catalog
from student_api import students


def history(code="PRE100", term="25F", credits=3, status="Completed"):
    return dict(course_code=code, term=term, credits_earned=credits, status=status)


def plan(code="ADV200", term="26F"):
    return dict(course_code=code, term=term)


@pytest.fixture
def data():
    return {
        "PRE100": dict(credits=3, prerequisites=[], cross_listed=[]),
        "ADV200": dict(credits=4.5, prerequisites=["PRE 100"], cross_listed=["ALT-200"]),
        "ALT200": dict(credits=4.5, prerequisites=[], cross_listed=[]),
    }


@pytest.mark.parametrize("code", ["pre100", "Pre-100", "p r e 1 0 0", "PRE 100"])
def test_normalize(code):
    assert normalize_code(code) == "PRE100"


@pytest.mark.parametrize("term,valid", [
    ("25F", True), ("26W", True), ("26SP", True), ("26S", True),
    ("26F", False), ("27W", False),
])
def test_strictly_earlier_prerequisites(data, term, valid):
    result = build_audit("a", {"history": [history(term=term)], "plan": [plan()]}, data)
    assert (result["status"] == "ok") is valid
    assert bool(result["timeline_validation"][0]["errors"]) is not valid


def test_term_order_and_grouping(data):
    terms = ["26F", "26S", "26SP", "26W", "25F"]
    result = build_audit("a", {"history": [], "plan": [plan(term=t) for t in terms] + [plan()]}, data)
    timeline = result["timeline_validation"]
    assert [group["term"] for group in timeline] == ["25F", "26W", "26SP", "26S", "26F"]
    assert len(timeline[-1]["errors"]) == 2
    assert timeline[0]["errors"] == [{
        "type": "MISSING_PREREQUISITE", "course_code": "ADV200", "message": "Missing prerequisite: PRE100",
    }]


@pytest.mark.parametrize("status", ["Attempted", "In-Progress", "Failed", "completed"])
def test_only_completed_satisfies_prerequisite(data, status):
    result = build_audit("a", {"history": [history(status=status)], "plan": [plan()]}, data)
    assert result["status"] == "warning"
    assert result["credit_summary"]["total_earned"] == 0


def test_planned_prerequisites_do_not_satisfy_history_requirement(data):
    result = build_audit("a", {"history": [], "plan": [plan("PRE100", "25F"), plan()]}, data)
    assert result["status"] == "warning"


def test_retake_and_duplicate_credits_are_order_independent(data):
    attempts = [history("pre-100", "24F", 0, "Attempted"),
                history("PRE 100", "25W", 3), history("pre100", "26F", 3),
                history("OTHER100", "24W", 6), history("FAIL100", "24W", 9, "Failed")]
    for rows in (attempts, attempts[::-1]):
        result = build_audit("a", {"history": rows, "plan": [plan()]}, data)
        assert result["status"] == "ok"
        assert result["credit_summary"] == {"total_earned": 9, "total_planned": 4.5, "total_remaining_for_graduation": 106.5}


def test_cross_list_conflict_both_directions_and_formatting(data):
    for planned, completed in [("adv-200", "alt 200"), ("ALT200", "ADV 200")]:
        result = build_audit("a", {"history": [history(completed), history()],
                                   "plan": [plan(planned)]}, data, strict=True)
        assert result["status"] == "failed"
        assert result["cross_list_violations"] == [{
            "type": "CROSS_LIST_CONFLICT", "course_code": normalize_code(planned),
            "message": f"Cross-listed with completed course {normalize_code(completed)}",
        }]


def test_failed_cross_list_attempt_does_not_conflict(data):
    result = build_audit("a", {"history": [history(), history("ALT200", status="Attempted")],
                               "plan": [plan()]}, data)
    assert result["cross_list_violations"] == []
    assert result["status"] == "ok"


def test_empty_and_credit_floor_and_no_mutations(data):
    record = {"history": [], "plan": []}
    assert build_audit("a", record, data, True) == {
        "student_id": "a", "status": "ok", "timeline_validation": [],
        "cross_list_violations": [], "credit_summary": {"total_earned": 0, "total_planned": 0, "total_remaining_for_graduation": 120},
    }
    record = {"history": [history(credits=120)], "plan": [plan()]}
    before = deepcopy((record, data))
    assert build_audit("a", record, data)["credit_summary"]["total_remaining_for_graduation"] == 0
    assert (record, data) == before


@pytest.mark.parametrize("term", ["2026F", "26X", "F26", "26sp", ""])
def test_invalid_terms(term):
    with pytest.raises(ValueError, match="Invalid audit term"):
        term_key(term)


@pytest.fixture
def client():
    old_catalog, old_students = deepcopy(catalog), deepcopy(students)
    catalog.clear()
    students.clear()
    with TestClient(app) as instance:
        yield instance
    catalog.clear()
    catalog.update(old_catalog)
    students.clear()
    students.update(old_students)


def import_student(client, student="a"):
    return client.post(f"/api/v1/students/{student}/history/import", files={
        "file": ("transcript.html", b"<table></table>", "text/html"),
    })


def test_api_phase1_phase2_lifecycle(client):
    sample = Path(__file__).resolve().parents[1] / "sample_catalog.html"
    assert client.post("/api/v1/admin/catalog/import", files={"file": ("c.html", sample.read_bytes())}).status_code == 200
    assert import_student(client).status_code == 201
    base = "/api/v1/students/a"
    assert client.post(base + "/plan", json={"planned_courses": [plan("cosc-3506")]}).status_code == 200
    before = client.get(base + "/profile").json()
    for query, status in [("", "warning"), ("?strict=false", "warning"), ("?strict=true", "failed")]:
        response = client.get(base + "/audit-report" + query)
        assert response.status_code == 200
        assert response.json()["status"] == status
        assert set(response.json()) == {"student_id", "status", "timeline_validation", "cross_list_violations", "credit_summary"}
    assert client.get(base + "/profile").json() == before
    assert client.put(base + "/history", json={"history": [history("COSC 2007")]}).status_code == 200
    assert client.get(base + "/audit-report?strict=true").json()["status"] == "ok"
    assert client.put(base + "/plan", json={"planned_courses": [plan("ITEC3506")]}).status_code == 200
    assert client.get(base + "/audit-report").json()["credit_summary"]["total_planned"] == 3
    assert import_student(client).status_code == 201
    assert client.get(base + "/audit-report").json()["status"] == "warning"
    assert client.delete(base + "/plan").status_code == 200
    assert client.delete(base + "/history").status_code == 200
    assert client.get(base + "/audit-report").json()["status"] == "ok"
    assert import_student(client, "b").status_code == 201
    assert client.get("/api/v1/students/b/audit-report").json()["credit_summary"]["total_earned"] == 0


def test_api_errors_and_openapi(client, data):
    assert client.get("/api/v1/students/missing/audit-report").status_code == 404
    import_student(client)
    base = "/api/v1/students/a"
    assert client.get(base + "/audit-report?strict=invalid").status_code == 422
    catalog.update(data)
    for entry, message in [(plan("UNKNOWN100"), "not in the catalog"),
                           (plan(term="invalid"), "Invalid audit term")]:
        client.post(base + "/plan", json={"planned_courses": [entry]})
        response = client.get(base + "/audit-report")
        assert response.status_code == 422
        assert message in response.json()["detail"]
    client.post(base + "/plan", json={"planned_courses": [plan()]})
    catalog["ADV200"]["credits"] = "variable"
    assert client.get(base + "/audit-report").status_code == 422
    operation = client.get("/openapi.json").json()["paths"]["/api/v1/students/{student_id}/audit-report"]["get"]
    strict = next(p for p in operation["parameters"] if p["name"] == "strict")
    assert strict["schema"]["type"] == "boolean"
    assert strict["schema"]["default"] is False


@pytest.mark.parametrize("query,expected_status", [
    ("", "warning"), ("?strict=false", "warning"), ("?strict=true", "failed"),
])
def test_exact_professor_response_contract(client, data, query, expected_status):
    catalog.update(data)
    import_student(client)
    base = "/api/v1/students/a"
    # History is deliberately out of order, with formatting variants and a
    # later passing retake that cannot satisfy the earlier planned terms.
    attempts = [history("pre-100", "26S", 3),
                history("PRE 100", "25F", 99, "Attempted"),
                history("alt 200", "25F", 4),
                history("PRE100", "27W", 3),
                history("ALT-200", "26W", 4)]
    assert client.put(base + "/history", json={"history": attempts}).status_code == 200
    assert client.post(base + "/plan", json={"planned_courses": [
        plan("aDv-200", term) for term in ["26F", "26S", "26W", "26SP"]
    ]}).status_code == 200
    before = client.get(base + "/profile").json()
    response = client.get(base + "/audit-report" + query)
    assert response.status_code == 200
    assert response.json() == {
        "student_id": "a", "status": expected_status,
        "timeline_validation": [
            {"term": term, "errors": [{
                "course_code": "ADV200", "type": "MISSING_PREREQUISITE",
                "message": "Missing prerequisite: PRE100",
            }]} for term in ["26W", "26SP", "26S"]
        ] + [{"term": "26F", "errors": []}],
        "cross_list_violations": [{
            "course_code": "ADV200", "type": "CROSS_LIST_CONFLICT",
            "message": "Cross-listed with completed course ALT200",
        } for _ in range(4)],
        "credit_summary": {
            "total_earned": 7, "total_planned": 18,
            "total_remaining_for_graduation": 95,
        },
    }
    assert client.get(base + "/profile").json() == before


def test_each_missing_prerequisite_has_exact_message(data):
    data["ADV200"]["prerequisites"] = ["pre-100", "oThEr 101"]
    result = build_audit("a", {"history": [], "plan": [plan()]}, data)
    assert result["timeline_validation"] == [{"term": "26F", "errors": [
        {"course_code": "ADV200", "type": "MISSING_PREREQUISITE",
         "message": f"Missing prerequisite: {code}"}
        for code in ["PRE100", "OTHER101"]
    ]}]


def test_failed_attempt_after_completion_does_not_remove_earned_credit(data):
    record = {"history": [history("PRE-100", "25F", 3),
                          history("pre 100", "26W", 99, "Failed")], "plan": [plan()]}
    assert build_audit("a", record, data, strict=True)["status"] == "ok"
    assert build_audit("a", record, data)["credit_summary"]["total_earned"] == 3
