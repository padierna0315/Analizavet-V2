#!/usr/bin/env python3

import re
from dataclasses import dataclass
from typing import List
import logging

from clinical_standards import CHEMISTRY_CODES

logger = logging.getLogger(__name__)


@dataclass
class FujifilmReading:
    internal_id: str  # e.g. "908"
    patient_name: str  # e.g. "POLO"
    parameter_code: str  # e.g. "CRE" (stripped from "CRE-PS")
    raw_value: str  # e.g. "0.87"


def parse_fujifilm_message(raw: str) -> List[FujifilmReading]:
    """
    Parse Fujifilm NX600 messages.

    Message format:
        S/R,NORMAL,DD-MM-YYYY,HH:MM,internal_id,patient_name,...,XXXX-PS,=,value,unit,...

    - Splits by comma
    - Checks if starts with 'S' or 'R'
    - Extracts internal_id (field index 4) and patient_name (field index 5)
    - Finds all XXXX-PS,=,value,unit patterns with regex
    - Strips '-PS' suffix from parameter code
    - Validates against CHEMISTRY_CODES
    - Returns list of FujifilmReading

    FAULT-TOLERANT: never crashes, returns empty list on any error.
    """
    try:
        # Validate input type
        if not isinstance(raw, str):
            logger.debug(f"parse_fujifilm_message: non-string input type={type(raw)}")
            return []

        # Strip control characters (STX \x02, ETX \x03)
        raw = raw.replace('\x02', '').replace('\x03', '')

        # Strip whitespace
        raw = raw.strip()

        # If the message doesn't start with S/R, try to find the first S/R marker
        # This handles cases where control characters cause prefix data to appear
        if not raw or raw[0] not in ('S', 'R'):
            # Look for S,NORMAL or R,NORMAL pattern to extract valid message portion
            sr_match = re.search(r'([SR]),NORMAL', raw)
            if sr_match:
                # Extract from the S/R position onwards
                raw = raw[sr_match.start():]
            else:
                return []

        # Split by comma
        fields = raw.split(",")

        # Must have enough fields for basic info (at least through patient_name at index 5)
        if len(fields) < 6:
            logger.debug(f"parse_fujifilm_message: insufficient fields, got {len(fields)}")
            return []

        # Check first field starts with 'S' or 'R'
        first_field = fields[0].strip()
        if not first_field or first_field[0] not in ("S", "R"):
            logger.debug(f"parse_fujifilm_message: first field '{first_field}' does not start with S or R")
            return []

        # Extract basic info
        internal_id = fields[4].strip()
        patient_name = fields[5].strip()

        if not internal_id or not patient_name:
            logger.debug(f"parse_fujifilm_message: missing internal_id or patient_name")
            return []

        # Join the remaining fields back into a string to search for chemistry patterns
        # Chemistry patterns appear as: CODE-PS,=,value,unit
        # We need to find these scattered throughout the comma-separated fields.
        # Re-joining with a marker helps regex find patterns across field boundaries.
        remainder = ",".join(fields[6:])

        # Regex: word chars + dash + "-PS", then comma, equals sign, comma,
        # then capture value+unit (may include spaces), then comma, then next field.
        # The raw value is extracted from the combined field.
        pattern = re.compile(
            r'([A-Za-z0-9]+(?:-[A-Za-z]+)?)-PS\s*,\s*[<>=]\s*,\s*([^,]+?)\s*,\s*([^,]+)'
        )
        
        # The file may contain multiple concatenated messages.
        # Each message starts with S,NORMAL or R,NORMAL.
        # Find all message segments by looking for ,S,NORMAL or ,R,NORMAL boundaries.
        
        # Find positions of all message starts (S,NORMAL or R,NORMAL)
        message_starts = [m.start(1) for m in re.finditer(r'([SR]),NORMAL', raw)]
        
        if not message_starts:
            logger.debug("parse_fujifilm_message: no message starts found")
            return []
        
        all_readings: List[FujifilmReading] = []
        
        # Process each message segment
        for i, start_pos in enumerate(message_starts):
            # Segment goes from start_pos to next start_pos (or end)
            end_pos = message_starts[i + 1] if i + 1 < len(message_starts) else len(raw)
            segment = raw[start_pos:end_pos]
            
            # Parse this segment as a single message
            segment_fields = segment.split(",")
            if len(segment_fields) < 6:
                logger.debug(f"parse_fujifilm_message: segment {i} has insufficient fields")
                continue
            
            # Check first field starts with S or R
            first_field = segment_fields[0].strip()
            if not first_field or first_field[0] not in ("S", "R"):
                logger.debug(f"parse_fujifilm_message: segment {i} first field '{first_field}' invalid")
                continue
            
            # Extract basic info from THIS segment
            internal_id = segment_fields[4].strip()
            patient_name = segment_fields[5].strip()
            
            if not internal_id or not patient_name:
                logger.debug(f"parse_fujifilm_message: segment {i} missing id or name")
                continue
            
            # Join remaining fields for pattern matching
            remainder = ",".join(segment_fields[6:])
            
            matches = pattern.findall(remainder)
            
            for param_code_stripped, value_unit_field, _next_field in matches:
                # Extract numeric value
                raw_val_match = re.search(r'([*0-9.]+)', value_unit_field)
                if not raw_val_match:
                    continue
                raw_val = raw_val_match.group(1)
                
                # Skip if value is **** or other non-numeric placeholder
                if not raw_val or raw_val.strip() == "" or set(raw_val.strip()) == {"*"}:
                    continue
                
                # Validate against CHEMISTRY_CODES (case-insensitive)
                if param_code_stripped.upper() not in {c.upper() for c in CHEMISTRY_CODES}:
                    continue
                
                reading = FujifilmReading(
                    internal_id=internal_id,
                    patient_name=patient_name,
                    parameter_code=param_code_stripped,
                    raw_value=raw_val.strip(),
                )
                all_readings.append(reading)
                logger.debug(f"parse_fujifilm_message: extracted {reading}")
        
        return all_readings

    except Exception as e:
        logger.error(f"parse_fujifilm_message: unexpected error: {e}", exc_info=True)
        return []
