from __future__ import annotations

import contextlib
import multiprocessing
import os
import shutil
import tempfile
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path

from krmanfi_search.domain import SearchHit, SearchQuery, SearchStats, TextChunk
from krmanfi_search.infrastructure.archives import (
    ARCHIVE_EXTENSIONS,
    MAX_ARCHIVE_DEPTH,
    MAX_MEMBER_BYTES,
    MAX_TOTAL_BYTES,
    ZipReader,
)
from krmanfi_search.infrastructure.search.extractors import (
    DOCUMENT_EXTENSIONS,
    ExtractorRegistry,
    ImageOcr,
    pdf_page_count,
)
from krmanfi_search.infrastructure.search.matchers import Matcher, make_matcher
from krmanfi_search.shared.exceptions import OperationCancelledError, SecurityLimitError
from krmanfi_search.shared.logging import get_logger
from krmanfi_search.shared.types import CancelToken, ProgressCallback

log = get_logger(__name__)

MAX_HITS_PER_LOCATION = 200
PAGES_PER_PART = 4
SPLIT_PDF_MIN_BYTES = 1_000_000
POOL_MIN_FILES = 30
TEMP_PREFIX = "krmanfi-search-"
ARCHIVE_SEPARATOR = "!/"

type OcrFactory = Callable[[], ImageOcr | None]
type Pages = tuple[int, int | None] | None


@dataclass(frozen=True, slots=True)
class _Job:
    """Единица извлечения: реальный файл или файл, распакованный из архива."""

    key: str
    path: Path
    real: Path
    ext: str


@dataclass(frozen=True, slots=True)
class _Part:
    """Единица работы пула: файл целиком или диапазон страниц большого PDF."""

    job: _Job
    pages: Pages = None
    page_count: int = 0

    def label(self):
        """Текст для строки состояния."""
        name = Path(self.job.key.rsplit(ARCHIVE_SEPARATOR, 1)[-1]).name
        if self.pages is None:
            return name
        start, stop = self.pages
        return f"{name}: стр. {start + 1}–{stop} из {self.page_count}"


@dataclass(slots=True)
class _Assembly:
    """Куски одного файла, собираемые до завершения всех его частей."""

    parts_left: int
    error: BaseException | None = None


_WORKER = {}


def _worker_init(ocr_factory: OcrFactory | None, pdf_dpi: int):
    """Инициализировать реестры извлечения в рабочем процессе пула."""
    from krmanfi_search.shared.logging import configure_logging

    configure_logging("WARNING", to_file=False)
    ocr = ocr_factory() if ocr_factory is not None else None
    _WORKER["ocr"] = ExtractorRegistry(ocr, pdf_dpi)
    _WORKER["plain"] = ExtractorRegistry(None, pdf_dpi)


def _worker_extract(path: str, ext: str, use_ocr: bool, pages: Pages):
    """Извлечь текст в рабочем процессе и вернуть обычные словари."""
    registry = _WORKER["ocr" if use_ocr else "plain"]
    return [c.model_dump() for c in registry.extract(Path(path), ext, CancelToken(), pages)]


def _close_pool(pool: ProcessPoolExecutor, terminate: bool):
    """Закрыть пул; при отмене или ошибке принудительно завершить процессы."""
    workers = list((getattr(pool, "_processes", None) or {}).values())
    pool.shutdown(wait=not terminate, cancel_futures=True)
    if not terminate:
        return
    for proc in workers:
        with contextlib.suppress(Exception):
            proc.terminate()
    for proc in workers:
        with contextlib.suppress(Exception):
            proc.join(timeout=5)


def default_workers():
    """Число процессов извлечения: ядра минус одно, но не больше 8."""
    return max(1, min(8, (os.cpu_count() or 2) - 1))


def _walk(root: Path, cancel: CancelToken):
    """Обойти папку без перехода по ссылкам; недоступные папки пропускаются."""
    stack = [root]
    while stack:
        cancel.raise_if_cancelled()
        folder = stack.pop()
        try:
            with os.scandir(folder) as it:
                entries = sorted(it, key=lambda e: e.name.lower(), reverse=True)
        except OSError as exc:
            log.info("search.folder_skipped", folder=str(folder), reason=str(exc))
            continue
        for entry in entries:
            try:
                if entry.is_symlink():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    stack.append(Path(entry.path))
                elif entry.is_file(follow_symlinks=False):
                    yield Path(entry.path), entry.stat(follow_symlinks=False).st_size
            except OSError:
                continue


class TextSearchService:
    """Поиск текста: обход → (распаковка ZIP) → извлечение → сопоставление."""

    def __init__(
        self,
        *,
        ocr_factory: OcrFactory | None = None,
        ocr_available: Callable[[], bool] | None = None,
        pdf_dpi: int = 300,
        workers: int = 0,
    ):
        """Создать движок.

        Args:
            ocr_factory: Фабрика функции распознавания; вызывается в рабочих процессах.
            ocr_available: Проверка, что OCR реально работает в этом процессе.
            pdf_dpi: Разрешение отрисовки страниц для OCR.
            workers: Число процессов извлечения; ``0`` — в текущем процессе.
        """
        self._ocr_factory = ocr_factory
        self._ocr_available = ocr_available or (lambda: ocr_factory is not None)
        self._pdf_dpi = pdf_dpi
        self._workers = workers

    def search(
        self,
        query: SearchQuery,
        *,
        progress: ProgressCallback,
        cancel: CancelToken,
        stats: SearchStats,
    ):
        """Выдавать совпадения по мере обработки файлов.

        Raises:
            SearchError: Для неверного регулярного выражения.
            OperationCancelledError: Если поиск отменён.
        """
        return _Run(self, query, progress, cancel, stats).hits()


class _Run:
    """Состояние одного прогона: статистика, временная папка, счётчики прогресса."""

    def __init__(
        self,
        service: TextSearchService,
        query: SearchQuery,
        progress: ProgressCallback,
        cancel: CancelToken,
        stats: SearchStats,
    ):
        """Запомнить параметры прогона."""
        self._svc = service
        self._query = query
        self._progress = progress
        self._cancel = cancel
        self._stats = stats
        self._use_ocr = query.ocr_scanned_pdfs and service._ocr_available()
        self._extensions = DOCUMENT_EXTENSIONS | (
            ARCHIVE_EXTENSIONS if query.include_archives else frozenset()
        )
        self._total = 0
        self._done = 0
        self._extracted = 0
        self._local = None

    def hits(self):
        """Главный генератор совпадений."""
        matcher = make_matcher(self._query)
        stats = self._stats
        stats.ocr_available = self._use_ocr
        self._progress(0, 0, "Сбор файлов…")
        files = list(self._collect())
        stats.files_total = len(files)
        self._total = len(files)
        self._progress(0, self._total, f"Файлов для поиска: {self._total}")
        tmp_root = Path(tempfile.mkdtemp(prefix=TEMP_PREFIX))
        seen = set()
        try:
            for job, chunks in self._process(files, tmp_root):
                for hit in self._match(job, chunks, matcher):
                    stats.hits += 1
                    if hit.display_path not in seen:
                        seen.add(hit.display_path)
                        stats.hit_files += 1
                    yield hit
            self._progress(self._total, self._total, "Готово")
        finally:
            shutil.rmtree(tmp_root, ignore_errors=True)

    def _advance(self, message: str, units: int = 1):
        """Сообщить о завершённых единицах работы."""
        self._done = min(self._done + units, self._total)
        self._progress(self._done, self._total, message)

    def _grow(self, units: int):
        """Добавить единицы работы, найденные по ходу (члены архива, части PDF)."""
        self._total += units

    def _collect(self):
        """Задания для всех подходящих файлов под корнем запроса."""
        root = self._query.root
        entries = [(root, root.stat().st_size)] if root.is_file() else _walk(root, self._cancel)
        for path, size in entries:
            ext = path.suffix.lower().lstrip(".")
            if ext not in self._extensions:
                continue
            if size > self._query.max_file_size:
                self._stats.add_skipped(str(path))
                continue
            yield _Job(str(path), path, path, ext)

    def _failed(self, key: str, exc: BaseException):
        """Записать ошибку файла."""
        reason = f"{type(exc).__name__}: {exc}"
        log.info("search.extract_failed", file=key, error=reason)
        self._stats.add_error(key, reason)

    def _process(self, files: list[_Job], tmp_root: Path):
        """Выдавать ``(задание, куски)``: сразу для текстовых форматов, пулом — для PDF."""
        pending = []
        for job in files:
            self._cancel.raise_if_cancelled()
            self._stats.scanned += 1
            if job.ext in ARCHIVE_EXTENSIONS:
                self._advance(job.key)
                self._stats.archives += 1
                for member in self._expand_archive(job, tmp_root, 1):
                    self._stats.scanned += 1
                    self._grow(1)
                    pending.append(member)
                continue
            pending.append(job)
        yield from self._extract_all(pending)

    def _expand_archive(self, job: _Job, tmp_root: Path, depth: int):
        """Безопасно распаковать поддерживаемые записи ZIP (вложенные — рекурсивно)."""
        dest = Path(tempfile.mkdtemp(dir=tmp_root))
        try:
            with ZipReader(job.path) as reader:
                for slot, info in enumerate(reader.members()):
                    self._cancel.raise_if_cancelled()
                    if info.is_dir():
                        continue
                    name = info.filename.lower()
                    ext = next((e for e in self._extensions if name.endswith(f".{e}")), "")
                    if not ext:
                        continue
                    key = f"{job.key}{ARCHIVE_SEPARATOR}{info.filename}"
                    if info.flag_bits & 0x1:
                        self._stats.add_error(key, "запись архива зашифрована паролем")
                        continue
                    budget = MAX_TOTAL_BYTES - self._extracted
                    if budget <= 0:
                        raise SecurityLimitError(
                            "превышен общий объём распаковки для одного поиска"
                        )
                    try:
                        target = reader.extract(info, dest, min(MAX_MEMBER_BYTES, budget), slot)
                    except OperationCancelledError:
                        raise
                    except Exception as exc:
                        self._failed(key, exc)
                        continue
                    self._extracted += target.stat().st_size
                    child = _Job(key, target, job.real, ext)
                    if ext in ARCHIVE_EXTENSIONS:
                        if depth < MAX_ARCHIVE_DEPTH:
                            yield from self._expand_archive(child, tmp_root, depth + 1)
                    else:
                        yield child
        except OperationCancelledError:
            raise
        except Exception as exc:
            self._failed(job.key, exc)

    def _split(self, jobs: list[_Job]):
        """Разрезать большие PDF на диапазоны страниц, если возможен OCR."""
        parts = []
        for job in jobs:
            pages = 0
            if (
                self._use_ocr
                and job.ext == "pdf"
                and job.path.stat().st_size >= SPLIT_PDF_MIN_BYTES
            ):
                pages = pdf_page_count(job.path)
            if pages > PAGES_PER_PART:
                ranges = [
                    (start, min(start + PAGES_PER_PART, pages))
                    for start in range(0, pages, PAGES_PER_PART)
                ]
                self._grow(len(ranges) - 1)
                parts += [_Part(job, r, pages) for r in ranges]
            else:
                parts.append(_Part(job))
        return parts

    def _extract_all(self, jobs: list[_Job]):
        """Извлечь текст файлов по частям; выдавать результаты по мере готовности."""
        if not jobs:
            return
        parts = self._split(jobs)
        files = {}
        for part in parts:
            files.setdefault(part.job.key, _Assembly(0)).parts_left += 1
        with_text = set()
        for part, chunks, error in self._run_parts(parts):
            entry = files[part.job.key]
            entry.parts_left -= 1
            if error is not None:
                entry.error = entry.error or error
            elif chunks:
                with_text.add(part.job.key)
            self._advance(part.label())
            if chunks:
                yield part.job, chunks
            if entry.parts_left == 0:
                if entry.error is not None:
                    self._failed(part.job.key, entry.error)
                elif part.job.key in with_text:
                    self._stats.with_text += 1
                else:
                    self._stats.add_no_text(part.job.key)
                del files[part.job.key]

    def _use_pool(self, parts: list[_Part]):
        """Нужен ли пул процессов: есть что распознавать или много файлов."""
        if self._svc._workers <= 0:
            return False
        has_pdf = any(p.job.ext == "pdf" for p in parts)
        return (self._use_ocr and has_pdf) or len(parts) >= POOL_MIN_FILES

    def _run_parts(self, parts: list[_Part]):
        """Выдавать ``(часть, куски, ошибка)`` по мере завершения (пул или текущий процесс)."""
        if not self._use_pool(parts):
            yield from self._run_local(parts)
            return
        pool = ProcessPoolExecutor(
            max_workers=self._svc._workers,
            mp_context=multiprocessing.get_context("spawn"),
            initializer=_worker_init,
            initargs=(self._svc._ocr_factory, self._svc._pdf_dpi),
        )
        completed = False
        try:
            futures = {
                pool.submit(_worker_extract, str(p.job.path), p.job.ext, self._use_ocr, p.pages): p
                for p in parts
            }
            remaining = set(futures)
            while remaining:
                if self._cancel.cancelled:
                    raise OperationCancelledError("cancelled")
                finished, remaining = wait(remaining, timeout=0.2, return_when=FIRST_COMPLETED)
                for future in finished:
                    part = futures[future]
                    try:
                        chunks = [TextChunk.model_validate(c) for c in future.result()]
                    except Exception as exc:
                        yield part, [], exc
                        continue
                    yield part, chunks, None
            completed = True
        finally:
            _close_pool(pool, terminate=not completed)

    def _run_local(self, parts: list[_Part]):
        """Извлечение в текущем процессе."""
        if self._local is None:
            factory = self._svc._ocr_factory if self._use_ocr else None
            ocr = factory() if factory is not None else None
            self._local = ExtractorRegistry(ocr, self._svc._pdf_dpi)
        for part in parts:
            self._cancel.raise_if_cancelled()
            try:
                chunks = self._local.extract(part.job.path, part.job.ext, self._cancel, part.pages)
            except OperationCancelledError:
                raise
            except Exception as exc:
                yield part, [], exc
                continue
            yield part, chunks, None

    def _match(self, job: _Job, chunks: list[TextChunk], matcher: Matcher):
        """Превратить каждое вхождение в отдельное совпадение с контекстом."""
        context_chars = self._query.context_chars
        for chunk in chunks:
            matches = sorted(matcher.find(chunk.text), key=lambda m: (m.start, -m.end))
            distinct = []
            last_end = -1
            for m in matches:
                if m.start >= last_end:
                    distinct.append(m)
                    last_end = m.end
            for number, m in enumerate(distinct[:MAX_HITS_PER_LOCATION], start=1):
                start = max(m.start - context_chars, 0)
                end = min(m.end + context_chars, len(chunk.text))
                context = " ".join(chunk.text[start:end].split())
                yield SearchHit(
                    display_path=job.key,
                    real_path=job.real,
                    location=chunk.location,
                    page=chunk.page,
                    fragment=chunk.text[m.start : m.end][:500],
                    context=("…" if start else "")
                    + context
                    + ("…" if end < len(chunk.text) else ""),
                    match_count=len(distinct),
                    occurrence=number,
                    offset=m.start,
                )
