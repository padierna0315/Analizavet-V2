# Tasks: Patient Raw Data Provenance

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~420-460 |
| 400-line budget risk | Medium |
| Chained PRs recommended | Yes |
| Suggested split | PR 1 (Foundation) → PR 2 (Capture Hooks) → PR 3 (Linking + Archive + UI) |
| Delivery strategy | ask-on-risk |
| Chain strategy | pending |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: pending
400-line budget risk: Medium

### Suggested Work Units

| Unit | Goal | Likely PR |
|------|------|-----------|
| 1 | Foundation: Model + Migration + ProvenanceRecorder | PR 1 |
| 2 | Capture Hooks: Wire AppSheet, Ozelle, Fujifilm | PR 2 |
| 3 | Linking, Archive Integration, UI | PR 3 |

## Phase 1: Foundation

- [ ] 1.1 Create `app/shared/models/raw_data_log.py` — RawDataLog SQLModel with source (enum), raw_data (Text), nullable FKs (ondelete='SET NULL'), indexes on patient_id, test_result_id, session_code, source.
- [ ] 1.2 Create `app/services/provenance_recorder.py` — ProvenanceRecorder.record() with try/except wrapping, DB add+flush, never raises on failure.
- [ ] 1.3 Alembic migration `xxxx_add_raw_data_log.py` — upgrade + downgrade, all columns and indexes.
- [ ] 1.4 Tests: model validation, recorder happy path + DB error isolation.

## Phase 2: Capture Hooks

- [ ] 2.1 AppSheet hook: in `fetch_active_patients()`, after `response.json()`, call recorder with source='appsheet', raw_data=json, session_code before parsing.
- [ ] 2.2 Dramatiq actor `capture_ozelle_raw()` in `app/tasks/provenance_actors.py` — fire-and-forget, no retry, source='ozelle'.
- [ ] 2.3 Ozelle hook: in `app/satellites/ozelle/mllp_server.py`, enqueue actor with raw HL7 text before parse_hl7_message().
- [ ] 2.4 Dramatiq actor `capture_fujifilm_raw()` in `provenance_actors.py` — same pattern, source='fujifilm'.
- [ ] 2.5 Fujifilm hook: in `app/satellites/fujifilm/adapter.py` _process_message(), enqueue actor before parsing.
- [ ] 2.6 Tests: non-blocking enqueue, all 3 hooks fire correctly, error isolation.

## Phase 3: Linking + Archive + UI

- [ ] 3.1 Lazy linking: in `app/domains/reception/service.py`, backfill RawDataLog.patient_id by session_code after patient creation.
- [ ] 3.2 Archive integration: include RawDataLog rows in PatientArchive.snapshot_data.raw_data_logs before retirement.
- [ ] 3.3 Router: `app/domains/provenance/router.py` — GET /patients/{id}/raw-data returning HTMX fragment.
- [ ] 3.4 Template: `app/templates/provenance/raw_data_view.html` — source-grouped cards, scrollable pre block, timestamps, status badge.
- [ ] 3.5 Patient detail: add "Ver datos crudos" HTMX link in `app/templates/patients/detail.html`.
- [ ] 3.6 Tests: lazy linking backfill, archive includes rows, router returns HTMX, template renders 0/1/multi-source rows.
