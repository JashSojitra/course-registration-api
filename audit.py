"""Read-only academic audit over the existing catalog and student records."""

import re


def normalize_code(code: str) -> str:
    return code.upper().replace(" ", "").replace("-", "")


def term_key(term: str) -> tuple[int, int]:
    """Interpret the transcript's YYW/YYSP/YYS/YYF term notation."""
    match = re.fullmatch(r"(\d{2})(W|SP|S|F)", term)
    if match is None:
        raise ValueError(f"Invalid audit term '{term}'; expected YYW, YYSP, YYS, or YYF.")
    return int(match[1]), {"W": 0, "SP": 1, "S": 2, "F": 3}[match[2]]


def build_audit(student_id: str, record: dict, catalog: dict, strict: bool = False) -> dict:
    """Compute an audit without modifying history, plans, or catalog records.

    Duplicate completed attempts contribute their greatest earned credit value
    once. Planned entries retain their existing per-entry semantics.
    """
    courses = {normalize_code(key): value for key, value in catalog.items()}
    completed: dict[str, list[dict]] = {}
    for entry in record["history"]:
        if entry["status"] == "Completed":
            term_key(entry["term"])
            completed.setdefault(normalize_code(entry["course_code"]), []).append(entry)

    timeline: dict[str, list[dict]] = {}
    conflicts = []
    planned = 0
    for entry in sorted(record["plan"], key=lambda item: term_key(item["term"])):
        code = normalize_code(entry["course_code"])
        course = courses.get(code)
        if course is None:
            raise ValueError(f"Planned course '{entry['course_code']}' is not in the catalog.")
        credits = course["credits"]
        if not isinstance(credits, (int, float)):
            raise ValueError(f"Catalog credits for '{code}' are not numeric.")
        planned += credits
        errors = timeline.setdefault(entry["term"], [])
        for prerequisite in course["prerequisites"]:
            required = normalize_code(prerequisite)
            if not any(
                term_key(attempt["term"]) < term_key(entry["term"])
                for attempt in completed.get(required, [])
            ):
                errors.append({
                    "type": "MISSING_PREREQUISITE",
                    "course_code": code,
                    "message": f"Missing prerequisite: {required}",
                })
        # Cross-listing is an equivalence even if only one catalog row lists it.
        equivalents = {normalize_code(value) for value in course["cross_listed"]}
        equivalents.update(
            other_code for other_code, other in courses.items()
            if code in {normalize_code(value) for value in other["cross_listed"]}
        )
        for other_code in sorted(equivalents & completed.keys()):
            conflicts.append({
                "type": "CROSS_LIST_CONFLICT",
                "course_code": code,
                "message": f"Cross-listed with completed course {other_code}",
            })

    earned = sum(max(attempt["credits_earned"] for attempt in attempts)
                 for attempts in completed.values())
    issues = any(timeline.values()) or bool(conflicts)
    return {
        "student_id": student_id,
        "status": ("failed" if strict else "warning") if issues else "ok",
        "timeline_validation": [
            {"term": term, "errors": errors} for term, errors in timeline.items()
        ],
        "cross_list_violations": conflicts,
        "credit_summary": {
            "total_earned": earned, "total_planned": planned,
            "total_remaining_for_graduation": max(0, 120 - earned - planned),
        },
    }
