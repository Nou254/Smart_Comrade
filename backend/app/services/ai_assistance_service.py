"""
AI assistance — Module 005.

Every AI call in the platform is routed through the single HTTP client in
this module. It speaks the OpenAI `/chat/completions` protocol, so it works
against Groq, OpenAI, or any compatible gateway. The endpoint is selected
with `settings.AI_API_BASE` and the credential with `settings.AI_API_KEY`
(falling back to `GROQ_API_KEY` / `OPENAI_API_KEY`).

Router policy:
  - draft / validate        → cheap models
  - grade / hint / research → mid-tier models
  - summarize / high_stakes → premium models

Any call that cannot reach the provider raises `AIError` with a clear
message; callers translate that to HTTP 502.
"""
import json
import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy.orm import Session

from app.models.assessment import (
    AIAssistanceLog,
    AI_ACTION_DRAFT, AI_ACTION_VALIDATE, AI_ACTION_GRADE,
    AI_ACTION_SUMMARIZE, AI_ACTION_HINT,
    AI_ENTITY_ASSESSMENT, AI_ENTITY_QUESTION,
    AI_ENTITY_RESPONSE, AI_ENTITY_RESULT, AI_ENTITY_REPORT,
)
from app.core.config import settings


logger = logging.getLogger(__name__)


class AIError(Exception):
    def __init__(self, message: str, status_code: int = 502):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


# ─────────────────────────────────────────────────────────────────────────
# ROUTER
# ─────────────────────────────────────────────────────────────────────────

def _model_for_action(action: str) -> str:
    """Route based on task. Model ids are configurable via env."""
    if action in (AI_ACTION_DRAFT, AI_ACTION_VALIDATE):
        return settings.AI_MODEL_CHEAP
    if action in (AI_ACTION_GRADE, AI_ACTION_HINT):
        return settings.AI_MODEL_MID
    if action in (AI_ACTION_SUMMARIZE,):
        return settings.AI_MODEL_PREMIUM
    return settings.AI_MODEL_CHEAP


# ─────────────────────────────────────────────────────────────────────────
# LLM CLIENT
# ─────────────────────────────────────────────────────────────────────────

def _resolve_api_key() -> str | None:
    return settings.AI_API_KEY or settings.GROQ_API_KEY or settings.OPENAI_API_KEY


def _resolve_api_base() -> str:
    """
    Pick the API base URL. If no explicit AI_API_KEY is configured but an
    OpenAI key is, target OpenAI rather than the default Groq base so the
    credential and the endpoint agree.
    """
    if settings.AI_API_KEY:
        return settings.AI_API_BASE.rstrip("/")
    if settings.OPENAI_API_KEY and not settings.GROQ_API_KEY:
        return "https://api.openai.com/v1"
    return settings.AI_API_BASE.rstrip("/")


def chat_completion(
    *,
    prompt: str,
    system: str | None = None,
    model: str | None = None,
    max_tokens: int | None = None,
    temperature: float = 0.2,
    json_mode: bool = False,
) -> tuple[str, dict]:
    """
    Run one chat completion. Returns `(text, usage)`.

    Raises AIError on any configuration or transport problem so callers
    never silently receive invented content.
    """
    if not settings.AI_ENABLED:
        raise AIError("AI assistance is disabled (AI_ENABLED=false).", 503)

    api_key = _resolve_api_key()
    if not api_key:
        raise AIError(
            "No AI credential configured. Set AI_API_KEY (or GROQ_API_KEY / "
            "OPENAI_API_KEY).",
            503,
        )

    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload: dict = {
        "model": model or settings.AI_MODEL_MID,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens or settings.AI_MAX_TOKENS,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    url = f"{_resolve_api_base()}/chat/completions"
    try:
        with httpx.Client(timeout=settings.AI_TIMEOUT_SECONDS) as client:
            resp = client.post(
                url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
    except httpx.HTTPError as e:
        logger.exception("AI request to %s failed", url)
        raise AIError(f"AI provider unreachable: {e}", 502)

    if resp.status_code >= 400:
        logger.error("AI provider returned %s: %s", resp.status_code, resp.text[:500])
        raise AIError(
            f"AI provider returned {resp.status_code}: {resp.text[:200]}", 502,
        )

    try:
        data = resp.json()
        text = data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, ValueError) as e:
        raise AIError(f"Malformed AI response: {e}", 502)

    usage = data.get("usage") or {}
    return text, {
        "prompt_tokens": int(usage.get("prompt_tokens", 0) or 0),
        "completion_tokens": int(usage.get("completion_tokens", 0) or 0),
    }


def _parse_json(text: str) -> dict | list:
    """Extract a JSON object/array from a model response, fenced or not."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()
    try:
        return json.loads(cleaned)
    except ValueError:
        for opener, closer in (("{", "}"), ("[", "]")):
            start = cleaned.find(opener)
            end = cleaned.rfind(closer)
            if start != -1 and end > start:
                try:
                    return json.loads(cleaned[start:end + 1])
                except ValueError:
                    continue
    raise AIError("AI response was not valid JSON.", 502)


# ── prompt scaffolding ───────────────────────────────────────────────────

_DRAFT_SYSTEM = (
    "You are an academic assessment designer. Produce clear, unambiguous "
    "assessment questions aligned to the supplied learning outcomes. "
    "Respond with JSON only."
)

_VALIDATE_SYSTEM = (
    "You are an assessment quality reviewer. Check the question for "
    "ambiguity, bias, and clarity. Respond with JSON only."
)

_GRADE_SYSTEM = (
    "You are a fair, rubric-driven academic grader. Score the student's "
    "answer and justify it with reference to the question. Your score is "
    "preliminary and must be confirmed by a human evaluator. JSON only."
)

_SUMMARIZE_SYSTEM = (
    "You summarise assessment analytics for a lecturer in plain language. "
    "Be concise and factual. Do not invent numbers. Plain text only."
)


# ─────────────────────────────────────────────────────────────────────────
# ENTRY POINTS
# ─────────────────────────────────────────────────────────────────────────

def draft_questions(
    db: Session, *, actor_id: str, assessment_id: str,
    unit_title: str, learning_outcomes: list[str], count: int = 5,
    difficulty: str = "intermediate",
) -> dict:
    """Draft assessment questions from learning outcomes using the LLM."""
    action = AI_ACTION_DRAFT
    model = _model_for_action(action)

    outcomes = "\n".join(f"- {o}" for o in learning_outcomes) or "- (none supplied)"
    prompt = (
        f"Unit: {unit_title}\n"
        f"Difficulty: {difficulty}\n"
        f"Learning outcomes:\n{outcomes}\n\n"
        f"Write exactly {count} questions. Return a JSON object of the form "
        '{"questions": [{"text": "...", "question_type": "essay", '
        '"difficulty": "..."}]} using only these question_type values: '
        "multiple_choice, true_false, short_answer, essay."
    )

    text, usage = chat_completion(
        prompt=prompt, system=_DRAFT_SYSTEM, model=model, json_mode=True,
    )
    try:
        parsed = _parse_json(text)
    except AIError as e:
        _log(
            db, entity_type=AI_ENTITY_ASSESSMENT, entity_id=assessment_id,
            action=action, model=model, actor_id=actor_id,
            request_summary=f"draft {count} questions for {unit_title}",
            response_summary="unparseable response", succeeded=False,
            error_message=e.message, **usage,
        )
        raise

    drafts = parsed.get("questions") if isinstance(parsed, dict) else parsed
    if not isinstance(drafts, list):
        raise AIError("AI returned no question list.", 502)

    _log(
        db, entity_type=AI_ENTITY_ASSESSMENT, entity_id=assessment_id,
        action=action, model=model, actor_id=actor_id,
        request_summary=f"draft {count} questions for {unit_title}",
        response_summary=f"produced {len(drafts)} drafts", **usage,
    )
    return {"drafts": drafts, "model_used": model}


def validate_question(
    db: Session, *, actor_id: str, question_id: str, text: str,
) -> dict:
    """Validate a question for ambiguity, bias and clarity using the LLM."""
    action = AI_ACTION_VALIDATE
    model = _model_for_action(action)

    prompt = (
        "Review this assessment question and return JSON of the form "
        '{"status": "passed"|"issues_found", "issues": ["..."], '
        '"notes": "..."}.\n\n'
        f"Question:\n{text}"
    )
    raw, usage = chat_completion(
        prompt=prompt, system=_VALIDATE_SYSTEM, model=model, json_mode=True,
    )
    result = _parse_json(raw)
    if not isinstance(result, dict):
        raise AIError("AI validation response was not an object.", 502)

    _log(
        db, entity_type=AI_ENTITY_QUESTION, entity_id=question_id,
        action=action, model=model, actor_id=actor_id,
        request_summary=f"validate question len={len(text)}",
        response_summary=str(result.get("status", "unknown")), **usage,
    )
    return {"result": result, "model_used": model}


def preliminary_grade(
    db: Session, *, actor_id: str, response_id: str,
    question_text: str, student_answer: str, rubric: str | None = None,
) -> dict:
    """
    Preliminary score for a subjective response.
    Human evaluator MUST confirm before this becomes official.
    """
    action = AI_ACTION_GRADE
    model = _model_for_action(action)

    prompt = (
        f"Question:\n{question_text}\n\n"
        f"Rubric:\n{rubric or '(no rubric supplied - grade holistically)'}\n\n"
        f"Student answer:\n{student_answer}\n\n"
        "Return JSON of the form "
        '{"preliminary_score": 0-100, "rationale": "...", '
        '"confidence": 0.0-1.0}.'
    )
    raw, usage = chat_completion(
        prompt=prompt, system=_GRADE_SYSTEM, model=model, json_mode=True,
    )
    result = _parse_json(raw)
    if not isinstance(result, dict):
        raise AIError("AI grading response was not an object.", 502)

    _log(
        db, entity_type=AI_ENTITY_RESPONSE, entity_id=response_id,
        action=action, model=model, actor_id=actor_id,
        request_summary=f"grade response len={len(student_answer)}",
        response_summary=str(result.get("preliminary_score")), **usage,
    )
    return {"result": result, "model_used": model}


def summarize_analytics(
    db: Session, *, actor_id: str, assessment_id: str,
    stats: dict,
) -> dict:
    """Natural-language summary of assessment analytics."""
    action = AI_ACTION_SUMMARIZE
    model = _model_for_action(action)

    prompt = (
        "Summarise the following assessment statistics in 2-4 sentences for "
        "the lecturer who owns the assessment. Highlight participation, "
        "performance, and anything that needs attention.\n\n"
        f"Statistics (JSON):\n{json.dumps(stats, default=str)}"
    )
    summary, usage = chat_completion(
        prompt=prompt, system=_SUMMARIZE_SYSTEM, model=model,
    )

    _log(
        db, entity_type=AI_ENTITY_REPORT, entity_id=assessment_id,
        action=action, model=model, actor_id=actor_id,
        request_summary="summarize analytics",
        response_summary=(summary[:120] if summary else "empty"), **usage,
    )
    return {"summary": summary, "model_used": model}


# ─────────────────────────────────────────────────────────────────────────
# AUDIT LOG
# ─────────────────────────────────────────────────────────────────────────

def _log(
    db: Session, *,
    entity_type: str, entity_id: str | None,
    action: str, model: str, actor_id: str | None,
    request_summary: str | None = None,
    response_summary: str | None = None,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    cost_usd: float | None = None,
    succeeded: bool = True,
    error_message: str | None = None,
) -> None:
    db.add(AIAssistanceLog(
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        model_used=model,
        actor_id=actor_id,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost_usd=cost_usd,
        request_summary=request_summary,
        response_summary=response_summary,
        succeeded=succeeded,
        error_message=error_message,
    ))
    db.commit()


def list_logs(
    db: Session, *, entity_type: str | None = None,
    entity_id: str | None = None, actor_id: str | None = None,
    limit: int = 500,
) -> list[AIAssistanceLog]:
    q = db.query(AIAssistanceLog)
    if entity_type:
        q = q.filter(AIAssistanceLog.entity_type == entity_type)
    if entity_id:
        q = q.filter(AIAssistanceLog.entity_id == entity_id)
    if actor_id:
        q = q.filter(AIAssistanceLog.actor_id == actor_id)
    return q.order_by(AIAssistanceLog.created_at.desc()).limit(limit).all()


def cost_summary(db: Session) -> dict:
    from sqlalchemy import func
    total = db.query(func.coalesce(func.sum(AIAssistanceLog.cost_usd), 0)).scalar()
    calls = db.query(func.count(AIAssistanceLog.id)).scalar()
    failed = db.query(func.count(AIAssistanceLog.id)).filter(
        AIAssistanceLog.succeeded.is_(False),
    ).scalar()
    return {
        "total_calls": int(calls or 0),
        "total_cost_usd": float(total or 0.0),
        "failed_calls": int(failed or 0),
    }