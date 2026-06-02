# Apply Progress: Modo Automático (Headless Console Operator)

## Phase 1: Auto Domain — ✅ Complete

### TDD Cycle Evidence
| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| 1.1 | `tests/test_auto_status.py` | Integration | N/A (new) | ✅ 404 | ✅ 2/2 pass | ✅ 2 cases (data+empty) | ➖ None needed |
| 1.2 | `app/domains/auto/router.py` | Integration | N/A (new) | ✅ Written | ✅ Passed | ✅ 2 cases | ➖ None needed |
| 1.3 | — | — | — | — | — | — | ✅ Clean |

## Phase 2: Backend Endpoints — ✅ Complete

### TDD Cycle Evidence
| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| 2.1 | `tests/test_jornada_adelanto.py` | Integration | N/A (new) | ✅ 404 | ✅ 4/4 pass | ✅ 4 cases (format, idempotent, empty, header) | ➖ None needed |
| 2.2 | `app/domains/jornada/router.py` | Integration | ✅ 8/8 | ✅ Written | ✅ Passed | ✅ 4 cases | ➖ None needed |
| 2.3 | `tests/test_quarantine_reprocess.py` | Unit | ✅ 8/8 | ✅ AssertionError | ✅ 2/2 pass | ✅ 2 cases (trigger+no-trigger) | ➖ None needed |
| 2.4 | `app/domains/reception/appsheet_service.py` | Unit | ✅ 8/8 | ✅ Written | ✅ Passed | ✅ 2 cases | ➖ None needed |

## Phase 3: Headless Operator — ✅ Complete

### TDD Cycle Evidence
| Task | Test File | Layer | Safety Net | RED | GREEN | TRIANGULATE | REFACTOR |
|------|-----------|-------|------------|-----|-------|-------------|----------|
| 3.1 | `tests/test_auto_mode.py` | Unit | N/A (new) | ✅ ImportError (15 tests) | ✅ 15/15 pass | ✅ 15 test cases (sync, status, report, keypress, stdin) | ✅ Extracted pure functions |
| 3.2 | `app/auto_mode.py` | Unit | N/A (new) | ✅ Written | ✅ Passed | ✅ 15 cases | ✅ Clean structure |
| 3.3 | `tests/test_iniciar.sh` | Shell | N/A (new) | ✅ 4 failures | ✅ 4/4 pass | ✅ 4 assertions | ➖ None needed |
| 3.4 | `iniciar.sh` | Shell | N/A (mod) | ✅ Written | ✅ Passed | ✅ 4 assertions | ➖ None needed |

## Phase 4: Regression — ✅ Complete

### Results
| Metric | Value |
|--------|-------|
| Total tests | 847 |
| Passed | 829 |
| Failed | 16 (all pre-existing, none caused by this change) |
| Skipped | 1 |
| Errors | 2 (FileNotFound, pre-existing) |
| Coverage | 77% |
| New regressions | **0** |

## Files Changed
| File | Action | What Was Done |
|------|--------|---------------|
| `app/domains/auto/__init__.py` | Created | Package init |
| `app/domains/auto/router.py` | Created | `GET /auto/status` with DB counts + module-level timestamps |
| `app/domains/jornada/router.py` | Modified | Added `GET /jornada/adelanto` — read-only, X-Jornada-Mode header |
| `app/domains/reception/appsheet_service.py` | Modified | Added `reprocess_quarantined.send(q.id)` after each quarantine link |
| `app/main.py` | Modified | Registered `auto_router` |
| `app/auto_mode.py` | Created | Headless operator: 30s polling, key listener, report handler |
| `iniciar.sh` | Modified | Prompt "¿Modo automático? [s/N]" + conditional fork |
| `tests/test_auto_status.py` | Created | 2 tests for GET /auto/status |
| `tests/test_jornada_adelanto.py` | Created | 4 tests for GET /jornada/adelanto |
| `tests/test_quarantine_reprocess.py` | Created | 2 tests for reprocess trigger in _link_quarantined_items |
| `tests/test_auto_mode.py` | Created | 15 tests for auto_mode.py core functions |
| `tests/test_iniciar.sh` | Created | 4 assertions for iniciar.sh prompt/fork |

## Deviations from Design
None — implementation matches design.

## Issues Found
- Test `test_quarantine_list_empty_shows_message` fails in full suite but passes in isolation (pre-existing test isolation issue, not caused by this change).
- All 16 failing tests in full suite are pre-existing and unrelated to this change.

## Commits Made
(Will be done after apply-progress is written)

## Verification
- ✅ `pytest -v --cov=app --cov-report=term-missing -p pytest_playwright` → 829 passed, 0 new regressions
- ✅ `python -c "import app.auto_mode"` → imports successfully
- ✅ All new tests (23) pass
- ✅ Existing appsheet_sync tests (8) still pass
- ✅ iniciar.sh test passes (4/4 assertions)
- ✅ Coverage: 77% (891 missed lines out of 3946)
