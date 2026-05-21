# Reception Fallback Matching Specification

## Purpose

When lab results arrive without a `session_code`, the fallback matching by
normalized name MUST verify uniqueness before reusing a patient record. This
prevents cross-contamination when multiple patients share the same name. This
spec governs the Fujifilm, Ozelle, and File source paths in reception.

**Note**: Name-only fallback matching for machine sources (Fujifilm, Ozelle,
File) has been REMOVED. Machine data without a valid session code is handled
by the Code Validation Gatekeeper — sent to quarantine, never matched by name.
The name-only fallback described below applies ONLY to manual/operator-entered
data.

## Requirements

### Requirement: Temporal isolation during session_code match

When matching by `session_code`, the system MUST verify
`received_at >= patient.created_at - timedelta(seconds=5)`. If the data's
timestamp is older than the patient creation time (outside tolerance), the
match is REJECTED.

#### Scenario: Temporal match passes

- GIVEN patient "M5" created at 2026-05-20T10:00:00Z
- WHEN data arrives at `received_at=2026-05-20T10:00:03Z` with session_code "M5"
- THEN temporal check passes (within 5s tolerance), patient matched

#### Scenario: Temporal match fails

- GIVEN patient "M5" created at 2026-05-20T10:00:00Z
- WHEN data arrives at `received_at=2026-05-19T09:00:00Z` with session_code "M5"
- THEN temporal check fails (data 25h older than patient)
- AND data is REJECTED → sent to quarantine with reason "temporal_mismatch"

#### Scenario: Archived restore preserves original created_at

- GIVEN patient "M5" was archived, then restored (created_at unchanged: 2026-05-19T09:00:00Z)
- WHEN data arrives at `received_at=2026-05-19T08:59:58Z` with session_code "M5"
- THEN temporal check passes (data is 2s older than patient — within 5s tolerance)
- AND patient matched correctly

### Requirement: `session_code` matching takes priority

The system MUST attempt `session_code`-based matching before any fallback
name-matching. Fallback by name applies ONLY when `session_code` is absent
or does not match any patient.

#### Scenario: Session_code present, match found

- GIVEN a patient exists with `session_code = "M5"` and `normalized_name = "KIARA"`
- WHEN a result arrives with `session_code = "M5"`
- THEN the system matches by `session_code`, not by name
- AND returns `BaulResult(created=False)`

### Requirement: `raw_string` MUST NOT serve as lookup code

The system MUST NOT use `raw_input.raw_string` as a session_code lookup.
The `session_code` field is the sole authority for code-based patient
matching.

#### Scenario: No session_code, raw_string present

- GIVEN a patient with `session_code = "M5"` exists
- WHEN a result arrives with empty `session_code` and `raw_string = "M5"`
- THEN the system does NOT match by `raw_string`
- AND proceeds to name-based fallback matching

### Requirement: Fallback name-matching MUST be unique (machine sources REMOVED)

Name-only fallback for Fujifilm, Ozelle, and File sources is REMOVED.
Machine data without a valid session code is now handled by the Code
Validation Gatekeeper — sent to quarantine, never matched by name.

For manual/operator-entered data, the original fallback rule still applies:
when matching by `normalized_name` in the absence of a `session_code` match,
the system MUST select an existing patient ONLY when exactly one patient
shares that normalized name. If zero or two or more patients share the name,
the system MUST create a new patient record.

#### Scenario: Manual entry with exactly one match

- GIVEN exactly one patient exists with `normalized_name = "KIARA"`
- WHEN a manual entry arrives with `raw_string = "KIARA"` and no `session_code`
- THEN the system reuses the existing patient
- AND returns `BaulResult(created=False)`

#### Scenario: Manual entry with multiple matches

- GIVEN two patients exist with `normalized_name = "KIARA"`
- WHEN a manual entry arrives with `raw_string = "KIARA"` and no `session_code`
- THEN the system creates a new patient record
- AND returns `BaulResult(created=True)`

#### Scenario: Manual entry with no match

- GIVEN no patient exists with `normalized_name = "KIARA"`
- WHEN a manual entry arrives with `raw_string = "KIARA"` and no `session_code`
- THEN the system creates a new patient record
- AND returns `BaulResult(created=True)`
