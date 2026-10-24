# Classroom Draft Output Release

Published on 2026-10-21 to the existing cloud application. This is an additive
output release, not a claim that automatic student recognition or educational
scoring has been validated.

## Scope

- Live changes: `demo2_course_analysis.py` and `demo2_course_page.py` only.
- Backend source: `.runtime/cloud_release_overrides/demo2_course_analysis.py`.
- Live-compatible page: `.runtime/cloud_draft_release/demo2_course_page.py`.
- The fuller V10 page in `.runtime/cloud_release_overrides` retains the same
  draft additions, but its other changes were not included in this release.
- Windows production, invitation settings, account credentials, video files,
  student records and existing observations were not reset or replaced.

## Output

The saved, source-bound technical manifest produces an automatic draft without
teacher records or an external model request. It contains a full timeline,
within-video visual-change/audio-energy indices, representative replay clips,
data-specific early/middle/late summaries and existing linked-student summaries.
The relative indices use the within-video 10th/90th percentile range. Constant
streams are represented separately; missing audio remains missing, not zero
student response. These are not attention, emotion, mastery or teacher scores.

Existing AI visible-behavior observations, teacher review, student records,
applicability checks and dual-track assessment remain available. The local draft
is placed first in the course view and exported report. No automatic association
of unnamed persons with student names or IEP documents was introduced.

## Verification

- Draft backend contracts: 41 passed; existing technical-summary tests: 31 passed.
- Dedicated UI checks: 12 passed; existing observation UI checks: 35 passed.
- Deployment-helper tests: 59 passed plus one backup-location regression test.
- Real cloud course: 108 segments, six selected clips, eight prose sections,
  1,044 characters. Existing model output: eight frames and 20 observations.
- The tested course has no confirmed student bindings or teacher records. The
  result does not represent a positive student-identity/IEP association test.
- Actual live browser: playable source metadata, clip seek, HTML report export,
  desktop/mobile overflow and JavaScript error checks passed.
- Four retained school logins passed; three peer-account reads and anonymous
  access were denied. The source workspace was unchanged by the checks.
- Public HTTPS is reachable with a trusted certificate. An unauthenticated
  request receives 401, consistent with the existing invitation gateway.

The first candidate screenshot run failed due to a test-runner mask argument;
the corrected candidate and the post-release live run both passed. No live code
had been replaced during that candidate failure.

## Evidence and Recovery

Private cloud screenshots and the JSON result are under
`/var/lib/rehabaffect/acceptance-private/classroom-draft-live-20261021-01`.
The local review copy is under
`.runtime/cloud_deploy_20261020/classroom-draft-live-20261021`.

The deployment helper initially refused the backup directory because it was
inside the application-owned data root. The helper now uses the independent
root-owned `/var/lib/rehabaffect-cloud-backups`; data-directory permissions were
not weakened. The successful update backup is
`v10-20261021T082523Z-fd635353`. Existing database data were not restored or
replaced, incomplete uploads were not cancelled, and ingress resumed normally.

Only accepted source files in `.runtime/cloud_draft_release/accepted.json` were
published. A future rollback must use the updated helper and this new backup
root; do not blindly restore an old database over newer school uploads.
