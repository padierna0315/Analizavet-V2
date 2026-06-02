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

- [ ] 1.1 **Git hygiene** — Ensure `.gitignore` covers `.coverage`, `__pycache__/`, `data/jornada-session.json`. Run `git rm --cached` if any tracked. Verify clean `git status`.
  - Files: `.gitignore`
  - Test: `git status` shows zero unexpected untracked artifacts
  - Est: ~5 lines

- [ ] 1.2 **Replace inline HTMX div** — Extract `reception/router.py:37` inline HTMX div into a Jinja2 template snippet, or replace with a proper HTMX trigger attribute on an existing element if the div is redundant.
  - Files: `app/domains/reception/router.py`, possibly `app/domains/reception/templates/` (create if needed)
  - Test: E2E sync trigger still fires; existing integration tests pass
  - Est: ~15 lines

- [ ] 1.3 **Deduplicate suffix constants** — Create `app/domains/taller/_constants.py` with shared `_KNOWN_SUFFIXES` and `_PART_PATTERN`. Update `service.py` and `images.py` to import from there. Remove duplicated definitions.
  - Files: `app/domains/taller/_constants.py` (create), `app/domains/taller/service.py`, `app/domains/taller/images.py`
  - Test: `pytest tests/unit/test_taller_service.py tests/unit/test_image_service.py -v` passes
  - Est: ~35 lines

## Phase 2: clinical_standards.py Relocation

- [ ] 2.1 **Copy `clinical_standards.py` to `app/shared/`** — Copy `clinical_standards.py` to `app/shared/clinical_standards.py`. Fix the JSON data path to use `Path(__file__).parent.resolve()` for hot-reload compatibility. Keep the original file as a redirect shim (or delete in the same commit if safe).
  - Files: `app/shared/clinical_standards.py` (create), `clinical_standards.py` (remove or shim)
  - Test: `pytest tests/unit/test_clinical_standards.py -v` passes with new path
  - Est: ~160 lines

- [ ] 2.2 **Update all import sites** — Replace `from clinical_standards import ...` with `from app.shared.clinical_standards import ...` across all 19 files (51 import statements). Also update any lazy imports.
  - Files: All 19 files from grep results + any additional found by scanning
  - Test: `pytest -v --import-mode=importlib` collects without ImportError
  - Est: ~100 lines

## Phase 3: Test Fixes

- [ ] 3.1 **Fix AppSheet authority tests** — Add `appsheet_confirmed=True` to fixtures in test files that create patients via machine sources. Target: eliminate the ~75 failures + 8 errors. Each fixture fix requires adding the flag before the machine-source code path.
  - Files: `tests/unit/test_intake_service.py`, `tests/unit/test_gatekeeper_isolation.py`, `tests/unit/test_appsheet_sync_service.py`, `tests/unit/test_patient_model.py`, `tests/integration/test_quarantine_router.py`, plus any other files failing from the same cause
  - Test: `pytest -v -k "not e2e" --co` — zero collection errors; `pytest -v` — zero failures
  - Est: ~150 lines

- [ ] 3.2 **Write quarantine-scenario tests** — Add ~5 tests covering edge cases: machine source + unconfirmed patient → quarantine, machine source + confirmed patient → attach, non-machine source → skip gate, session_code mismatch, missing patient.
  - Files: `tests/unit/test_intake_service.py` or `tests/unit/test_gatekeeper_isolation.py`
  - Test: All 5 new tests pass; full quarantine coverage ≥ 90%
  - Est: ~80 lines

- [ ] 3.3 **Fix or delete `test_jornada_api.py`** — `SESSION_MARKER` was removed from `app/domains/jornada/service.py`. Fix the import (point to the new location or constant) or delete the file if the endpoint is vestigial.
  - Files: `tests/integration/test_jornada_api.py`
  - Test: `pytest tests/integration/test_jornada_api.py --co` collects without error
  - Est: ~30 lines

## Phase 4: Final Verification

- [ ] 4.1 **Full test suite** — Run `pytest -v --cov=app --cov-report=term-missing -p pytest_playwright`. Verify 0 failures, 0 errors, coverage not regressed.
  - Files: None (verification only)
  - Test: Full suite green
  - Est: 0 lines (verification pass)
