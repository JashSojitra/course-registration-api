"""End-to-end API tests for course catalog import and retrieval."""

from pathlib import Path

from fastapi.testclient import TestClient

from main import app


client = TestClient(app)

PROJECT_ROOT = Path(__file__).parent.parent
FAKE_CATALOG = (PROJECT_ROOT / "tests" / "fixtures" / "fake_catalog.html").read_text(
    encoding="utf-8"
)
SAMPLE_CATALOG = (PROJECT_ROOT / "sample_catalog.html").read_bytes()


def _import_fake_catalog():
    return client.post(
        "/api/v1/admin/catalog/import",
        files={"file": ("fake_catalog.html", FAKE_CATALOG, "text/html")},
    )


def test_root_confirms_api_is_running() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {"message": "Course Catalog API is running"}


def test_import_then_retrieve_course_with_both_code_forms() -> None:
    import_response = _import_fake_catalog()

    assert import_response.status_code == 200
    assert import_response.json() == {
        "message": "Catalog imported successfully",
        "courses_imported": 2,
    }

    compact_response = client.get("/api/v1/catalog/courses/quux275b")
    spaced_response = client.get("/api/v1/catalog/courses/QUUX%20275B")

    assert compact_response.status_code == 200
    assert spaced_response.status_code == 200
    assert compact_response.json() == spaced_response.json() == {
        "course_code": "QUUX 275B",
        "title": "Applied Imaginary Systems",
        "credits": 4.5,
        "prerequisites": ["ZORB 142", "XYLO 100"],
        "cross_listed_courses": ["PLUM 275B", "WREN 280"],
    }


def test_professor_sample_imports_with_required_response_schema() -> None:
    import_response = client.post(
        "/api/v1/admin/catalog/import",
        files={"file": ("catalog.html", SAMPLE_CATALOG, "text/html")},
    )

    assert import_response.status_code == 200
    assert import_response.json() == {
        "message": "Catalog imported successfully",
        "courses_imported": 5,
    }

    course_response = client.get("/api/v1/catalog/courses/COSC3506")

    assert course_response.status_code == 200
    assert course_response.json() == {
        "course_code": "COSC 3506",
        "title": "Software Systems Development",
        "credits": 3,
        "prerequisites": ["COSC 2007"],
        "cross_listed_courses": ["ITEC 3506"],
    }


def test_import_does_not_depend_on_filename_or_html_media_type() -> None:
    response = client.post(
        "/api/v1/admin/catalog/import",
        files={
            "file": (
                "unrelated-name.bin",
                FAKE_CATALOG,
                "application/octet-stream",
            )
        },
    )

    assert response.status_code == 200
    assert response.json()["courses_imported"] == 2


def test_empty_markers_become_empty_arrays() -> None:
    _import_fake_catalog()

    response = client.get("/api/v1/catalog/courses/ZORB142")

    assert response.status_code == 200
    assert response.json()["prerequisites"] == []
    assert response.json()["cross_listed_courses"] == []


def test_unknown_course_returns_404() -> None:
    _import_fake_catalog()

    response = client.get("/api/v1/catalog/courses/FAKE%20999")

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_empty_upload_returns_400() -> None:
    response = client.post(
        "/api/v1/admin/catalog/import",
        files={"file": ("empty.html", b"", "text/html")},
    )

    assert response.status_code == 400
    assert "empty" in response.json()["detail"].lower()


def test_html_without_required_table_returns_400() -> None:
    _import_fake_catalog()

    response = client.post(
        "/api/v1/admin/catalog/import",
        files={"file": ("bad.html", "<html><p>No catalog</p></html>", "text/html")},
    )

    assert response.status_code == 400
    assert "no table" in response.json()["detail"].lower()

    # Parsing happens before replacement, so a rejected upload cannot erase a
    # previously valid in-memory catalog.
    preserved_course = client.get("/api/v1/catalog/courses/ZORB142")
    assert preserved_course.status_code == 200


def test_openapi_declares_required_multipart_file_field() -> None:
    schema = app.openapi()
    operation = schema["paths"]["/api/v1/admin/catalog/import"]["post"]
    request_body = operation["requestBody"]
    multipart_schema = request_body["content"]["multipart/form-data"]["schema"]
    component_name = multipart_schema["$ref"].rsplit("/", 1)[-1]
    component = schema["components"]["schemas"][component_name]

    assert request_body["required"] is True
    assert component["required"] == ["file"]
    assert component["properties"]["file"]["type"] == "string"
    assert (
        component["properties"]["file"]["contentMediaType"]
        == "application/octet-stream"
    )
