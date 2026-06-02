# Delta Specs: Modo Automático

## 1. auto-operator — Full Spec

Headless foreground loop — `app/auto_mode.py`.

### Requirements

| ID | Requirement | Strength |
|----|-------------|----------|
| AO-1 | Every 30s: call `POST /reception/appsheet/sync`, then `GET /auto/status` | MUST |
| AO-2 | Display sync count and JSON status to stdout on each tick | MUST |
| AO-3 | Detect 'r' via `select.select` stdin (non-blocking, raw mode) — pause loop | MUST |
| AO-4 | On 'r': prompt "¿ADELANTO o FINAL?" — "ADELANTO" calls `GET /jornada/adelanto`, prints report. "FINAL" calls `GET /jornada/resumen`, saves `.txt` to `data/descargas/` | MUST |
| AO-5 | Sync failure → log error to stderr, continue to next tick | MUST |
| AO-6 | Ctrl+C → clean exit, no orphan processes | MUST |

### Scenarios

- GIVEN auto_mode.py is running WHEN 30s elapse THEN sync is called AND status is fetched AND output printed
- GIVEN sync returns 3 patients WHEN status is fetched THEN console shows both results
- GIVEN user presses 'r' AND types "ADELANTO" THEN printed report is shown AND loop resumes
- GIVEN user presses 'r' AND types "FINAL" THEN report is saved as .txt AND log is cleared
- GIVEN AppSheet is unreachable WHEN sync fails THEN error logged AND next tick proceeds at 30s
- GIVEN Ctrl+C is pressed WHEN loop runs THEN process exits cleanly

## 2. auto-status — Full Spec

### Requirements

| ID | Requirement | Strength |
|----|-------------|----------|
| AS-1 | `GET /auto/status` returns JSON with: `patients_waiting_count` (int), `jornada_entries` (int), `last_sync_at` (ISO 8601 `str` or `null`), `last_reprocess_at` (ISO 8601 `str` or `null`) | MUST |

### Scenarios

- GIVEN 5 active patients and 3 jornada entries WHEN GET /auto/status THEN `patients_waiting_count=5` AND `jornada_entries=3`
- GIVEN no sync has run yet WHEN GET /auto/status THEN `last_sync_at` is `null`

## 3. jornada-adelanto — Full Spec

### Requirements

| ID | Requirement | Strength |
|----|-------------|----------|
| JA-1 | `GET /jornada/adelanto` returns same report format as `/jornada/resumen` — grouped by category, plain text | MUST |
| JA-2 | MUST NOT call `clear_jornada_log()` — log is read-only | MUST |
| JA-3 | Response header `X-Jornada-Mode: HASTA-AHORA` | MUST |

### Scenarios

- GIVEN 3 entries in jornada log WHEN adelanto is called twice THEN both responses contain the same 3 entries AND log has 3 entries after second call
- GIVEN empty jornada log WHEN adelanto is called THEN response reads "No hay reportes generados en esta sesión."

## 4. iniciar-script — Delta Spec

### MODIFIED Requirements

| ID | Requirement | Strength |
|----|-------------|----------|
| IS-1 | After `verify_all()`: prompt "¿Modo automático? [s/N]". Default: N (Enter) | MUST |
| IS-2 | Answer 's'/'S' → background `tail -f uvicorn.log`, foreground `uv run python app/auto_mode.py`, skip `open_browser()`, skip final `tail -f` | MUST |
| IS-3 | Answer other → normal flow: `open_browser()`, final `tail -f` | MUST |
| *(Previously: no prompt, always opens browser)* | | |

### Scenarios

- GIVEN verify_all succeeds WHEN user types 's' THEN auto_mode.py runs in foreground AND no browser opens
- GIVEN verify_all succeeds WHEN user types Enter THEN browser opens normally AND auto_mode.py does NOT run

## 5. quarantine-auto-reprocess — Delta Spec

### MODIFIED Requirements

| ID | Requirement | Strength |
|----|-------------|----------|
| QR-1 | After `_link_quarantined_items()` in `sync_from_appsheet()`, for each linked item call `_async_reprocess_quarantined(id)` as fire-and-forget | MUST |
| QR-2 | Reprocess failure MUST NOT propagate to sync response — logfire error, continue | MUST |
| QR-3 | Skipped when `session_code` is `None` (no quarantine to link) | MUST |
| *(Previously: items were linked (status=forced) but reprocess was never triggered)* | | |

### Scenarios

- GIVEN quarantined item with `session_code="M5"`, `status=pending`, `rejection_reason="awaiting_appsheet"` WHEN AppSheet sync creates patient with `session_code="M5"` THEN item status becomes `forced` AND `_async_reprocess_quarantined(id)` is called
- GIVEN reprocess raises an exception WHEN triggered THEN error is logged AND sync response returns success with patient count
- GIVEN sync runs but creates no new patients (all existing) WHEN no items are linked THEN no reprocess is triggered

## Error Cases Summary

| Domain | Error | Behavior |
|--------|-------|----------|
| auto-operator | Sync HTTP failure | Log, continue |
| auto-operator | AppSheet returns 5xx | Log, continue |
| auto-operator | 'r' prompt empty/unknown | Re-prompt |
| auto-status | DB unreachable | Return zeros, log error |
| jornada-adelanto | Log file corrupt | Return empty report, log error |
| quarantine-auto-reprocess | Reprocess exception | Logfire error, sync succeeds |

## Acceptance Criteria

| ID | Criterion | Test Type |
|----|-----------|-----------|
| AC-1 | 30s loop calls sync + status, outputs to stdout | Integration |
| AC-2 | 'r' → ADELANTO prints report, no log clear | E2E |
| AC-3 | 'r' → FINAL saves .txt, log cleared | E2E |
| AC-4 | `GET /auto/status` returns correct counts | Unit |
| AC-5 | `GET /jornada/adelanto` twice returns same data | Integration |
| AC-6 | iniciar.sh 's' skips browser, runs auto_mode.py | Shell test |
| AC-7 | iniciar.sh Enter opens browser normally | Shell test |
| AC-8 | Sync triggers reprocess for linked quarantine items | Integration |
| AC-9 | Reprocess failure does not break sync response | Integration |
| AC-10 | All existing 786 tests still pass | Regression |
