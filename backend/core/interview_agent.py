import json
from typing import Any

from langchain.agents import create_agent
from langgraph.checkpoint.memory import InMemorySaver

from app.llms import get_chat_model


_CHECKPOINTER = InMemorySaver()
_AGENT = None


def _extract_text_from_result(result: Any) -> str:
    if isinstance(result, dict):
        messages = result.get("messages") or []
        if messages:
            last = messages[-1]
            content = getattr(last, "content", None)
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                parts: list[str] = []
                for item in content:
                    if isinstance(item, dict):
                        text = item.get("text")
                        if text:
                            parts.append(str(text))
                    elif isinstance(item, str):
                        parts.append(item)
                if parts:
                    return "\n".join(parts)
    if isinstance(result, str):
        return result
    return str(result)


def get_interview_agent():
    global _AGENT
    if _AGENT is None:
        _AGENT = create_agent(
            model=get_chat_model(),
            tools=[],
            checkpointer=_CHECKPOINTER,
            system_prompt=(
                "You are a strict but fair technical interviewer. "
                "Use plain text only. No markdown. Keep follow-ups focused."
            ),
        )
    return _AGENT


def generate_opening_question(
    session_id: str,
    role: str,
    level: str,
    difficulty: str,
    focus_areas: list[str] | None,
    default_questions: list[str] | None,
) -> str:
    agent = get_interview_agent()
    focus = " | ".join(focus_areas or []) or "problem solving"

    # If default questions are provided, use the first one directly
    if default_questions and len(default_questions) > 0:
        return default_questions[0]

    prompt = (
        "Start an interview with one concise opening question. "
        f"Role: {role}. Level: {level}. Difficulty: {difficulty}. "
        f"Focus areas (topics to cover): {focus}."
    )
    try:
        result = agent.invoke(
            {"messages": [{"role": "user", "content": prompt}]},
            config={"configurable": {"thread_id": session_id}},
        )
        text = _extract_text_from_result(result).strip()
    except Exception:
        text = ""
    return text or "Tell me about a challenging technical problem you solved recently."


def evaluate_and_generate_followup(
    session_id: str,
    role: str,
    level: str,
    difficulty: str,
    focus_areas: list[str] | None,
    candidate_response: str,
    max_followup_depth: int = 2,
    current_topic_turns: int = 0,
    default_questions: list[str] | None = None,
    current_turn: int = 0,
) -> dict[str, Any]:
    agent = get_interview_agent()
    focus = " | ".join(focus_areas or []) or "problem solving"
    topic_instruction = ""
    if current_topic_turns >= max_followup_depth:
        topic_instruction = (
            "IMPORTANT: You have already asked enough follow-up questions on the current topic. "
            "Your next_question MUST move to a completely different topic or focus area. "
            "Do NOT ask another drill-down question on the same subject."
        )

    # If there's a predefined default question for the next turn, instruct agent to use it
    next_default = ""
    if default_questions and current_turn < len(default_questions):
        next_default = (
            f"IMPORTANT: For your next_question, you MUST use this exact predefined question: "
            f"\"{default_questions[current_turn]}\""
        )

    prompt = (
        "Evaluate this interview response and produce the next interviewer question. "
        "Return ONLY valid JSON with keys: score (0-10 number), strengths (array of strings), "
        "improvements (array of strings), feedback (string), next_question (string). "
        f"Role: {role}. Level: {level}. Difficulty: {difficulty}. "
        f"Focus areas (topics to cover): {focus}. "
        f"{topic_instruction} "
        f"{next_default} "
        f"Candidate response: {candidate_response}"
    )
    try:
        result = agent.invoke(
            {"messages": [{"role": "user", "content": prompt}]},
            config={"configurable": {"thread_id": session_id}},
        )
        raw = _extract_text_from_result(result).strip()
    except Exception:
        raw = ""

    try:
        parsed = json.loads(raw)
        score = float(parsed.get("score", 0))
        score = max(0.0, min(10.0, score))
        return {
            "score": score,
            "strengths": parsed.get("strengths", []) or [],
            "improvements": parsed.get("improvements", []) or [],
            "feedback": str(parsed.get("feedback", "")).strip(),
            "next_question": str(parsed.get("next_question", "")).strip(),
            "raw": raw,
        }
    except Exception:
        return {
            "score": None,
            "strengths": [],
            "improvements": [],
            "feedback": "",
            "next_question": raw or "Can you walk me through your thought process in more detail?",
            "raw": raw,
        }
