"""FastAPI application for importing and querying an in-memory course catalog."""

from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup
from fastapi import FastAPI, File, HTTPException, UploadFile, status


app = FastAPI(title="Course Catalog Ingestion API", version="1.0.0")

# Catalog keys are compact, uppercase course codes (for example, "COSC3506").
# Values keep a readable, consistently formatted representation of each code.
catalog: dict[str, dict[str, Any]] = {}

REQUIRED_COLUMNS = {
    "course_code",
    "title",
    "credits",
    "prerequisites",
    "cross_listed_courses",
}

EMPTY_VALUES = {
    "",
    "-",
    "--",
    "—",
    "n/a",
    "na",
    "nil",
    "none",
    "not applicable",
    "no prerequisite",
    "no prerequisites",
    "no cross listing",
    "no cross listings",
}

# The department part is deliberately generic; no real or sample department is
# embedded in the parser. Separators are accepted but normalized in responses.
COURSE_CODE_PATTERN = re.compile(
    r"(?<![A-Z0-9])([A-Z][A-Z&]{1,11})\s*(?:-|\s)?\s*(\d{2,5}[A-Z]?)(?![A-Z0-9])",
    re.IGNORECASE,
)


def _header_key(value: str) -> str | None:
    """Map a human-readable table header to an internal field name."""

    header = re.sub(r"[^a-z0-9]+", "", value.casefold())

    if header in {"code", "coursecode", "coursenumber", "courseno", "catalogcode"}:
        return "course_code"
    if header in {"title", "coursetitle", "name", "coursename"}:
        return "title"
    if "credit" in header or header in {"units", "unit"}:
        return "credits"
    if header.startswith("prereq") or "prerequisite" in header:
        return "prerequisites"
    if (
        "crosslist" in header
        or "crosslisted" in header
        or header in {"equivalent", "equivalents", "equivalentcourses"}
    ):
        return "cross_listed_courses"
    return None


def _normalize_key(course_code: str) -> str:
    """Return the lookup form of a course code."""

    return re.sub(r"[^A-Z0-9]", "", course_code.upper())


def _extract_course_codes(value: str) -> list[str]:
    """Extract unique course codes from free-form cell text."""

    cleaned = " ".join(value.split()).strip()
    if cleaned.casefold().strip(" .;:") in EMPTY_VALUES:
        return []

    codes: list[str] = []
    seen: set[str] = set()
    for match in COURSE_CODE_PATTERN.finditer(cleaned):
        display_code = f"{match.group(1).upper()} {match.group(2).upper()}"
        key = _normalize_key(display_code)
        if key not in seen:
            seen.add(key)
            codes.append(display_code)
    return codes


def _parse_credits(value: str) -> int | float | str:
    """Convert ordinary numeric credit values while preserving unusual formats."""

    cleaned = " ".join(value.split()).strip()
    numeric_match = re.fullmatch(
        r"(\d+(?:\.\d+)?)\s*(?:credits?|units?)?", cleaned, re.IGNORECASE
    )
    if not numeric_match:
        return cleaned

    numeric_value = float(numeric_match.group(1))
    return int(numeric_value) if numeric_value.is_integer() else numeric_value


def _parse_catalog(html: bytes) -> dict[str, dict[str, Any]]:
    """Parse all compatible HTML tables into a new in-memory catalog."""

    soup = BeautifulSoup(html, "html.parser")
    parsed: dict[str, dict[str, Any]] = {}
    matching_table_found = False

    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        header_row_index: int | None = None
        columns: dict[str, int] = {}

        # Searching rather than assuming the first row permits captions and
        # multi-row page furniture before the actual table headings.
        for row_index, row in enumerate(rows):
            cells = row.find_all(["th", "td"], recursive=False)
            candidate: dict[str, int] = {}
            for column_index, cell in enumerate(cells):
                field = _header_key(cell.get_text(" ", strip=True))
                if field is not None and field not in candidate:
                    candidate[field] = column_index
            if REQUIRED_COLUMNS.issubset(candidate):
                header_row_index = row_index
                columns = candidate
                matching_table_found = True
                break

        if header_row_index is None:
            continue

        for row in rows[header_row_index + 1 :]:
            cells = row.find_all(["td", "th"], recursive=False)
            if not cells or max(columns.values()) >= len(cells):
                continue

            values = {
                field: cells[index].get_text(" ", strip=True)
                for field, index in columns.items()
            }
            if not any(value.strip() for value in values.values()):
                continue

            course_matches = _extract_course_codes(values["course_code"])
            if not course_matches:
                # Footer rows and section labels are ignored; a structurally
                # valid table may contain more than course records.
                continue

            course_code = course_matches[0]
            title = " ".join(values["title"].split()).strip()
            credits = _parse_credits(values["credits"])
            if not title or credits == "":
                raise ValueError(f"Course {course_code} is missing a title or credits value.")

            key = _normalize_key(course_code)
            if key in parsed:
                raise ValueError(f"Duplicate course code found: {course_code}.")

            parsed[key] = {
                "course_code": course_code,
                "title": title,
                "credits": credits,
                "prerequisites": _extract_course_codes(values["prerequisites"]),
                "cross_listed_courses": _extract_course_codes(
                    values["cross_listed_courses"]
                ),
            }

    if not matching_table_found:
        raise ValueError(
            "No table with Course Code, Title, Credits, Prerequisites, and "
            "Cross-listed Courses columns was found."
        )
    if not parsed:
        raise ValueError("The catalog does not contain any valid course rows.")

    return parsed


@app.get("/")
def root() -> dict[str, str]:
    """Return a small health message."""

    return {"message": "Course Catalog API is running"}


@app.post("/api/v1/admin/catalog/import")
async def import_catalog(file: UploadFile = File(...)) -> dict[str, Any]:
    """Import an HTML course catalog, replacing the current in-memory data."""

    contents = await file.read()
    if not contents or not contents.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The uploaded catalog file is empty.",
        )

    try:
        imported_catalog = _parse_catalog(contents)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    catalog.clear()
    catalog.update(imported_catalog)
    return {
        "message": "Catalog imported successfully",
        "courses_imported": len(catalog),
    }


@app.get("/api/v1/catalog/courses/{course_code}")
def get_course(course_code: str) -> dict[str, Any]:
    """Retrieve one course with space-insensitive code matching."""

    course = catalog.get(_normalize_key(course_code))
    if course is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Course '{course_code}' was not found.",
        )
    return course
