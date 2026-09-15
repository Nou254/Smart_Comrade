"""
Extraction service — turn raw OCR text into structured unit records.

Strategy:
  - If OPENAI_API_KEY is set and OCR_PROVIDER allows it → use LLM
  - Otherwise → regex-based heuristic parser (best-effort, low confidence)
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


# ── Regex helpers ──────────────────────────────────────────────

UNIT_CODE_RE = re.compile(r"\b([A-Z]{2,4})\s*[-]?\s*(\d{3,4})\b")
DAY_RE = re.compile(r"\b(Mon|Tue|Wed|Thu|Fri|Sat|Sun|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b", re.IGNORECASE)
TIME_RANGE_RE = re.compile(r"(\d{1,2})[:.]?(\d{2})?\s*[-–to]+\s*(\d{1,2})[:.]?(\d{2})?")


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


# ── Regex-based parser (fallback) ──────────────────────────────

def _parse_with_regex(raw_text: str) -> list[ParsedUnit]:
    """Very best-effort. Low confidence. Group Leader will fix."""
    results: list[ParsedUnit] = []
    lines = [l.strip() for l in raw_text.splitlines() if l.strip()]

    for line in lines:
        code_match = UNIT_CODE_RE.search(line)
        if not code_match:
            continue
        code = f"{code_match.group(1)} {code_match.group(2)}"

        # Try to find a day on the same line
        day_match = DAY_RE.search(line)
        day = _normalize_day(day_match.group(1)) if day_match else None

        # Try to find a time range
        start_time = end_time = None
        tm = TIME_RANGE_RE.search(line)
        if tm:
            start_time = _normalize_time(tm.group(1), tm.group(2))
            end_time = _normalize_time(tm.group(3), tm.group(4))

        # Title = remainder after code, before day/time keywords (best-effort)
        remainder = line[code_match.end():].strip()
        # strip day + time tokens from the title
        if day_match:
            remainder = remainder.replace(day_match.group(1), "", 1).strip()
        title = remainder if 3 <= len(remainder) <= 120 else None

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


# ── AI-based parser ────────────────────────────────────────────

_AI_PROMPT = """You are extracting academic units from a university timetable page.

Extract ONLY academic units — ignore headers, footers, logos, signatures.

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
- title: the unit title, or null if not visible on the page. Do NOT invent titles.
- day_of_week: 3-letter abbreviation ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
- start_time / end_time: HH:MM in 24-hour format. Use the time column headers.
- If a unit appears in multiple slots on the same page, emit multiple entries.
- If a field is genuinely not visible, use null.
- confidence: 0..1 — how sure you are about this row.

Return JSON only. No prose.
"""


def _parse_with_ai(raw_text: str, page_number: int) -> list[ParsedUnit]:
    if not _HAS_OPENAI or not settings.OPENAI_API_KEY:
        raise RuntimeError("AI extraction not available (no OpenAI key)")

    client = OpenAI(api_key=settings.OPENAI_API_KEY)

    try:
        response = client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": _AI_PROMPT},
                {"role": "user", "content": f"Page {page_number} text:\n\n{raw_text}"},
            ],
            response_format={"type": "json_object"},
            temperature=0.0,
        )
        content = response.choices[0].message.content or "{}"
        data = json.loads(content)
    except Exception as e:
        logger.exception(f"AI extraction failed: {e}")
        return []

    units: list[ParsedUnit] = []
    for u in data.get("units", []):
        units.append(ParsedUnit(
            code=(u.get("code") or "").strip() or None,
            title=(u.get("title") or "").strip() or None,
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
    Chooses AI vs regex based on configuration.
    """
    provider = (settings.OCR_PROVIDER or "auto").lower()
    use_ai = (
        provider == "ai"
        or (provider == "auto" and _HAS_OPENAI and settings.OPENAI_API_KEY)
    )

    if use_ai:
        try:
            units = _parse_with_ai(raw_text, page_number)
            if units:
                return units
        except Exception:
            logger.warning("AI extraction failed, falling back to regex parser")

    return _parse_with_regex(raw_text)


def dedupe_units(units: list[ParsedUnit]) -> list[ParsedUnit]:
    """Remove duplicate (code, day, start) rows within a page."""
    seen = set()
    out: list[ParsedUnit] = []
    for u in units:
        key = (u.code, u.day_of_week, u.start_time)
        if key in seen:
            continue
        seen.add(key)
        out.append(u)
    return out