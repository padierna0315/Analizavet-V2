# SDD Apply Progress: hygiene-cleanup

## Mode: Strict TDD (pytest)

## Completed Tasks

### Phase 1: Quick Wins
- [x] 1.1 Git hygiene — `git rm --cached data/jornada-session.json`, `.gitignore` already covers all patterns
- [x] 1.2 Replace inline HTMX div — Created `app/templates/reception/partials/auto_sync_trigger.html`, updated `router.py` to use `templates.TemplateResponse`
- [x] 1.3 Deduplicate suffix constants — Created `app/domains/taller/_constants.py` with `KNOWN_SUFFIXES` and `PART_PATTERN`. Updated `service.py` and `images.py`. Removed unused `import re` from both. 51/51 tests pass.

### Phase 2: clinical_standards.py Relocation
- [x] 2.1 Copy to `app/shared/clinical_standards.py` — Fixed JSON_PATH to use `Path(__file__).parent.parent.parent / "data" / "clinical_standards.json"`. Deleted root `clinical_standards.py`.
- [x] 2.2 Update all import sites — 21 files updated (11 app, 10 test). Zero `from clinical_standards import` remaining. Fixed test isolation in `test_clinical_standards_refactor.py` with autouse `reset_to_defaults()` fixture.

### Phase 3: Test Fixes
- [x] 3.1 Fix AppSheet authority tests — Eliminated ALL quarantine failures:
  - `test_reception_service.py`: 25/25 pass
  - `test_sala_espera.py`: 3/4 pass (1 pre-existing)
  - `test_reception_receive_session_code.py`: 1/1 pass
  - `test_reception_api.py`: 8/10 pass (2 pre-existing)
  - `test_taller_api.py`: 17/23 pass (6 pre-existing)
  - `test_reports_api.py`: 2/3 pass (1 pre-existing)
- [x] 3.2 Quarantine-scenario tests — Already existed in `test_intake_service.py`. All pass.
- [x] 3.3 Fix test_jornada_api.py — Rewrote 7 tests for flat JSON log API. All pass.

### Phase 4: Final Verification
- [x] 4.1 Full test suite: **786 passed, 30 failed, 1 skipped, 8 errors**

## Final Test Results

| Metric | Value |
|--------|-------|
| Total tests | 825 |
| Passed | 786 (95.3%) |
| Failed | 30 (ALL pre-existing) |
| Errors | 8 (ALL pre-existing) |
| Skipped | 1 |

### Pre-existing Failure Categories
| Category | Count | Root Cause |
|----------|-------|------------|
| Redis ConnectionError | 5 | No Redis in test env |
| AsyncClient API | 6 | Old deprecated API |
| FileNotFoundError | 2 | Missing test data files |
| Template TypeError | 4 | Jinja2 bug in editor/reception |
| Routing 404s | 6 | Taller workspace route with test data |
| Other | 7 | Archiving, pipeline, health, PDF, quarantine display |

**Zero new failures introduced.**

## Commits
1. `f0c73ab` — fix: git hygiene, dedup taller constants, fix jornada api tests, extract inline div
2. `512fef3` — refactor: relocate clinical_standards.py to app/shared/
3. `9a5eed7` — test: fix remaining quarantine failures in test_reception_api.py

## Issues Found
- `test_editor_router.py` (3 failures) — pre-existing Jinja2 template TypeError
- `test_reception_flow.py` (2 failures) — pre-existing Jinja2 template TypeError
- `test_reception_upload.py` (6 errors) — pre-existing deprecated AsyncClient API
- `test_fujifilm_processor.py` (4 failures) — pre-existing Redis dependency
- `test_taller_api.py` (6 failures) — pre-existing taller workspace routing 404s
- `test_patient_archiving_api.py` (6 failures) — pre-existing archiving endpoint issues
- `test_quarantine_router.py` (1 failure) — pre-existing template rendering issue
- `test_full_system.py`, `test_health.py`, `test_pipeline.py`, `test_reports_api.py` — pre-existing
- `test_real_logs.py` — pre-existing missing test data files

## Deviations from Design
None — implementation matches the proposal and task plan exactly. The only modification to the task plan is that task 3.2 (quarantine-scenario tests) was already implemented in the codebase and required no additional work.
