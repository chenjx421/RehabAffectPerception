# Demo2 1-10 Integration Handoff

Branch: `integration/demo2-1-10`

This branch combines the collaborator's core-data work (1, 2, 3, and 10) with
the evaluation/report work (4-9). It is a local integration branch only; it
does not deploy the cloud server or merge `master`.

## Integration contract

The stable join fields are `school_id`, `student_id`, `iep_summary_id`,
`course_id`, `task_id`, `evaluation_id`, and `report_id`. The server owns these
links. Names are display fields only.

`iep_summary_id` is the selected IEP document version ID. The dossier
`reference_id` remains a separate ID for the task/student/identity evidence
that authorized that document version. A current report may read a live,
authorized summary. A saved company report keeps only reference/document
version IDs and report evidence; it does not persist IEP summary text.

The report snapshot `report_id` is a database snapshot ID. The report content
ID is `content_report_id` (`report-<hash>`). They intentionally differ: the
snapshot is used for access-controlled download, while the content ID changes
when evaluation versions change.

## Main flow

1. The school account uploads and processes one task.
2. The school confirms the current media applicability and student sample.
3. The school records measurements and optional dual-track evaluation.
4. The course workspace joins current student evidence, evaluation records, and
   current authorized IEP references.
5. `GET /api/v1/demo2/course-analysis?task_id=...` saves an idempotent report
   snapshot for company administration.
6. Company administration lists reports at
   `/api/v1/demo2/admin/reports`; report downloads support `fmt=md` and
   `fmt=json`.

Withdrawn/expired dossier references, changed media revisions, revoked
identity bindings, withdrawn evaluations, and changed evaluation versions do
not contribute to a current report. A stale saved snapshot is rejected until
the school refreshes the course workspace. The dossier vault remains the only
source for sensitive IEP text.

## Files

- `src/rehab_affect/demo2_iep_context.py`: current authorized IEP adapter and
  non-sensitive snapshot projection.
- `src/rehab_affect/demo2_measurement_store.py`: course workspace join.
- `src/rehab_affect/demo2_evaluation_store.py`: server-side course and IEP link
  validation, plus stale-source filtering.
- `src/rehab_affect/demo2_report_store.py`: persistent snapshots, access checks,
  freshness checks, listing and downloads.
- `src/rehab_affect/scenario_lab_server.py`: the one shared integration file;
  it dispatches the course-analysis and report routes.
- `src/rehab_affect/demo2_portal.py`: company report table, pagination and
  download controls.

## Verification

Run from the repository root:

```powershell
$env:PYTHONPATH='src'
python -m pytest -q tests/test_demo2_iep_report_integration.py tests/test_demo2_report_store.py tests/test_demo2_course_analysis.py tests/test_demo2_evaluation_provenance.py tests/test_demo2_admin_refresh.py tests/test_demo2_portal_html.py
python -m compileall -q src tests
```

The integration tests use disposable SQLite databases, synthetic media and a
temporary Fernet key. They do not use student data, real media, credentials,
API keys or the production database.

## Next merge/rollback step

After the collaborator finishes 1, 2, 3 and 10, merge or cherry-pick the
validated core-data commits into this branch, rerun the focused command above,
then run the complete acceptance suite. Do not deploy until the complete flow
passes with an approved test database backup. To roll back this integration
batch, keep the parent commit and reset the test branch to it; do not touch the
production database or upload directory.
