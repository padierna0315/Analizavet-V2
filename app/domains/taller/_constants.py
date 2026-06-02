"""Shared constants for the Taller domain — suffix/pattern definitions."""

import re

# Suffixes used by Ozelle in OBX identifiers (confirmed from real log)
KNOWN_SUFFIXES = {"Main", "Histo", "Distribution"}
PART_PATTERN = re.compile(r"_Part(\d+)$")
