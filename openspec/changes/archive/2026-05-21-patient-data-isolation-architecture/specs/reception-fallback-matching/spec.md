# Delta for Reception Fallback Matching

## MODIFIED Requirements

### Requirement: Fallback name-matching MUST be unique (REMOVED for machine sources)

Name-only fallback matching for Fujifilm, Ozelle, and File sources is REMOVED. Machine data without a valid session code is now handled by the Code Validation Gatekeeper — sent to quarantine, never matched by name.
(Previously: name-only fallback with `.all() + len()==1` guard for Fujifilm and Ozelle)

#### Scenario: Machine data without code — was previously named-matched

- GIVEN "KIARA" arrives from Fujifilm with no session_code
- WHEN `receive()` is called
- THEN the Fujifilm name-fallback path is NOT entered
- AND the data is rejected by the gatekeeper → quarantined
- Previously: would have matched by normalized_name with `.all() + len()==1` guard

### ADDED Requirements

### Requirement: Temporal isolation during session_code match

When matching by `session_code`, the system MUST verify `received_at >= patient.created_at - timedelta(seconds=5)`. If the data's timestamp is older than the patient creation time (outside tolerance), the match is REJECTED.

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

### Requirement: Session_code matching takes priority (UNCHANGED)

The existing priority rule is preserved — session_code lookup runs first, gatekeeper validation filters before matching.

### Requirement: raw_string MUST NOT serve as lookup code (UNCHANGED)

No change to this requirement.
