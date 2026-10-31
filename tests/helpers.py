import io
import random
import zipfile
from collections.abc import Mapping
from pathlib import Path

import numpy as np
import pymupdf
from PIL import Image, ImageDraw, ImageFont


def make_zip(path: Path, members: Mapping[str, bytes | str]):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in members.items():
            archive.writestr(name, data.encode("utf-8") if isinstance(data, str) else data)
    return path


def noise_png(width: int = 200, height: int = 200, seed: int = 0):
    rng = np.random.default_rng(seed)
    pixels = rng.integers(0, 256, (height, width, 3), dtype=np.uint8)
    buffer = io.BytesIO()
    Image.fromarray(pixels).save(buffer, "PNG")
    return buffer.getvalue()


def solid_png(width: int, height: int, colour: tuple[int, int, int] = (255, 255, 255)):
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), colour).save(buffer, "PNG")
    return buffer.getvalue()


CYRILLIC_FONTS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/Library/Fonts/Arial.ttf",
)


def cyrillic_font(size: int):
    for candidate in CYRILLIC_FONTS:
        if Path(candidate).is_file():
            return ImageFont.truetype(candidate, size)
    return None


def text_image(text: str, size: int = 56, width: int = 1400, height: int = 300):
    image = Image.new("RGB", (width, height), "white")
    font = cyrillic_font(size) or ImageFont.load_default(size=size)
    ImageDraw.Draw(image).text((40, 60), text, fill="black", font=font)
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return image, buffer.getvalue()


def ruled_page(width: int = 900, height: int = 1200, angle: float = 0.0):
    image = Image.new("L", (width, height), 255)
    draw = ImageDraw.Draw(image)
    for row in range(80, height - 80, 40):
        draw.rectangle((80, row, width - 80, row + 12), fill=0)
    if angle:
        image = image.rotate(angle, resample=Image.Resampling.BICUBIC, fillcolor=255)
    return image


def make_text_pdf(path: Path, pages: list[str], password: str | None = None):
    document = pymupdf.open()
    for text in pages:
        page = document.new_page()
        if text:
            page.insert_text((72, 100), text, fontsize=14)
    if password:
        document.save(
            str(path),
            encryption=pymupdf.PDF_ENCRYPT_AES_256,
            user_pw=password,
            owner_pw=password + "-owner",
        )
    else:
        document.save(str(path))
    document.close()
    return path


def make_image_pdf(path: Path, pages: int = 1, noisy: bool = False, text: str = ""):
    document = pymupdf.open()
    for number in range(pages):
        page = document.new_page()
        data = noise_png(400, 400, seed=number) if noisy else solid_png(400, 400, (240, 240, 240))
        page.insert_image(page.rect, stream=data)
        if text:
            page.insert_text((72, 100), text, fontsize=14)
    document.save(str(path))
    document.close()
    return path


def random_text(rng: random.Random, alphabet: str, length: int):
    return "".join(rng.choice(alphabet) for _ in range(length))


def flag_member_as_encrypted(path: Path, name: str):
    data = bytearray(path.read_bytes())
    encoded = name.encode("utf-8")
    start = 0
    while (start := data.find(b"PK\x01\x02", start)) != -1:
        name_length = int.from_bytes(data[start + 28 : start + 30], "little")
        if bytes(data[start + 46 : start + 46 + name_length]) == encoded:
            data[start + 8] |= 0x01
            break
        start += 4
    path.write_bytes(bytes(data))
    return path
