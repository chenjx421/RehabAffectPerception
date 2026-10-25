# Student dossier implementation contract (2026-09-11)

This is the coordination contract for the five EXISTING visible RehabAffect tasks. Shared checkout: D:/GIT/RehabAffectPerception. Do not start extra tasks, change real student data, restart live8792, create public tunnels, commit, reset, or perform live write tests. Each role owns the listed files. Main integrates, deploys locally after isolated verification, and creates the PDF.

## Goal and boundaries

Use the existing `demo2_identity_students.student_id` as the canonical NEW student key, preserving owner_account_id + school scope. Link authorized IEP/assessment/support versions to confirmed identity evidence in uploaded video tasks. No name-based merges and NO automatic migration of legacy global `students`/documents. Old sensitive routes must be gated; existing nonsensitive video/manual-ROI/channel functionality preserved. Explain legacy files require explicit correct-student reimport, not that migration has already happened.

Teachers operate only their own account + school scope. Company admin gets operational counts/status/expiry only, NOT names, filenames, reference text, summaries or document bytes. No training permissions are granted. No external model/face/medical inference added. This is an auditable demo, not a declaration of legal compliance.

## Files and role ownership

- Database: NEW `src/rehab_affect/demo2_dossier_store.py`, NEW `tests/test_demo2_dossier_store.py`.
- AI/data: NEW `src/rehab_affect/demo2_dossier_vault.py`, NEW `tests/test_demo2_dossier_vault.py`; encryption/secure file lifecycle only, no model training.
- Backend: `scenario_lab_server.py`, `demo2_manager_gateway.py`, NEW `tests/test_demo2_dossier_api.py`; no other product files.
- Frontend: NEW `demo2_dossier.py`, NEW `tests/test_demo2_dossier_html.py`, minimal links in `demo2_identity.py` (student roster), `demo2_video_review.py` (task context), `demo2_portal.py` (admin counts link).
- Tests/release: NEW `scripts/qa_demo2_dossier_20260911.py` and `.js`, NEW `tests/test_demo2_dossier_security.py`; isolated fixtures, real browser screenshots and security audit; report findings to main without editing role files.
- Main: coordination, deployment, existing-report integration evaluation, PDF builder/docs/verification, any agreed cross-role fixes.

## Vault contract

`DossierVault(root: Path)` uses Fernet authenticated encryption. Public `seal(data:bytes)->bytes`, `open(data:bytes)->bytes`, `status()->dict` (no paths/key). `VaultError(code,message)` fixed safe messages.
Key: `REHAB_DEMO2_DOSSIER_KEY` when supplied; otherwise Windows DPAPI current-user protection, stored outside docs as DPAPI ciphertext in root parent secure key location. No plaintext key on disk, no secrets printed. Non-Windows without explicit key -> fail closed. Test injection via env key. Allow stdlib/installed cryptography, no pip/network. Strict local paths/no symlinks/reparse paths for managed files. Atomic key creation and independent-store reopen tests. Do not embed private plaintext in errors/logs.
DB passes root = records.upload_dir.parent / 'scoped_dossier_v1'. Vault key status may initialize local DPAPI on first new dossier access; live deployment handled by main. Database handles file UUID filenames, atomic writes and scoped access.

## Store contract

`DossierError(status,code,message)` and `Demo2DossierStore(records, identities=None)`; identities defaults Demo2IdentityStore(records). Same sqlite database, new tables only; idempotent schema migrations. No legacy DELETE/migration. Encrypted JSON blobs for authorization reference, source descriptions, filenames, notes, summaries; bytes encrypted on disk. Identity display_name may be read from canonical table for teacher responses, never duplicated in audit or admin output. No automatic OCR/parsing/untrusted execution.

Public methods:
- `student_workspace(token,student_id)->workspace`
- `save_authorization(token,payload)->authorization`
- `withdraw_authorization(token,payload)->result`
- `create_document(token,payload)->document`
- `document_download(token,document_id)->(bytes, filename, content_type)`; attachment only, no native/raw paths.
- `delete_document(token,payload)->result`
- `task_workspace(token,task_id)->workspace`
- `create_reference(token,payload)->reference`
- `reference_export(token,reference_id)->dict`
- `admin_summary(token)->dict`
- `cleanup_expired()->dict` system maintenance, only new tables/files. Called periodically by server and before dossier reads/writes. Failed unlink must remain deletion_pending and inaccessible, retry next sweep. Clear encrypted sensitive columns on expiry/withdrawal/deletion; retain minimum audit/tombstone IDs, event timestamps, generic reason codes. Reports/exports must not resurrect deleted content. No claim that backups are purged by the app.

Authorization POST exact fields:
`student_id, reference, storage_mode, valid_until, confirmed`
storage_mode = `summary_only` or `original_and_summary`; confirmed must literal true. Purpose server-fixed education_support; no training/company archive. valid_until ISO YYYY-MM-DD; future and <=60 days from now (pilot cap, not a legal retention rule). UI explains school's actual authorization must cover purpose/scope, attestation is not proof of legal consent. Replacing authorization revokes old material access; reject replacement until active prior authorization withdrawn to avoid silently changing purpose. Multiple expired/revoked historical records allowed, one live authorization per student.
Withdrawal fields: `student_id, authorization_id, confirmed` (true); active matching auth only, idempotent. Immediately block linked source/summary access and request file purge.

Document POST exact fields:
`student_id, authorization_id, document_type, document_date, source_ref, retain_until, summary, filename, content_base64, supersedes_id`
document_type = `iep`, `professional_assessment`, `five_domain`, `safety_support`.
document_date ISO YYYY-MM-DD <=today; retain_until future <=auth.valid_until (at most60daypilot).
summary object exact keys `learning_goals, support_methods, safety_notes, professional_conclusion`, strings <=2000 chars each; only teacher-entered approved information, medical conclusion cannot be model-generated. Source_ref <=200 chars required. For summary_only filename/content_base64 must empty. For original_and_summary optional original, but at least one nonblank summary or file required. Files <=8MiB decoded; allow .pdf .docx .png .jpg .jpeg .txt, validate base64, filename basename and magic/MIME; DOCX inspect zip metadata safely, reject zip bombs/macros, do not extract. No SVG/HTML/executable. Vault failures must produce503, no fallback plaintext. supersedes_id empty=new family, otherwise same student/type existing available version, do not update older content. Monotonic per-family version; reject competing successor409. Every version's retention independently enforced.

Document teacher public fields: `document_id,student_id,authorization_id,document_type,version,family_id,supersedes_id,status,source_ref,document_date,retain_until,summary,has_file,filename,created_at,available`. Sensitive fields empty/omitted on unavailable records. New metadata sha256 may be retained only if necessary and not public to admin. No filesystem paths.
Authorization public fields: `authorization_id,student_id,reference,storage_mode,valid_until,status,purpose`.
Student workspace: `{student:{student_id,display_name,student_code,class_name}, authorization:null|object, documents:[], references:[], vault:{available,mode}, policy:{max_retention_days:60,training_allowed:false}, legacy_notice:string}`.

Task workspace teacher only: `{task:{task_id,course_id,course_name,frame_revision}, students:[{student_id,display_name,confirmed_binding_count,documents:[]}],references:[],notice:string}`. Students ONLY with confirmed student bindings on current source/revision, scope/task owner valid. Raw expired/revoked bindings/source reprocess -> cannot create new references. Existing history stays labelled, never silently reassigned.
Create-reference POST exact: `task_id,student_id,frame_revision,document_ids,confirmed` true. At least1 version <=10; all authorized/available/same student. Server snapshots IDs, versions, course metadata, source sha/frame revision and active binding IDs/time; no duplicate plaintext summaries. New IEP version must not change previous references. Return/export identifies unavailable/deleted sources and revoked/outdated identity evidence. Missing evidence never becomes unqualified confirmed assignment. No LLM report generated here; this is a downloadable course-evidence record for downstream reports, not a new thousand-word analysis.
Delete-document POST: `student_id,document_id,confirmed` true. Immediate access revocation and physical deletion lifecycle.

Admin summary exact shape: `{totals:{authorization_count,active_authorization_count,document_count,available_document_count,expired_document_count,deletion_pending_count,reference_count,encrypted_file_bytes},channels:[{channel_no,document_count,available_document_count,deletion_pending_count,encrypted_file_bytes}],policy:{max_retention_days:60,training_allowed:false,raw_documents_visible:false},vault:{available,mode}}`; no diagnostic/source/student content. Audit only action+opaqueIDs+counts, no content/reference/filenames/student names. Transactions recheck actor/owner as needed.

## HTTP and page contract

Teacher pages: `/demo2/dossier?student_id=...` -> `demo2_dossier.render_student(account)`; `/demo2/course-dossier?task_id=...` -> `render_task(account)`.
Admin `/demo2/admin/dossiers` -> `render_admin(account)`.
Protected JSON prefix `/api/v1/demo2/dossier`.
GET `/student?student_id=...` -> `{ok:true,workspace}`; `/task?task_id=...` -> same; `/admin` -> `{ok:true,summary}`.
GET `/document?document_id=...` attachment bytes; `/reference?reference_id=...` downloadable JSON (scope and live policy recheck, no raw files).
POST `/authorization` -> `{ok:true,authorization}`; `/authorization/withdraw` -> `{ok:true,result}`; `/documents` -> `{ok:true,document}`; `/documents/delete` -> `{ok:true,result}`; `/references` -> `{ok:true,reference}`.
All teacher calls require school_uploader; admin only `/admin`, no student/doc/reference contents. Queries exact and duplicate reject. POST application/json only, <=12MiB body (8MiB filebase64), auth before body, no-store/private all. Extend private invitation gateway allowlist, same-origin protection remains. No new public endpoint. Deadline maintenance <=60sec loop with clean shutdown; no legacy sweep.

## UI and verification

Blue/white, practical and concise, use existing HTML helpers and local icons. Don't hardcode fake pupils/authorization. One child per dossier. Tabs: 资料与版本 / 授权与期限 / 课堂引用 as useful. Explicit authorization details in plain language, no hidden defaults or prechecked legal consent. Actual name selected before upload; storage mode summary_only never uploads selected file. Old library has no auto name migration. After withdrawals/mutations reread, no fabricated success. Network uncertainty requires refresh before retry. Destructive controls explicit confirm. Disabled explanations and return navigation required. Admin counts only.

Tests use isolated real SQLite + synthetic files; keys injected only to isolated fixture. Verify two owners/schools and admin cannot read, key absence/corruption, no plaintext at rest, expired/withdrawn/deleted source access rejected, oldreference versionstable, fakecrossstudent/task invalid, maintenance idempotent and no realDB paths. Browser executable headless-shell1243 exists; run serial, do not download browsers. Fonts/images local. Source code manually edited with apply_patch. Main will provide live read-only QA and PDF using synthetic authorized demo records, not real diagnosis information.
