r"""SessionCodeExtractor — pure-function validation of patient name prefixes.

Extracts a ^[A-Z]\d+ session code from the beginning of patient name strings.
No database access, no side effects — trivially testable.
"""

import re


class SessionCodeExtractor:
    """Extracts session code prefix from patient name strings.

    The code must be at the START of the string and match the pattern
    one uppercase letter followed by one or more digits.

    Examples:
        "M5 KIARA"  → "M5"
        "M5KIARA"   → "M5"
        "M5-KIARA"  → "M5"
        "KIARA"     → None
        ""           → None
    """

    PATTERN: re.Pattern[str] = re.compile(r"^([A-Z]\d+)")

    @staticmethod
    def extract(code_or_name: str) -> str | None:
        r"""Extract ^[A-Z]\d+ code prefix from a patient name string.

        Args:
            code_or_name: Raw patient name string (e.g. "M5 KIARA").

        Returns:
            The extracted code string ("M5") or None if no valid code found.
        """
        if not code_or_name or not code_or_name.strip():
            return None
        match = SessionCodeExtractor.PATTERN.match(code_or_name.strip())
        return match.group(1) if match else None
