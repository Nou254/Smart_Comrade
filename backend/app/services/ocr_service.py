"""
OCR service — extract raw text from pages.

Strategy:
  1. If file is a text-based PDF, extract text directly (no OCR).
  2. Otherwise, run Tesseract OCR on the rendered page image.
  3. Return per-page raw text.

The structured extraction (into code/title/time) happens in extraction_service.
"""
import io
import logging

from app.core.config import settings

logger = logging.getLogger(__name__)

# ── Optional dependencies ──────────────────────────────────────
try:
    import pymupdf
    _HAS_PYMUPDF = True
except Exception:
    try:
        import fitz as pymupdf
        _HAS_PYMUPDF = True
    except Exception:
        _HAS_PYMUPDF = False
        logger.warning("pymupdf not installed — PDF parsing disabled")

try:
    import pytesseract
    from PIL import Image
    _HAS_TESSERACT = True
    if settings.TESSERACT_CMD:
        pytesseract.pytesseract.tesseract_cmd = settings.TESSERACT_CMD
except Exception:
    _HAS_TESSERACT = False
    logger.warning("pytesseract or Pillow not installed — OCR will be limited")


# ── Data type ──────────────────────────────────────────────────

class PageOCRResult:
    __slots__ = ("page_number", "raw_text", "confidence", "method")

    def __init__(self, page_number: int, raw_text: str,
                 confidence: float | None, method: str):
        self.page_number = page_number
        self.raw_text = raw_text
        self.confidence = confidence
        self.method = method

    def __repr__(self) -> str:
        return (
            f"<PageOCRResult page={self.page_number} "
            f"method={self.method} conf={self.confidence}>"
        )


class OCRError(Exception):
    def __init__(self, message: str, status_code: int = 500):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


# ── Text extraction from PDFs with embedded text ───────────────

def _extract_pdf_text_layer(file_path: str, page_number: int) -> str | None:
    if not _HAS_PYMUPDF:
        return None
    try:
        with pymupdf.open(file_path) as doc:
            page = doc.load_page(page_number - 1)
            text = page.get_text("text")
            if text and len(text.strip()) >= 50:
                return text
            return None
    except Exception as e:
        logger.warning(f"PDF text-layer extraction failed: {e}")
        return None


# ── Tesseract OCR on a rendered page image ─────────────────────

def _render_pdf_page_png(file_path: str, page_number: int,
                         zoom: float = 2.0) -> bytes | None:
    if not _HAS_PYMUPDF:
        return None
    try:
        with pymupdf.open(file_path) as doc:
            page = doc.load_page(page_number - 1)
            pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
            return pix.tobytes("png")
    except Exception as e:
        logger.warning(f"PDF page render failed: {e}")
        return None


def _tesseract_ocr(image_bytes: bytes) -> tuple[str, float | None]:
    if not _HAS_TESSERACT:
        raise OCRError("Tesseract is not installed on the server.", 500)
    try:
        img = Image.open(io.BytesIO(image_bytes))
        data = pytesseract.image_to_data(
            img, output_type=pytesseract.Output.DICT, config="--psm 6",
        )
        text = pytesseract.image_to_string(img, config="--psm 6")

        confs = [
            int(c) for c in data.get("conf", [])
            if str(c).lstrip("-").isdigit()
        ]
        confs = [c for c in confs if c >= 0]
        avg_conf = (sum(confs) / len(confs) / 100.0) if confs else None

        return text, avg_conf
    except Exception as e:
        logger.exception(f"Tesseract OCR failed: {e}")
        raise OCRError(f"Tesseract OCR failed: {e}", 500)


# ── Public API ─────────────────────────────────────────────────

def scan_page(file_path: str, extension: str, page_number: int) -> PageOCRResult:
    """
    Extract raw text from a single page.

    Strategy:
      - PDF with text layer → return extracted text (no OCR needed)
      - PDF scanned → render page → Tesseract
      - Image file → Tesseract directly
      - Other formats → not yet supported
    """
    ext = extension.lower()

    if ext == "pdf":
        text = _extract_pdf_text_layer(file_path, page_number)
        if text:
            return PageOCRResult(
                page_number=page_number,
                raw_text=text,
                confidence=0.99,
                method="text_layer",
            )
        png = _render_pdf_page_png(file_path, page_number)
        if not png:
            return PageOCRResult(
                page_number=page_number,
                raw_text="",
                confidence=0.0,
                method="failed",
            )
        text, conf = _tesseract_ocr(png)
        return PageOCRResult(
            page_number=page_number,
            raw_text=text,
            confidence=conf,
            method="tesseract",
        )

    if ext in ("png", "jpg", "jpeg"):
        with open(file_path, "rb") as fh:
            img_bytes = fh.read()
        text, conf = _tesseract_ocr(img_bytes)
        return PageOCRResult(
            page_number=page_number,
            raw_text=text,
            confidence=conf,
            method="tesseract",
        )

    return PageOCRResult(
        page_number=page_number,
        raw_text="",
        confidence=0.0,
        method="failed",
    )