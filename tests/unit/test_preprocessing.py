import io

import numpy as np
import pytest
from PIL import Image

from krmanfi_search.infrastructure.ocr import preprocessing
from krmanfi_search.infrastructure.ocr.preprocessing import (
    PreprocessOptions,
    despeckle,
    detect_orientation,
    estimate_skew,
    geometry_preview,
    normalize_illumination,
    otsu_threshold,
    png_bytes,
    preprocess,
    sauvola,
)
from tests.helpers import ruled_page


def bimodal(low=40, high=210, size=100):
    array = np.full((size, size), high, dtype=np.uint8)
    array[:, : size // 2] = low
    return array


def test_otsu_separates_two_levels():
    threshold = otsu_threshold(bimodal())
    assert 40 <= threshold < 210


def test_otsu_on_empty_array_is_midpoint():
    assert otsu_threshold(np.zeros((0, 0), dtype=np.uint8)) == 127


def test_otsu_on_flat_image_does_not_crash():
    assert 0 <= otsu_threshold(np.full((20, 20), 90, dtype=np.uint8)) <= 255


def test_sauvola_returns_binary_image_of_same_shape():
    result = sauvola(np.asarray(ruled_page(200, 200)))
    assert result.shape == (200, 200) and set(np.unique(result)) <= {0, 255}


def test_sauvola_keeps_ink_dark():
    page = np.asarray(ruled_page(300, 300))
    result = sauvola(page)
    assert result[page == 0].mean() < 60 and result[page == 255].mean() > 200


def test_sauvola_on_uniform_image_is_white():
    assert (sauvola(np.full((50, 50), 200, dtype=np.uint8)) == 255).all()


def test_illumination_is_flattened():
    width, height = 400, 300
    gradient = np.tile(np.linspace(110, 255, width), (height, 1))
    page = gradient.astype(np.uint8)
    page[100:110, 50:350] = 20
    flat = normalize_illumination(page)
    left, right = flat[200:280, 20:80].mean(), flat[200:280, 320:380].mean()
    assert abs(left - right) < 15 < abs(page[200:280, 20:80].mean() - page[200:280, 320:380].mean())


def test_illumination_keeps_text_dark():
    page = np.full((300, 300), 230, dtype=np.uint8)
    page[100:112, 40:260] = 30
    assert normalize_illumination(page)[104, 100] < 80


@pytest.mark.parametrize("angle", [-6.0, -3.0, 3.0, 6.0])
def test_skew_estimate_is_close_to_the_inverse_rotation(angle):
    page = np.asarray(ruled_page(900, 1200, angle=angle))
    assert estimate_skew(page) == pytest.approx(-angle, abs=1.0)


def test_straight_page_has_no_skew():
    assert abs(estimate_skew(np.asarray(ruled_page(900, 1200)))) <= 0.5


def test_blank_page_has_no_skew():
    assert estimate_skew(np.full((400, 400), 255, dtype=np.uint8)) == 0.0


def test_despeckle_removes_dots_and_keeps_blocks():
    page = np.full((100, 100), 255, dtype=np.uint8)
    page[10, 10] = 0
    page[50, 50] = 0
    page[60:80, 20:60] = 0
    cleaned = despeckle(page)
    assert cleaned[10, 10] == 255 and cleaned[50, 50] == 255
    assert (cleaned[60:80, 20:60] == 0).all()


def test_despeckle_without_opencv_uses_median(monkeypatch):
    monkeypatch.setattr(preprocessing, "optional_import", lambda name: None)
    page = np.full((60, 60), 255, dtype=np.uint8)
    page[30, 30] = 0
    assert despeckle(page)[30, 30] == 255


def test_preprocess_reports_applied_steps():
    processed, report = preprocess(ruled_page(900, 1200), PreprocessOptions())
    assert processed.mode == "L"
    assert {"denoise", "deskew_deg", "binarization", "despeckle"} <= set(report)
    assert set(np.unique(np.asarray(processed))) <= {0, 255}


def test_small_images_are_upscaled():
    processed, report = preprocess(ruled_page(300, 400), PreprocessOptions(upscale_min_side=900))
    assert report["upscale"] == 3.0 and processed.width >= 900


def test_upscale_is_capped_at_four_times():
    options = PreprocessOptions(upscale_min_side=5000)
    _, report = preprocess(Image.new("L", (100, 100), 255), options)
    assert report["upscale"] == 4.0


def test_large_images_are_not_resized():
    _, report = preprocess(ruled_page(1200, 1600), PreprocessOptions(upscale_min_side=1000))
    assert "upscale" not in report


@pytest.mark.parametrize("mode", ["otsu", "sauvola", "auto"])
def test_binarization_modes_give_black_and_white(mode):
    processed, report = preprocess(
        ruled_page(900, 1200), PreprocessOptions(binarization=mode, deskew=False, denoise=False)
    )
    assert set(np.unique(np.asarray(processed))) <= {0, 255} and "binarization" in report


def test_none_binarization_keeps_gray_levels_and_skips_despeckle():
    processed, report = preprocess(
        ruled_page(900, 1200),
        PreprocessOptions(binarization="none", denoise=False, upscale_min_side=0),
    )
    assert "binarization" not in report and "despeckle" not in report
    assert processed.size == (900, 1200)


def test_steps_can_be_switched_off():
    _, report = preprocess(
        ruled_page(900, 1200),
        PreprocessOptions(denoise=False, deskew=False, despeckle=False, upscale_min_side=0),
    )
    assert "denoise" not in report and "deskew_deg" not in report and "despeckle" not in report


def test_denoise_falls_back_to_median_without_opencv(monkeypatch):
    monkeypatch.setattr(preprocessing, "optional_import", lambda name: None)
    _, report = preprocess(ruled_page(900, 1200), PreprocessOptions(deskew=False))
    assert report["denoise"] == "median3"


def test_big_images_use_cheap_denoise(monkeypatch):
    monkeypatch.setattr(preprocessing, "NLMEANS_MAX_PIXELS", 10)
    _, report = preprocess(ruled_page(900, 1200), PreprocessOptions(deskew=False))
    assert report["denoise"] == "cv2.median3"


def test_colour_and_palette_inputs_are_accepted():
    for mode in ("RGB", "RGBA", "P", "1"):
        processed, _ = preprocess(ruled_page(700, 900).convert(mode), PreprocessOptions())
        assert processed.mode == "L"


def test_geometry_preview_matches_processed_size_for_skewed_page():
    options = PreprocessOptions()
    page = ruled_page(700, 900, angle=5.0)
    processed, report = preprocess(page, options)
    shown = geometry_preview(page, options, report)
    assert shown.mode == "RGB" and shown.size == processed.size


def test_geometry_preview_matches_after_upscale():
    options = PreprocessOptions(upscale_min_side=1000)
    page = ruled_page(400, 500)
    processed, report = preprocess(page, options)
    assert geometry_preview(page, options, report).size == processed.size


def test_geometry_preview_keeps_colours():
    page = Image.new("RGB", (1200, 1200), (250, 200, 10))
    options = PreprocessOptions(deskew=False)
    shown = geometry_preview(page, options, {})
    assert shown.getpixel((10, 10)) == (250, 200, 10)


def test_png_bytes_round_trip():
    image = ruled_page(50, 40)
    again = Image.open(io.BytesIO(png_bytes(image)))
    assert again.format == "PNG" and again.size == (50, 40)
    assert np.array_equal(np.asarray(again), np.asarray(image))


def test_orientation_is_zero_without_pytesseract(monkeypatch):
    monkeypatch.setattr(preprocessing, "optional_import", lambda name: None)
    assert detect_orientation(ruled_page(300, 300)) == 0


def test_orientation_is_zero_when_detection_fails(monkeypatch):
    class Broken:
        Output = type("Output", (), {"DICT": "dict"})

        @staticmethod
        def image_to_osd(*args, **kwargs):
            raise RuntimeError("osd.traineddata missing")

    monkeypatch.setattr(preprocessing, "optional_import", lambda name: Broken)
    assert detect_orientation(ruled_page(300, 300)) == 0


def test_orientation_is_read_from_osd_result(monkeypatch):
    class Fake:
        Output = type("Output", (), {"DICT": "dict"})

        @staticmethod
        def image_to_osd(*args, **kwargs):
            return {"rotate": 450}

    monkeypatch.setattr(preprocessing, "optional_import", lambda name: Fake)
    assert detect_orientation(ruled_page(300, 300)) == 90
