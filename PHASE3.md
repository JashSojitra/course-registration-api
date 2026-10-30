Phase 3 adds a read-only `GET /api/v1/students/{student_id}/audit-report`
using the existing catalog, history and plan dictionaries. `strict` is an optional
boolean query parameter, defaulting to false. Findings always return HTTP 200;
strict changes `warning` to `failed`. Unknown students retain the existing 404.

No assignment PDF or selftest.zip was found in the repository. The response
below follows the professor-specified nested fields and messages supplied in
the compliance review request. The Phase 4 grader is not Phase 3 verification
and was not used. Full compliance beyond the supplied requirements cannot be
verified without the Phase 3 assignment materials.

```json
{
  "student_id": "example",
  "status": "warning",
  "timeline_validation": [
    {"term": "26F", "errors": [
      {"course_code": "COSC3506", "type": "MISSING_PREREQUISITE", "message": "Missing prerequisite: COSC2007"}
    ]}
  ],
  "cross_list_violations": [
    {"course_code": "COSC3506", "type": "CROSS_LIST_CONFLICT", "message": "Cross-listed with completed course ITEC3506"}
  ],
  "credit_summary": {"total_earned": 3, "total_planned": 3, "total_remaining_for_graduation": 114}
}
```

Terms follow the existing transcript notation `YYW`, `YYSP`, `YYS`, `YYF`.
Timeline groups include every planned term, including groups with no errors.
Report course identifiers are uppercase with spaces and hyphens removed;
stored profile and catalog formatting is preserved.

Only exact `Completed` status counts. Completed attempts are deduplicated by
normalized course code, taking the greatest credits_earned value if duplicate
completed records disagree. A later completed retake can satisfy prerequisites
only for plans strictly after that completion. Planned entries never satisfy
prerequisites, and each saved planned entry contributes catalog credits.
Cross-listing is checked in either catalog direction, without inferring
transitive equivalences or counting equivalent courses as prerequisites.

Existing write models accept arbitrary terms, unknown course codes, and catalog
credit strings. Audit returns 422 for unrecognized planned courses, nonnumeric
planned credits, or invalid planned/completed terms rather than fabricating an
audit. These unspecified edge-case policies need comparison
against the assignment materials when available. Existing in-memory storage
and its restart/concurrent-write limitations remain.

Local checks (after installing `requirements-dev.txt`):

```powershell
python -m ruff check .
python -m pytest -m "not integration" --cov=main --cov=student_api --cov=audit --cov-report=term-missing --cov-fail-under=80
```

For live integration, start `python -m uvicorn main:app` and set
`API_BASE_URL=http://127.0.0.1:8000`, then run `python -m pytest -m integration`.
Use a disposable local process: integration tests replace its in-memory catalog.
CI runs separate lint/coverage and live-server integration jobs. Ruff checks
correctness rules while allowing existing legacy import and one-line layout.
