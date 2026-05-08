"""
Unit tests for Image Triage — Phase 22 task 22.2.

Verifies that `seleccionar_mejores_imagenes()` enforces the rules:
  - All _Distribution / _Histo / _Main → True
  - _Part1.._Part3 → max 3 per parameter code → True
  - _Part4+ → False
  - Unknown suffix → True
"""
import pytest
from app.shared.models.patient_image import PatientImage
from app.domains.taller.triage import seleccionar_mejores_imagenes


def _img(parameter_code: str, image_type: str, is_included: bool = True) -> PatientImage:
    """Helper: create a PatientImage with the given metadata."""
    img = PatientImage(
        test_result_id=1,
        parameter_code=parameter_code,
        parameter_name_es="Test",
        file_path=f"images/test/{parameter_code}_{image_type}.jpg",
        patient_folder="images/test",
        image_type=image_type,
        is_included_in_report=is_included,
    )
    return img


class TestTriageDistributionHistoMain:
    """All Distribution / Histo / Main images are always included."""

    def test_distribution_included(self):
        img = _img("WBC", "Distribution")
        seleccionar_mejores_imagenes([img])
        assert img.is_included_in_report is True

    def test_histo_included(self):
        img = _img("LYM", "Histo")
        seleccionar_mejores_imagenes([img])
        assert img.is_included_in_report is True

    def test_main_included(self):
        img = _img("PLT", "Main")
        seleccionar_mejores_imagenes([img])
        assert img.is_included_in_report is True


class TestTriagePartLimits:
    """Maximum 3 _Part1.._Part3 per parameter code."""

    def test_part1_to_part3_within_limit(self):
        """First 3 Part images for a parameter are included."""
        images = [
            _img("WBC", "Part1"),
            _img("WBC", "Part2"),
            _img("WBC", "Part3"),
        ]
        seleccionar_mejores_imagenes(images)
        assert all(img.is_included_in_report for img in images)

    def test_part4_excluded(self):
        img = _img("WBC", "Part4")
        seleccionar_mejores_imagenes([img])
        assert img.is_included_in_report is False

    def test_part5_excluded(self):
        img = _img("RBC", "Part5")
        seleccionar_mejores_imagenes([img])
        assert img.is_included_in_report is False

    def test_part10_excluded(self):
        img = _img("EOS", "Part10")
        seleccionar_mejores_imagenes([img])
        assert img.is_included_in_report is False

    def test_fourth_part_excluded(self):
        """The 4th Part1/2/3 image for the same parameter is excluded."""
        images = [
            _img("WBC", "Part1"),
            _img("WBC", "Part2"),
            _img("WBC", "Part3"),
            _img("WBC", "Part1"),   # duplicate — 4th slot
        ]
        seleccionar_mejores_imagenes(images)
        assert images[0].is_included_in_report is True
        assert images[1].is_included_in_report is True
        assert images[2].is_included_in_report is True
        assert images[3].is_included_in_report is False

    def test_different_parameters_independent_limits(self):
        """WBC Part images don't consume RBC Part slots."""
        images = [
            _img("WBC", "Part1"),
            _img("WBC", "Part2"),
            _img("WBC", "Part3"),
            _img("RBC", "Part1"),
            _img("RBC", "Part2"),
            _img("RBC", "Part3"),
        ]
        seleccionar_mejores_imagenes(images)
        assert all(img.is_included_in_report for img in images)


class TestTriageMixedImageSet:
    """Simulates the real 8-image WBC scenario from the spec."""

    def test_real_wbc_scenario(self):
        """WBC with Distribution, Histo, Part1..Part6.

        Expected:
          - Distribution → True
          - Histo       → True
          - Part1..Part3 → True
          - Part4..Part6 → False
        """
        images = [
            _img("WBC", "Distribution"),
            _img("WBC", "Histo"),
            _img("WBC", "Part1"),
            _img("WBC", "Part2"),
            _img("WBC", "Part3"),
            _img("WBC", "Part4"),
            _img("WBC", "Part5"),
            _img("WBC", "Part6"),
        ]
        seleccionar_mejores_imagenes(images)
        flags = {img.image_type: img.is_included_in_report for img in images}
        assert flags["Distribution"] is True
        assert flags["Histo"] is True
        assert flags["Part1"] is True
        assert flags["Part2"] is True
        assert flags["Part3"] is True
        assert flags["Part4"] is False
        assert flags["Part5"] is False
        assert flags["Part6"] is False


class TestTriageUnknownSuffix:
    """Unknown / empty suffix defaults to included (safe default)."""

    def test_unknown_suffix_included(self):
        img = _img("ALP", "unknown")
        seleccionar_mejores_imagenes([img])
        assert img.is_included_in_report is True

    def test_empty_suffix_included(self):
        img = _img("ALT", "")
        seleccionar_mejores_imagenes([img])
        assert img.is_included_in_report is True
