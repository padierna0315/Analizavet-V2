# Code Validation Gatekeeper Specification

## Purpose

Prevent patient data cross-contamination by enforcing session code format (`^[A-Z]\d+`) at every data source boundary before data enters the matching pipeline. Data without a valid code prefix MUST be rejected — never silently matched by name.

## Requirements

### Requirement: Patient name MUST contain valid code prefix

The system MUST validate that every incoming patient record from any source (AppSheet, Ozelle, Fujifilm, Manual) carries a valid `^[A-Z]\d+` prefix — one uppercase letter followed by one or more digits — at the start of the patient identifier. Validation fires BEFORE any parsing or matching logic.

| Source | Field to validate | Location |
|--------|-------------------|----------|
| AppSheet | `session_code` (Codigo_Corto) | `app/services/appsheet.py` fetch/sync |
| Ozelle | `raw_patient_string` (PID[9]) or `sample_id` (PID[3]) | `app/satellites/ozelle/hl7_parser.py` |
| Fujifilm | `patient_name` field | `app/satellites/fujifilm/parser.py` |
| Manual | `raw_string` | `app/domains/reception/service.py` receive |

On failure: REJECT the data → record in Logfire alert → store in DataQuarantine → do NOT attempt matching.

#### Scenario: Valid code passes

- GIVEN "M5 KIARA" arrives from Fujifilm
- WHEN the gatekeeper validates `patient_name`
- THEN code "M5" is extracted, data proceeds to matching pipeline

#### Scenario: No code — rejected

- GIVEN "KIARA" arrives from Fujifilm (no prefix)
- WHEN the gatekeeper validates
- THEN data is REJECTED, Logfire alert fires, data is stored in DataQuarantine
- AND no name-only matching is attempted

#### Scenario: Malformed code — rejected

- GIVEN "5M KIARA" (digits first) arrives
- WHEN the gatekeeper validates
- THEN data is REJECTED and sent to DataQuarantine

#### Scenario: Ozelle HL7 with code

- GIVEN HL7 message with PID[9]="A105 BUDDY"
- WHEN gatekeeper validates `raw_patient_string`
- THEN code "A105" extracted, `sample_id` set, data proceeds

### Requirement: Code pattern is `^[A-Z]\d+`

The validation regex MUST be `^[A-Z]\d+` — one uppercase letter, one or more digits. This is a change from the existing `^[A-Z]\d{1,2}` (which limited to 2 digits). Supports codes like "M5", "F3", "A105".

### Requirement: Name-only fallback removed for machine sources

The system MUST NOT attempt name-only matching for Fujifilm, Ozelle, or File sources. The `.all() + len()==1` guard in `service.py` is replaced by proactive gatekeeper rejection. No code = no match = quarantine.
(Previously: name-only fallback with uniqueness guard for Fujifilm and Ozelle)
