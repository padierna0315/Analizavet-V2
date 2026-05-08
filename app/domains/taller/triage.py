"""
Image Triage Service — selects which images are included in the PDF report.

Santiago's rule: veterinarians don't scroll through 165 cell images.
We pre-select the best ones:

  - All `_Distribution` and `_Histo` images → always included
  - Max 3 `_Part1` through `_Part3` per parameter code → included
  - All `_Part4` through `_Part10` → excluded (visual noise reduction)

User can override via HTMX toggle.
"""
from app.shared.models.patient_image import PatientImage


def seleccionar_mejores_imagenes(images: list[PatientImage]) -> list[PatientImage]:
    """Apply triage rules to a list of PatientImage records.

    Modifies `is_included_in_report` in-place and returns the same list.

    Rules (per parameter code):
      - `_Distribution` / `_Histo` / `_Main` → True
      - `_Part1` … `_Part3`                   → True (max 3 total)
      - `_Part4` … `_Part10`                  → False
      - Unknown suffix                        → True (default safe)
    """
    # Track how many PartN images we've selected per parameter code
    part_counts: dict[str, int] = {}
    max_parts = 3

    for img in images:
        suffix = img.image_type or ""

        if suffix.startswith("Part"):
            # Extract part number to enforce max 3 limit
            try:
                part_num = int(suffix.replace("Part", ""))
            except ValueError:
                img.is_included_in_report = True
                continue

            if part_num >= 4:
                # Part4+ are excluded by default
                img.is_included_in_report = False
            else:
                # Part1-Part3: count up to max 3 per parameter
                base = img.parameter_code or ""
                current = part_counts.get(base, 0)
                if current < max_parts:
                    img.is_included_in_report = True
                    part_counts[base] = current + 1
                else:
                    img.is_included_in_report = False

        elif suffix in ("Distribution", "Histo", "Main"):
            img.is_included_in_report = True

        else:
            # Unknown/empty suffix — default to included
            img.is_included_in_report = True

    return images
