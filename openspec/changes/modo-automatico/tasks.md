# Tasks: Modo Automático (Headless Console Operator)

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~410 |
| 800-line budget risk | Low |
| Chained PRs recommended | No |
| Suggested split | Single PR |
| Delivery strategy | auto-forecast |
| Chain strategy | stacked-to-main |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: stacked-to-main
800-line budget risk: Low

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | All backend + headless operator + tests | PR 1 (single) | Stacked to main; tests bundled per TDD cycle |

## Phase 1: Auto Domain (TDD)

- [x] 1.1 RED: Write test for `GET /auto/status` — mock Patient + DataQuarantine counts, assert JSON shape (`tests/test_auto_status.py`, ~50 lines)
- [x] 1.2 GREEN: Create `app/domains/auto/__init__.py` + `router.py` with status endpoint; register in `app/main.py` (~40 lines)
- [x] 1.3 REFACTOR: Verify test passes, clean up imports

## Phase 2: Backend Endpoints (TDD)

- [x] 2.1 RED: Write test for `GET /jornada/adelanto` — assert same content on 2nd call, log unchanged, empty edge case (`tests/test_jornada_adelanto.py`, ~40 lines)
- [x] 2.2 GREEN: Add adelanto endpoint in `app/domains/jornada/router.py` — reuse `get_jornada_results` + `format_report`, skip clear, set `X-Jornada-Mode: HASTA-AHORA` header (~15 lines)
- [x] 2.3 RED: Write test for quarantine reprocess — mock `reprocess_quarantined.send`, assert called per linked item, not called when no link (`tests/test_quarantine_reprocess.py`, ~35 lines)
- [x] 2.4 GREEN: Add import + `reprocess_quarantined.send(q.id)` after each link in `_link_quarantined_items()` (~5 lines)

## Phase 3: Headless Operator (TDD)

- [x] 3.1 RED: Write integration test for auto_mode loop — responde httpx client, assert 30s tick calls sync+status, assert 'r' triggers report handler (`tests/test_auto_mode.py`, ~70 lines)
- [x] 3.2 GREEN: Create `app/auto_mode.py` — `select.select` key listener, httpx poll loop, ADELANTO/FINAL report handler, clean Ctrl+C exit (~130 lines)
- [x] 3.3 RED: Write shell test for iniciar.sh — assert 's' runs auto_mode.py, assert Enter opens browser (`tests/test_iniciar.sh`, ~30 lines)
- [x] 3.4 GREEN: Add modo automático prompt + conditional fork in `iniciar.sh` after `verify_all` (~12 lines)

## Phase 4: Regression

- [x] 4.1 Run full suite: `pytest -v --cov=app --cov-report=term-missing -p pytest_playwright` — assert 0 new regressions (786 pass + 30 known failures baseline)
