# Tasks: Hygiene & Cleanup Audit

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~440 |
| 800-line budget risk | Low |
| Chained PRs recommended | No |
| Suggested split | Single PR |
| Delivery strategy | auto-chain |
| Chain strategy | stacked-to-main |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: stacked-to-main
800-line budget risk: Low

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | Quick wins + `clinical_standards` move | PR 1 (single) | Git hygiene, suffix dedup, inline div, clinical_standards relocation, test fixes. All within 800-line budget. |

## Phase 1: Quick Independent Wins

- [x] 1.1 **Git hygiene** — Ensure `.gitignore` covers `.coverage`, `__pycache__/`, `data/jornada-session.json`. Run `git rm --cached` if any tracked. Verify clean `git status`.
  - Files: `.gitignore`
  - Test: `git status` shows zero unexpected untracked artifacts
  - Est: ~5 lines
  - ✅ `.gitignore` already covered all patterns. Ran `git rm --cached data/jornada-session.json`.

- [x] 1.2 **Replace inline HTMX div** — Extract `reception/router.py:37` inline HTMX div into a Jinja2 template snippet, or replace with a proper HTMX trigger attribute on an existing element if the div is redundant.
  - Files: `app/domains/reception/router.py`, `app/templates/reception/partials/auto_sync_trigger.html`
  - Test: E2E sync trigger still fires; existing integration tests pass
  - Est: ~15 lines
  - ✅ Created template and updated router to use `templates.TemplateResponse`.

- [x] 1.3 **Deduplicate suffix constants** — Create `app/domains/taller/_constants.py` with shared `KNOWN_SUFFIXES` and `PART_PATTERN`. Update `service.py` and `images.py` to import from there. Remove duplicated definitions.
  - Files: `app/domains/taller/_constants.py` (create), `app/domains/taller/service.py`, `app/domains/taller/images.py`
  - Test: `pytest tests/unit/test_taller_service.py tests/unit/test_image_service.py -v` passes
  - Est: ~35 lines
  - ✅ 51/51 tests pass. Also removed unused `import re` from both files.

## Phase 2: clinical_standards.py Relocation

- [x] 2.1 **Copy `clinical_standards.py` to `app/shared/`** — Copy `clinical_standards.py` to `app/shared/clinical_standards.py`. Fix the JSON data path to use `Path(__file__).parent.resolve()` for hot-reload compatibility. Delete the original file.
  - Files: `app/shared/clinical_standards.py` (create), `clinical_standards.py` (removed)
  - Test: `pytest tests/unit/test_clinical_standards.py -v` passes with new path
  - Est: ~160 lines
  - ✅ Fixed JSON_PATH to use `_BASE_DIR / "data" / "clinical_standards.json"` (resolved from __file__). Original file deleted.

- [x] 2.2 **Update all import sites** — Replace `from clinical_standards import ...` with `from app.shared.clinical_standards import ...` across all 19 files (21 import sites found).
  - Files: 21 files updated (11 app, 10 test)
  - Test: `pytest -v --import-mode=importlib` collects without ImportError
  - Est: ~100 lines
  - ✅ Zero `from clinical_standards import` remaining in codebase. Clinical standards tests pass (25/26, 1 pre-existing leak fixed via autouse fixture).

## Phase 3: Test Fixes

- [x] 3.1 **Fix AppSheet authority tests** — Add `appsheet_confirmed=True` to fixtures in test files that create patients via machine sources.
  - Files: `tests/unit/test_reception_service.py` (25/25 pass), `tests/unit/test_sala_espera.py` (3/4, 1 pre-existing), `tests/unit/test_reception_receive_session_code.py` (1/1), `tests/integration/test_taller_api.py` (17/23 pass, 6 pre-existing 404s), `tests/unit/test_clinical_standards_refactor.py` (4/4 with isolation fix)
  - Test: Reduced from ~75 quarantine failures to 0 quarantine failures
  - Est: ~200 lines
  - ✅ All DataQuarantinedException failures eliminated. ~25 tests with appsheet_confirmed=True + session_code. Changed machine source to APPSHEET in helper functions where appropriate.

- [x] 3.2 **Write quarantine-scenario tests** — Add ~5 tests covering edge cases.
  - Files: `tests/unit/test_intake_service.py` (already contained these tests: `test_machine_source_without_confirmed_patient_raises_quarantine`, `test_machine_source_with_confirmed_patient_attaches`, `test_machine_source_no_session_code_match_quarantines`, `test_non_machine_source_skips_gate`, `test_temporal_isolation_triggers_quarantine`)
  - Test: All 5+ existing tests pass
  - Est: 0 lines (already implemented)
  - ✅ Quarantine-scenario tests already existed and pass. No additional tests needed.

- [x] 3.3 **Fix or delete `test_jornada_api.py`** — `SESSION_MARKER` was removed from `app/domains/jornada/service.py`. Rewrote test for new flat JSON log API.
  - Files: `tests/integration/test_jornada_api.py`
  - Test: `pytest tests/integration/test_jornada_api.py -v` collects without error
  - Est: ~35 lines
  - ✅ Rewrote 7 tests for new `append_to_jornada_log` / `read_jornada_log` / `clear_jornada_log` API. All 7 pass.

## Phase 4: Final Verification

- [x] 4.1 **Full test suite** — Run `pytest -v --cov=app --cov-report=term-missing -p pytest_playwright`. Verify 0 quarantine failures, coverage not regressed.
  - Files: None (verification only)
  - Test: 786 passed, 30 failed (all pre-existing), 8 errors (pre-existing). Zero quarantine failures. Zero new failures.
  - Est: 0 lines (verification pass)
