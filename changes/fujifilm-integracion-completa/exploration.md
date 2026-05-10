# Exploration: Fujifilm DRI-CHEM NX600 — Integración Completa

## Executive Summary

- ✅ **Adapter + Parser**: Robust TCP adapter with dual-mode (live/manual), fault-tolerant parser with real-world validation against actual log data
- ✅ **All 22 Chemistry Codes Fully Supported**: CRE, ALT, ALP, AST, GGT, BUN, GLU, Ca, TP, ALB, TBIL, Na, K, Cl, v-AMY, v-LIP, CPK, IP, TCHO, TG, NH3, LDH — all present in `clinical_standards.py` with canine/feline reference ranges and Spanish display names
- ✅ **Full Dramatiq Pipeline**: Parser → Dramatiq actor → ReceptionService (register patient) → TallerService (create TestResult, flag, store)
- ❌ **Critical Bug — Wrong Source in File Upload**: `app/domains/reception/service.py:391` uses `"FUJIFILM"` instead of `"LIS_FUJIFILM"`, so the patient card status dots won't light green for uploaded files
- ❌ **One Value = One TestResult**: Each Fujifilm chemistry value creates its own TestResult — no merging logic exists. 10 chemistry values = 10 separate TestResults for the same patient
- ❌ **Missing Species/Age/Owner Data**: The NX600 only sends patient name and internal ID. The normalizer has no species info to work with, producing patients with defaults
- ❌ **No Interpretations Data in UI**: `taller/preview.html` references `{{ interpretations }}` but this variable is never populated by `get_test_result_full()`
- ⚠️ **Tests exist but environment blocked**: Parser and processor tests are thorough (170 + 383 lines), can't run due to pydantic-core Rust build failure on Python 3.14

---

## Pipeline Overview (Data Flow)

```
Fujifilm NX600 (TCP, port 6001)
  │
  ▼
┌─────────────────────────────────────────────────┐
│ app/satellites/fujifilm/adapter.py              │
│ FujifilmAdapter (SourceAdapter)                 │
│                                                 │
│ Dual-mode:                                      │
│   Live (auto): line-by-line \n-delimited        │
│   Manual: STX...ETX single-frame (residual)     │
│                                                 │
│ handle_client() → _process_message()            │
└──────────────────────┬──────────────────────────┘
                       │ parse_fujifilm_message(line)
                       ▼
┌─────────────────────────────────────────────────┐
│ app/satellites/fujifilm/parser.py               │
│ parse_fujifilm_message(raw) → FujifilmReading[] │
│                                                 │
│ Input: "R,NORMAL,30-04-2026,20:11,908,POLO,..., │
│         CRE-PS,=,0.87,mg/dl,...,ALT-PS,=,43,.." │
│                                                 │
│ 1. Strip STX/ETX control chars                  │
│ 2. Split by message boundary (S,NORMAL/R,NORMAL) │
│ 3. Extract patient info from segment fields      │
│ 4. Regex match XXXX-PS,=,value,unit patterns     │
│ 5. Validate parameter_code ∈ CHEMISTRY_CODES      │
│ 6. Return list of FujifilmReading objects         │
└──────────────────────┬──────────────────────────┘
                       │ process_fujifilm_message.send()
                       ▼
┌─────────────────────────────────────────────────┐
│ app/tasks/fujifilm_processor.py                 │
│ process_fujifilm_message (Dramatiq actor)       │
│                                                 │
│ 1. Extract data from dict                       │
│ 2. Build RawPatientInput(raw_string=name,       │
│                          session_code=id)        │
│ 3. _async_process_pipeline() via anyio.run()    │
└──────────────────────┬──────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────┐
│ _async_process_pipeline()                       │
│                                                 │
│ Phase 1: ReceptionService.receive()             │
│   └─ Normalize (parse_patient_string)           │
│   └─ Baúl (find_existing / register)            │
│   └─ Returns BaulResult(patient_id, patient)    │
│                                                 │
│ Phase 2: (if param_code + value present)        │
│   └─ TallerService.create_test_result(          │
│        test_type="Química Sanguínea",           │
│        test_type_code="CHEM")                   │
│   └─ TallerService.flag_and_store(              │
│        values=[RawLabValueInput])               │
│     └─ TallerFlaggingEngine.flag_test_result()  │
│       └─ ClinicalFlaggingService.flag_value()   │
│       └─ Create LabValue row in DB              │
│       └─ Update TestResult flag counts          │
│       └─ Status → "listo"                       │
└──────────────────────┬──────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────┐
│ Data Model (DB)                                 │
│                                                 │
│ Patient (Baúl)                                  │
│   ├── id, name, species, sex, owner_name        │
│   ├── sources_received: ["LIS_FUJIFILM", ...]   │
│   └── session_code: "908"                       │
│                                                 │
│ TestResult (per value!)                         │
│   ├── patient_id → Patient                      │
│   ├── test_type="Química Sanguínea"             │
│   ├── source="LIS_FUJIFILM"                     │
│   └── status="listo"                            │
│                                                 │
│ LabValue                                        │
│   ├── test_result_id → TestResult               │
│   ├── parameter_code="CRE"                      │
│   ├── parameter_name_es="Creatinina"            │
│   ├── raw_value="0.87", numeric_value=0.87      │
│   ├── unit="mg/dL"                              │
│   ├── reference_range="0.6-1.6 mg/dL"           │
│   └── flag="NORMAL"                             │
└─────────────────────────────────────────────────┘
                       │
                       ▼  UI (HTMX)
┌─────────────────────────────────────────────────┐
│ app/templates/taller/dashboard.html             │
│ └── Upload form → file_type="fujifilm"          │
│ └── Patient cards (status dots per source)      │
│ └── Taller workspace (editor + preview)         │
│                                                 │
│ app/templates/report/report.html                │
│ └── Patient info grid                           │
│ └── Lab value table (grouped, sorted)           │
└─────────────────────────────────────────────────┘
```

---

## Gaps Found

### Gap 1: File Upload Uses Wrong Source (BUG)
**File**: `app/domains/reception/service.py`, line 391
**Code**: `"source": "FUJIFILM"`
**Should be**: `"source": PatientSource.LIS_FUJIFILM.value` (which is `"LIS_FUJIFILM"`)

This means files uploaded via the UI "Subir Datos → Fujifilm" will NOT light up the Fujifilm status dot (green) on the patient card, because `patient_card.html` checks for `'LIS_FUJIFILM' in patient.sources_received`.

### Gap 2: One Value = One TestResult (Design Flaw)
The Fujifilm NX600 sends each chemistry value as a separate message. For a patient with 10+ chemistry values:
- 10+ separate Dramatiq messages
- Each creates its own TestResult record with ONE LabValue
- No merging logic exists on the `inject-to-taller` path
- `inject_patient_to_taller()` only finds the LATEST TestResult (line 329-339 of `service.py`)
- So the user sees only ONE chemistry value at a time in the Taller

The HL7/Ozelle path avoids this because one HL7 message contains ALL values for a patient in a single OBX batch.

### Gap 3: Missing Species/Age/Owner Data
The NX600 sends only patient name and internal ID:
```
S,NORMAL,30-04-2026,20:11,908,POLO,,01
```

The normalizer `parse_patient_string()` expects a format like `"kitty felina 2a Laura Cepeda"`. When given just `"POLO"`, it may fail to extract any demographics. The `BaulService.register()` handles the fallback, but the patient ends up with default/missing species, sex, and owner.

### Gap 4: Interpretations Variable Unpopulated
**File**: `app/templates/taller/preview.html`, line 65
The `{{ interpretations }}` variable is referenced in the template but never populated by `TallerService.get_test_result_full()`. This means the "Interpretaciones Clínicas" panel will always be empty (or throw an error depending on Jinja2 config).

### Gap 5: Regex Potential Fragility
**File**: `app/satellites/fujifilm/parser.py`, line 92-94
The regex:
```
r'([A-Z0-9]+(?:-[A-Z]+)?)-PS\s*,\s*=\s*,\s*([^,]+?)\s*,\s*([^,]+)'
```
- Requires `-PS` suffix. If Fujifilm ever changes format, nothing will parse
- The `([^,]+?)` for value is non-greedy, which could under-match on certain edge cases
- Currently works with known real data (verified against `log_nx600_vivo.txt`)

### Gap 6: No i18n/Locale System
- No `locale/` directory or `.po`/`.mo` files exist
- Translation is entirely hard-coded in `clinical_standards.py` (Spanish only)
- `get_parameter_name()` returns Spanish names only
- `format_date(locale='es')` in `taller/router.py` is the only locale-aware code
- The UI templates have hard-coded Spanish text throughout

### Gap 7: No E2E or Integration Tests for Fujifilm
- Unit tests exist for parser (170 lines) and processor (383 lines) — **good coverage**
- No integration tests that verify the full pipeline (adapter → parser → Dramatiq → DB)
- No E2E tests that verify the UI displays Fujifilm data correctly

### Gap 8: Parser Import Path Issue
**File**: `app/satellites/fujifilm/parser.py`, line 8
```python
from clinical_standards import CHEMISTRY_CODES
```
This is a top-level import from the project root. If the parser is ever imported from a context where the root is not in `sys.path`, this will fail. The Ozelle parser in `app/satellites/ozelle/` does not have this issue (it uses relative imports within `app/`).

---

## Translation / Localization Status

| Code | Spanish Name | Unit | Canine Range | Feline Range |
|------|-------------|------|-------------|-------------|
| CRE | Creatinina | mg/dL | 0.6-1.6 | 0.8-2.0 |
| ALT | Alanina Aminotransferasa | U/L | 10-100 | 10-100 |
| ALP | Fosfatasa Alcalina | U/L | 20-150 | 10-80 |
| AST | Aspartato Aminotransferasa | U/L | 10-50 | 10-50 |
| GGT | Gamma-Glutamil Transferasa | U/L | 0-10 | 0-10 |
| CPK | Creatina Quinasa | U/L | 50-200 | 50-250 |
| v-LIP | Lipasa Veterinaria | U/L | 200-800 | 100-600 |
| v-AMY | Amilasa Veterinaria | U/L | 400-1500 | 500-1500 |
| LDH | Deshidrogenasa Láctica | U/L | 0-200 | 0-200 |
| BUN | Nitrógeno Ureico | mg/dL | 15-35 | 15-35 |
| GLU | Glucosa | mg/dL | 70-110 | 70-150 |
| IP | Fósforo Inorgánico | mg/dL | 2.5-6.0 | 3.0-6.5 |
| Ca | Calcio Total | mg/dL | 9.0-11.5 | 8.5-10.5 |
| TP | Proteína Total | g/dL | 5.5-7.5 | 6.0-8.0 |
| ALB | Albúmina | g/dL | 2.5-4.0 | 2.5-4.0 |
| TCHO | Colesterol Total | mg/dL | 130-300 | 80-220 |
| TG | Triglicéridos | mg/dL | 20-110 | 20-110 |
| TBIL | Bilirrubina Total | mg/dL | 0.0-0.5 | 0.0-0.5 |
| NH3 | Amoníaco | µg/dL | 0-100 | 0-100 |
| Na | Sodio | mEq/L | 140-155 | 145-155 |
| K | Potasio | mEq/L | 3.5-5.5 | 3.5-5.5 |
| Cl | Cloruro | mEq/L | 105-115 | 115-125 |

**Status**: TRANSLATION COMPLETE. All 22 Fujifilm codes are in `CHEMISTRY_CODES`, `VETERINARY_STANDARDS`, and `PARAMETER_GROUPS["QUÍMICA SANGUÍNEA"]`. No additional translation work needed.

---

## UI / Reception Card Integration Status

### What Works
- **Patient card** (`patient_card.html`) shows 3 colored status dots: Ozelle (green/gray), Fujifilm (green/gray), Bautizador (green/gray)
- **Upload form** in dashboard includes `file_type="fujifilm"` option
- **File upload** route (`POST /reception/upload`) handles `file_type="fujifilm"` and enqueues records
- **Patient injection** (`POST /reception/patient/{id}/inject-to-taller`) loads the latest TestResult into the Taller workspace
- **Taller workspace** shows lab values table with parameter names, raw values, units, reference ranges, and flags
- **Report preview** (`report.html`) renders fully formatted report with patient info, lab table, flags

### What Does NOT Work
- **Uploaded files don't light the Fujifilm dot** (see Gap 1 — wrong source string)
- **Only ONE chemistry value per patient shows** in the Taller (see Gap 2 — one TestResult per value, `inject-to-taller` only gets the latest)
- **Species/sex/owner are missing/incorrect** when receiving Fujifilm data (see Gap 3 — only patient name provided)
- **No "pending" state management**: Unlike HL7 which explicitly handles `"recibido"` → `"pendiente"` → `"listo"` transitions, Fujifilm values go straight to `"listo"` immediately after flagging

---

## Recommendations (Priority Order)

### P1: Fix File Upload Source Bug
- Change `app/domains/reception/service.py` line 391 from `"FUJIFILM"` to `"LIS_FUJIFILM"`
- Impact: 1 line change, zero risk
- Effect: Uploaded Fujifilm files will properly show the green status dot

### P2: Implement TestResult Merging for Fujifilm
- Create a deduplication/merge strategy in `fujifilm_processor.py`:
  - Check if a TestResult already exists for the same patient + test_type + recent timeframe
  - If yes, append the new LabValue to the existing TestResult instead of creating a new one
  - If no, create a new TestResult as before
- Alternative: Buffer readings in Dramatiq for a short period (e.g., 5s) before creating the TestResult
- This is the CRITICAL architectural fix — without it, the Fujifilm integration is unusable in practice

### P3: Add Species/Owner Input Mechanism
- When Fujifilm data arrives with no species info, show a prompt in the UI for the vet to fill in species, age, owner
- Options:
  a) Show a modal/field in the patient card that appears when `species == "Unknown"` or `owner_name == ""`
  b) Default to "Canino" / "Mestizo" / "Sin Tutor" with a clear visual indicator that data is incomplete
  c) Store a "pending_species" flag and require completion before PDF generation

### P4: Fix Interpretations Variable (Minor)
- Either populate the `interpretations` list in `get_test_result_full()` or remove it from the template
- Check the `taller/preview.html` template for the `{% if interpretations %}` block (line 65)

### P5: Add Integration Tests
- Add an integration test that mocks the Fujifilm adapter receiving a multi-value message
- Verify that the full pipeline (adapter → parser → processor → DB) works end-to-end
- Add a test that verifies file upload with correct source value

### P6: NX600 Data Grouping via session_code
- The NX600 sends the same `internal_id` (e.g., "908") with each chemistry reading
- Use `session_code` to group readings and trigger TestResult creation only after a "batch complete" signal
- Since the NX600 doesn't send an explicit end-of-batch marker, implement a timer-based approach (e.g., wait 30s after the last received reading for a session_code, then batch all pending values)

---

## Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| **Parser regex breakage** if Fujifilm changes output format | Low | High | Add format validation at adapter level + monitoring alerts |
| **DB bloat from 1-TestResult-per-value** in production | High | Medium | Implement P2 (merging) before production deployment — each patient with 18 chem values = 18 TestResult rows |
| **Patient duplication** if species/name matching fails | Medium | High | Improve normalizer fallback; add manual merge in UI |
| **Wrong flagging** if species defaults incorrectly | Medium | High | Species defaults should clearly indicate "unknown" rather than assuming Canino |
| **Lost values** if Dramatiq crashes mid-batch | Medium | Medium | Dramatiq retries (3x) mitigate this, but batch atomicity is not guaranteed |
| **TestResult status confusion** — Fujifilm goes straight to "listo" while Ozelle uses the full pipeline | Low | Low | Standardize status transitions across both paths |

---

## Ready for Proposal

**YES** — This exploration has identified all the gaps with specific file locations, code evidence, and production-blocking issues. The proposal should focus on:

1. **Two production blockers** (P1: wrong source, P2: no value merging) that must be fixed before the integration is usable
2. **One UX gap** (P3: missing species/owner) that needs design input
3. **Cleanup** (P4: interpretations, P5: tests, P6: session-based grouping)
