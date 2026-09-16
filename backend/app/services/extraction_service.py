"""
Extraction service — turn raw OCR text into structured unit records.

Provider priority (based on OCR_PROVIDER setting):
  - "groq"      → Groq LLM (fast, free tier)
  - "ai"        → OpenAI LLM
  - "auto"      → Groq if GROQ_API_KEY set, else OpenAI if set, else regex
  - "tesseract" → regex only (no LLM)
"""
import json
import logging
import re
from dataclasses import dataclass

from app.core.config import settings

logger = logging.getLogger(__name__)


try:
    from openai import OpenAI
    _HAS_OPENAI = True
except Exception:
    _HAS_OPENAI = False


@dataclass
class ParsedUnit:
    code: str | None
    title: str | None
    day_of_week: str | None
    start_time: str | None  # HH:MM
    end_time: str | None    # HH:MM
    confidence: float
    raw_text: str | None = None


# ── Regex helpers (fallback only) ──────────────────────────────

UNIT_CODE_RE = re.compile(r"\b([A-Z]{2,4})\s*[-]?\s*(\d{3,4})\b")
DAY_RE = re.compile(
    r"\b(Mon|Tue|Wed|Thu|Fri|Sat|Sun|"
    r"Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b",
    re.IGNORECASE,
)
TIME_RANGE_RE = re.compile(r"(\d{1,2})[:.]?(\d{2})?\s*[-–to]+\s*(\d{1,2})[:.]?(\d{2})?")

# Noise patterns to skip
NOISE_PATTERNS = [
    re.compile(r"^ISO\s*\d+", re.IGNORECASE),
    re.compile(r"certified", re.IGNORECASE),
    re.compile(r"^Page\s+\d+", re.IGNORECASE),
    re.compile(r"^\d+\s*of\s*\d+", re.IGNORECASE),
]

VENUE_PATTERN = re.compile(r"^\(?\s*(LAB|LR|CL|BOT\s+LAB|WS|CAD)\s*\d*\s*\)?$", re.IGNORECASE)


def _normalize_day(s: str) -> str:
    s = s.strip().lower()
    mapping = {
        "monday": "Mon", "mon": "Mon",
        "tuesday": "Tue", "tue": "Tue", "tues": "Tue",
        "wednesday": "Wed", "wed": "Wed",
        "thursday": "Thu", "thu": "Thu", "thurs": "Thu",
        "friday": "Fri", "fri": "Fri",
        "saturday": "Sat", "sat": "Sat",
        "sunday": "Sun", "sun": "Sun",
    }
    return mapping.get(s, s.title()[:3])


def _normalize_time(h: str, m: str | None) -> str:
    hour = int(h)
    minute = int(m) if m else 0
    return f"{hour:02d}:{minute:02d}"


def _is_noise(line: str) -> bool:
    for pattern in NOISE_PATTERNS:
        if pattern.search(line):
            return True
    return False


# ── Regex-based parser (fallback) ──────────────────────────────

def _parse_with_regex(raw_text: str) -> list[ParsedUnit]:
    results: list[ParsedUnit] = []
    lines = [l.strip() for l in raw_text.splitlines() if l.strip()]

    for line in lines:
        if _is_noise(line):
            continue

        code_match = UNIT_CODE_RE.search(line)
        if not code_match:
            continue

        code = f"{code_match.group(1)} {code_match.group(2)}"

        day_match = DAY_RE.search(line)
        day = _normalize_day(day_match.group(1)) if day_match else None

        start_time = end_time = None
        tm = TIME_RANGE_RE.search(line)
        if tm:
            start_time = _normalize_time(tm.group(1), tm.group(2))
            end_time = _normalize_time(tm.group(3), tm.group(4))

        # Title: remainder after code, before day/time keywords
        remainder = line[code_match.end():].strip()
        if day_match:
            remainder = remainder.replace(day_match.group(1), "", 1).strip()
        if tm:
            remainder = remainder.replace(tm.group(0), "", 1).strip()

        # Skip if title is actually a venue
        title = None
        if remainder and 3 <= len(remainder) <= 120:
            if not VENUE_PATTERN.match(remainder):
                title = remainder

        results.append(ParsedUnit(
            code=code,
            title=title,
            day_of_week=day,
            start_time=start_time,
            end_time=end_time,
            confidence=0.4,
            raw_text=line,
        ))

    return results


# ── LLM prompt (shared for Groq + OpenAI) ──────────────────────

_LLM_PROMPT = """You are extracting academic units from a university timetable page.

Extract ONLY academic units — ignore headers, footers, logos, signatures, ISO certifications, page numbers, and venue-only strings.

Return a JSON object with this exact shape:
{
  "units": [
    {
      "code": "ITB 2201",
      "title": "Operating Systems",
      "day_of_week": "Mon",
      "start_time": "12:00",
      "end_time": "14:00",
      "confidence": 0.95
    }
  ]
}

Rules:
- code: the unit code (e.g. "ITB 2201", "MAB 2201"). Preserve spaces.
- title: the unit title, or null if not visible. Do NOT invent titles. Do NOT use venue strings like "(LAB 9)" as titles.
- day_of_week: 3-letter abbreviation ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
- start_time / end_time: HH:MM in 24-hour format.
- If a unit appears in multiple slots, emit multiple entries.
- If a field is not visible, use null.
- confidence: 0..1 — how sure you are.

Return JSON only. No prose.
"""


# ── LLM parsers ────────────────────────────────────────────────

def _parse_with_groq(raw_text: str, page_number: int) -> list[ParsedUnit]:
    if not _HAS_OPENAI or not settings.GROQ_API_KEY:
        raise RuntimeError("Groq extraction not available")

    client = OpenAI(
        base_url="https://api.groq.com/openai/v1",
        api_key=settings.GROQ_API_KEY,
    )

    try:
        response = client.chat.completions.create(
            model=settings.GROQ_MODEL,
            messages=[
                {"role": "system", "content": _LLM_PROMPT},
                {"role": "user", "content": f"Page {page_number} text:\n\n{raw_text}"},
            ],
            response_format={"type": "json_object"},
            temperature=0.0,
        )
        content = response.choices[0].message.content or "{}"
        data = json.loads(content)
    except Exception as e:
        logger.exception(f"Groq extraction failed: {e}")
        return []

    units: list[ParsedUnit] = []
    for u in data.get("units", []):
        code = (u.get("code") or "").strip() or None
        title = (u.get("title") or "").strip() or None

        # Reject noise
        if code and _is_noise(code):
            continue
        if title and VENUE_PATTERN.match(title):
            title = None

        units.append(ParsedUnit(
            code=code,
            title=title,
            day_of_week=(u.get("day_of_week") or "").strip() or None,
            start_time=(u.get("start_time") or "").strip() or None,
            end_time=(u.get("end_time") or "").strip() or None,
            confidence=float(u.get("confidence") or 0.7),
            raw_text=None,
        ))
    return units


def _parse_with_openai(raw_text: str, page_number: int) -> list[ParsedUnit]:
    if not _HAS_OPENAI or not settings.OPENAI_API_KEY:
        raise RuntimeError("OpenAI extraction not available")

    client = OpenAI(api_key=settings.OPENAI_API_KEY)

    try:
        response = client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": _LLM_PROMPT},
                {"role": "user", "content": f"Page {page_number} text:\n\n{raw_text}"},
            ],
            response_format={"type": "json_object"},
            temperature=0.0,
        )
        content = response.choices[0].message.content or "{}"
        data = json.loads(content)
    except Exception as e:
        logger.exception(f"OpenAI extraction failed: {e}")
        return []

    units: list[ParsedUnit] = []
    for u in data.get("units", []):
        code = (u.get("code") or "").strip() or None
        title = (u.get("title") or "").strip() or None
        if code and _is_noise(code):
            continue
        if title and VENUE_PATTERN.match(title):
            title = None

        units.append(ParsedUnit(
            code=code,
            title=title,
            day_of_week=(u.get("day_of_week") or "").strip() or None,
            start_time=(u.get("start_time") or "").strip() or None,
            end_time=(u.get("end_time") or "").strip() or None,
            confidence=float(u.get("confidence") or 0.7),
            raw_text=None,
        ))
    return units


# ── Public API ─────────────────────────────────────────────────

def extract_units_from_text(raw_text: str, page_number: int) -> list[ParsedUnit]:
    """
    Parse a page's raw text into structured units.
    Provider selection is based on config + available keys.
    """
    provider = (settings.OCR_PROVIDER or "auto").lower()

    # Explicit provider selection
    if provider == "groq" and settings.GROQ_API_KEY:
        try:
            units = _parse_with_groq(raw_text, page_number)
            if units:
                return units
        except Exception:
            logger.warning("Groq extraction failed, falling back")

    if provider == "ai" and settings.OPENAI_API_KEY:
        try:
            units = _parse_with_openai(raw_text, page_number)
            if units:
                return units
        except Exception:
            logger.warning("OpenAI extraction failed, falling back")

    if provider == "auto":
        # Prefer Groq (free tier), then OpenAI, then regex
        if _HAS_OPENAI and settings.GROQ_API_KEY:
            try:
                units = _parse_with_groq(raw_text, page_number)
                if units:
                    return units
            except Exception:
                logger.warning("Groq extraction failed, trying OpenAI")
        if _HAS_OPENAI and settings.OPENAI_API_KEY:
            try:
                units = _parse_with_openai(raw_text, page_number)
                if units:
                    return units
            except Exception:
                logger.warning("OpenAI extraction failed, using regex")

    # Fallback
    return _parse_with_regex(raw_text)


def dedupe_units(units: list[ParsedUnit]) -> list[ParsedUnit]:
    """Remove duplicate (code, day, start) rows."""
    seen = set()
    out: list[ParsedUnit] = []
    for u in units:
        key = (u.code, u.day_of_week, u.start_time)
        if key in seen:
            continue
        seen.add(key)
        out.append(u)
    return out