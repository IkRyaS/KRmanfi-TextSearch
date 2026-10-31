from __future__ import annotations

import io
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
from PIL import Image, ImageFilter, ImageOps

from krmanfi_search.shared.optional import optional_import

type Gray = npt.NDArray[np.uint8]


@dataclass(frozen=True, slots=True)
class PreprocessOptions:
    """Какие шаги предобработки применять."""

    upscale_min_side: int = 1000
    denoise: bool = True
    deskew: bool = True
    binarization: str = "auto"
    despeckle: bool = True
    max_skew_degrees: float = 15.0


BINARIZATION_MODES = ("auto", "otsu", "sauvola", "none")
NLMEANS_MAX_PIXELS = 4_000_000


def normalize_illumination(gray: Gray):
    """Выровнять неравномерное освещение (фото с телефона, тени, виньетирование).

    Фон страницы оценивается как сильно размытый максимум уменьшенной копии (тёмные штрихи
    текста под максимальным фильтром исчезают), и каждый пиксель делится на этот фон: бумага
    становится равномерно белой, а текст — равномерно тёмным.
    """
    img = Image.fromarray(gray)
    factor = max(1, min(img.size) // 200)
    small = img.reduce(factor) if factor > 1 else img
    background = small.filter(ImageFilter.MaxFilter(7)).filter(ImageFilter.GaussianBlur(4))
    background = background.resize(img.size, Image.Resampling.BILINEAR)
    bg = np.maximum(np.asarray(background, dtype=np.float64), 1.0)
    flat = np.asarray(gray, dtype=np.float64) / bg * 255.0
    return np.clip(flat, 0, 255).astype(np.uint8)


def otsu_threshold(gray: Gray):
    """Глобальный порог Оцу (максимизирует межклассовую дисперсию)."""
    hist = np.bincount(gray.ravel(), minlength=256).astype(np.float64)
    total = gray.size
    if total == 0:
        return 127
    omega = np.cumsum(hist) / total
    mu = np.cumsum(hist * np.arange(256)) / total
    mu_t = mu[-1]
    with np.errstate(divide="ignore", invalid="ignore"):
        sigma_b = (mu_t * omega - mu) ** 2 / (omega * (1 - omega))
    sigma_b = np.nan_to_num(sigma_b)
    return int(np.argmax(sigma_b))


def sauvola(gray: Gray, window: int = 25, k: float = 0.2, r: float = 128.0):
    """Локальная бинаризация Саууолы по интегральным изображениям (устойчива к неровному свету)."""
    img = gray.astype(np.float64)
    pad = window // 2
    padded = np.pad(img, pad + 1, mode="reflect")
    integral = padded.cumsum(0).cumsum(1)
    integral_sq = (padded**2).cumsum(0).cumsum(1)
    h, w = img.shape
    y0, x0 = np.arange(h), np.arange(w)

    def box(ii: npt.NDArray[np.float64]):
        """Сумма значений пикселей в каждом окне ``window`` по интегральному изображению."""
        y1, x1 = y0[:, None] + 1, x0[None, :] + 1
        y2, x2 = y1 + window, x1 + window
        return np.asarray(ii[y2, x2] - ii[y1, x2] - ii[y2, x1] + ii[y1, x1], dtype=np.float64)

    n = window * window
    mean = box(integral) / n
    var = np.maximum(box(integral_sq) / n - mean**2, 0)
    threshold = mean * (1 + k * (np.sqrt(var) / r - 1))
    return np.where(img > threshold, 255, 0).astype(np.uint8)


def estimate_skew(gray: Gray, max_angle: float = 15.0):
    """Угол наклона в градусах: максимум дисперсии горизонтальной проекции при повороте."""
    small = Image.fromarray(gray)
    small.thumbnail((800, 800))
    arr = normalize_illumination(np.asarray(small, dtype=np.uint8))
    binary = arr < otsu_threshold(arr)
    if binary.mean() < 0.002:
        return 0.0
    img = Image.fromarray((binary * 255).astype(np.uint8))

    def score(angle: float):
        """Дисперсия профиля горизонтальной проекции после поворота на угол ``angle``."""
        rotated = np.asarray(img.rotate(angle, resample=Image.Resampling.BILINEAR, expand=True))
        profile = rotated.sum(axis=1, dtype=np.float64)
        return float(np.var(profile))

    coarse = np.arange(-max_angle, max_angle + 0.01, 1.0)
    best = float(max(coarse, key=score))
    fine = np.arange(best - 1, best + 1.01, 0.1)
    return round(float(max(fine, key=score)), 2)


def despeckle(binary: Gray, min_area: int = 6):
    """Убрать мелкие связные области (точки шума) на чёрно-белом изображении."""
    cv2 = optional_import("cv2")
    if cv2 is None:
        return np.asarray(
            Image.fromarray(binary).filter(ImageFilter.MedianFilter(3)), dtype=np.uint8
        )
    inverted = (binary < 128).astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(inverted, connectivity=8)
    keep = np.zeros(n, dtype=bool)
    keep[1:] = stats[1:, cv2.CC_STAT_AREA] >= min_area
    cleaned = keep[labels]
    return np.where(cleaned, 0, 255).astype(np.uint8)


def preprocess(image: Image.Image, opts: PreprocessOptions):
    """Выполнить цепочку предобработки.

    Args:
        image: Исходное изображение (любого режима).
        opts: Параметры.

    Returns:
        ``(обработанное_серое_изображение, отчёт)``; отчёт перечисляет применённые шаги.
    """
    report = {}
    img = ImageOps.exif_transpose(image).convert("L")
    if opts.upscale_min_side and min(img.size) < opts.upscale_min_side:
        factor = min(opts.upscale_min_side / max(min(img.size), 1), 4.0)
        img = img.resize(
            (int(img.width * factor), int(img.height * factor)), Image.Resampling.LANCZOS
        )
        report["upscale"] = round(factor, 2)
    gray = np.asarray(img, dtype=np.uint8)
    if opts.denoise:
        cv2 = optional_import("cv2")
        if cv2 is not None and gray.size <= NLMEANS_MAX_PIXELS:
            denoised = cv2.fastNlMeansDenoising(
                gray, None, h=10, templateWindowSize=7, searchWindowSize=21
            )
            gray = np.asarray(denoised, dtype=np.uint8)
            report["denoise"] = "cv2.fastNlMeans"
        elif cv2 is not None:
            gray = np.asarray(cv2.medianBlur(gray, 3), dtype=np.uint8)
            report["denoise"] = "cv2.median3"
        else:
            gray = np.asarray(img.filter(ImageFilter.MedianFilter(3)), dtype=np.uint8)
            report["denoise"] = "median3"
    if opts.deskew:
        angle = estimate_skew(gray, opts.max_skew_degrees)
        if abs(angle) >= 0.2:
            rotated = Image.fromarray(gray).rotate(
                angle, resample=Image.Resampling.BICUBIC, expand=True, fillcolor=255
            )
            gray = np.asarray(rotated, dtype=np.uint8)
        report["deskew_deg"] = angle
    if opts.binarization == "auto":
        gray = normalize_illumination(gray)
        t = otsu_threshold(gray)
        gray = np.where(gray > t, 255, 0).astype(np.uint8)
        report["binarization"] = f"illumination+otsu(t={t})"
    elif opts.binarization == "otsu":
        t = otsu_threshold(gray)
        gray = np.where(gray > t, 255, 0).astype(np.uint8)
        report["binarization"] = f"otsu(t={t})"
    elif opts.binarization == "sauvola":
        gray = sauvola(gray)
        report["binarization"] = "sauvola"
    if opts.despeckle and opts.binarization != "none":
        gray = despeckle(gray)
        report["despeckle"] = True
    return Image.fromarray(gray), report


def geometry_preview(image: Image.Image, opts: PreprocessOptions, report: dict):
    """Цветная копия страницы с той же геометрией, что у результата ``preprocess``.

    Повторяет увеличение и выравнивание наклона, но без шумоподавления и бинаризации,
    поэтому рамки слов, найденные на обработанном изображении, подходят и к этой копии.

    Args:
        image: Исходное изображение (то же, что подавалось в ``preprocess``).
        opts: Те же параметры, что и в ``preprocess``.
        report: Отчёт, который вернул ``preprocess``.
    """
    img = ImageOps.exif_transpose(image).convert("RGB")
    if opts.upscale_min_side and min(img.size) < opts.upscale_min_side:
        factor = min(opts.upscale_min_side / max(min(img.size), 1), 4.0)
        img = img.resize(
            (int(img.width * factor), int(img.height * factor)), Image.Resampling.LANCZOS
        )
    angle = float(report.get("deskew_deg", 0.0))
    if abs(angle) >= 0.2:
        img = img.rotate(
            angle, resample=Image.Resampling.BICUBIC, expand=True, fillcolor=(255, 255, 255)
        )
    return img


def detect_orientation(image: Image.Image):
    """Поворот текста (0/90/180/270) по данным Tesseract OSD; 0, если недоступно."""
    pytesseract = optional_import("pytesseract")
    if pytesseract is None:
        return 0
    try:
        osd = pytesseract.image_to_osd(image, output_type=pytesseract.Output.DICT)
    except Exception:
        return 0
    return int(osd.get("rotate", 0)) % 360


def png_bytes(image: Image.Image):
    """Закодировать изображение в PNG."""
    buf = io.BytesIO()
    image.save(buf, "PNG")
    return buf.getvalue()
