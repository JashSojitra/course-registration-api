"""Phase 2 student academic history and future-plan API."""
from __future__ import annotations

import re
from typing import Literal

from bs4 import BeautifulSoup
from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1/students/{student_id}")
# Separate state for each student, independent of the Phase 1 course catalog.
students: dict[str, dict[str, list[dict]]] = {}

class HistoryEntry(BaseModel):
    course_code: str
    term: str
    credits_earned: int
    status: str

class HistoryBody(BaseModel):
    history: list[HistoryEntry] = Field(default_factory=list)

class PlanEntry(BaseModel):
    course_code: str
    term: str

class PlanBody(BaseModel):
    planned_courses: list[PlanEntry] = Field(default_factory=list)

def _student(student_id: str) -> dict[str, list[dict]]:
    if student_id not in students:
        raise HTTPException(status_code=404, detail="Student not found")
    return students[student_id]

def _grade_rank(grade: str) -> int:
    value = grade.strip()
    if re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)\s*%?", value):
        return 2
    if re.fullmatch(r"[A-F][+-]?", value, re.IGNORECASE) and value.upper() != "P":
        return 1
    return 0

def _credits(raw: str) -> int:
    try:
        return int(raw.strip())
    except (ValueError, TypeError):
        return 0

def parse_transcript(html: bytes) -> list[dict]:
    """Extract eligible transcript rows, retaining the strongest duplicate."""
    soup = BeautifulSoup(html, "html.parser")
    best: dict[tuple[str, str], tuple[tuple[int, int], dict]] = {}
    required = {"status", "course", "grade", "term", "credits"}

    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        header_index = None
        cols: dict[str, int] = {}
        for i, row in enumerate(rows):
            cells = row.find_all(["th", "td"], recursive=False)
            candidate = {
                re.sub(r"\s+", "", cell.get_text(" ", strip=True)).casefold(): j
                for j, cell in enumerate(cells)
            }
            if required <= candidate.keys():
                header_index, cols = i, candidate
                break
        if header_index is None:
            continue
        for row in rows[header_index + 1:]:
            cells = row.find_all(["td", "th"], recursive=False)
            if not cells or max(cols[key] for key in required) >= len(cells):
                continue
            val = {name: cells[cols[name]].get_text(" ", strip=True) for name in required}
            if val["status"] not in {"Completed", "In-Progress", "Attempted"} or not val["term"]:
                continue
            if not val["course"]:
                continue
            course = {
                "course_code": val["course"],
                "term": val["term"],
                "credits_earned": _credits(val["credits"]),
                "status": val["status"],
            }
            key = (course["course_code"], course["term"])
            rank = (_grade_rank(val["grade"]), course["credits_earned"])
            if key not in best or rank > best[key][0]:
                best[key] = (rank, course)
    return [item[1] for item in best.values()]

@router.post("/history/import", status_code=201)
async def import_history(student_id: str, file: UploadFile = File(...)):
    body = await file.read()
    if not body.strip():
        raise HTTPException(status_code=400, detail="Empty transcript")
    history = parse_transcript(body)
    previous = students.get(student_id)
    # Import replaces history but must not erase a student's previously saved plan.
    students[student_id] = {"history": history, "plan": previous["plan"] if previous else []}
    return {"status": "success", "past_courses_imported": len(history)}

@router.put("/history")
def replace_history(student_id: str, body: HistoryBody):
    _student(student_id)["history"] = [item.model_dump() for item in body.history]
    return {"status": "success", "message": "Academic history updated successfully"}

@router.delete("/history")
def clear_history(student_id: str):
    _student(student_id)["history"] = []
    return {"status": "success"}

@router.post("/plan")
def post_plan(student_id: str, body: PlanBody):
    record = _student(student_id)
    record["plan"] = [item.model_dump() for item in body.planned_courses]
    return {"status": "success", "planned_courses_saved": len(record["plan"])}

@router.put("/plan")
def replace_plan(student_id: str, body: PlanBody):
    record = _student(student_id)
    record["plan"] = [item.model_dump() for item in body.planned_courses]
    return {"status": "success", "planned_courses_saved": len(record["plan"])}

@router.delete("/plan")
def clear_plan(student_id: str):
    _student(student_id)["plan"] = []
    return {"status": "success"}

@router.get("/profile")
def get_profile(student_id: str):
    record = _student(student_id)
    return {"student_id": student_id, "history": record["history"], "plan": record["plan"]}
