"""
Code Execution API Router

Provides endpoints for:
- Running code against test cases (sample or all)
- Getting test cases for a coding question
"""

import asyncio
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from core.auth import get_current_user
from core.code_runner import ensure_execution_available, run_test_case
from core.sql_runner import run_sql_test_case
from db.models import Question, QuestionType, TestCase, User
from db.async_helpers import run_db_sync
from db.database import SessionLocal

router = APIRouter(prefix="/code", tags=["code-execution"])


# ---------- Schemas ---------- #


class TestCaseOut(BaseModel):
    id: UUID
    input_data: str
    expected_output: str
    is_sample: bool


class RunCodeRequest(BaseModel):
    question_id: UUID
    code: str
    run_sample_only: bool = True  # True = run sample test cases, False = run all
    language: str = "python"  # 'python' or 'sql'


class TestCaseResult(BaseModel):
    test_case_id: UUID
    passed: bool
    input_data: str
    expected_output: str
    actual_output: str
    error: str | None = None
    is_sample: bool


class RunCodeResponse(BaseModel):
    results: List[TestCaseResult]
    total: int
    passed: int
    failed: int
    all_passed: bool


# ---------- Endpoints ---------- #


@router.get("/test-cases/{question_id}", response_model=List[TestCaseOut])
async def get_test_cases(
    question_id: UUID,
    _user: User = Depends(get_current_user),
):
    """Get sample test cases for a coding question (visible to user during exam)."""

    def _sync_work():
        db = SessionLocal()
        try:
            question = db.query(Question).filter(Question.id == question_id).first()
            if not question:
                raise HTTPException(status_code=404, detail="Question not found")
            if question.type != QuestionType.coding:
                raise HTTPException(status_code=400, detail="Not a coding question")

            test_cases = (
                db.query(TestCase)
                .filter(TestCase.question_id == question_id, TestCase.is_sample == True)
                .limit(2)
                .all()
            )

            return [{"id": tc.id, "input_data": tc.input_data, "expected_output": tc.expected_output, "is_sample": tc.is_sample} for tc in test_cases]
        finally:
            db.close()

    results = await run_db_sync(_sync_work)
    return [TestCaseOut(**r) for r in results]


@router.post("/run", response_model=RunCodeResponse)
async def run_code(
    body: RunCodeRequest,
    _user: User = Depends(get_current_user),
):
    """
    Execute user code against test cases.

    Candidate-facing execution is limited to public sample cases regardless of
    the request body. Hidden cases are evaluated only by the server worker.
    """
    language = (body.language or "python").strip().lower()
    if language not in ("python", "sql"):
        raise HTTPException(status_code=400, detail="Invalid language. Supported: 'python', 'sql'")
    if not body.code.strip():
        raise HTTPException(status_code=400, detail="No code provided")
    if len(body.code.encode("utf-8")) > 50_000:
        raise HTTPException(status_code=400, detail="Code exceeds maximum length (50000 bytes)")

    def _load_test_cases():
        db = SessionLocal()
        try:
            question = db.query(Question).filter(Question.id == body.question_id).first()
            if not question:
                raise HTTPException(status_code=404, detail="Question not found")
            if question.type != QuestionType.coding:
                raise HTTPException(status_code=400, detail="Not a coding question")

            # Candidate-facing execution is always restricted to public samples.
            query = db.query(TestCase).filter(
                TestCase.question_id == body.question_id,
                TestCase.is_sample == True,
            ).limit(2)
            test_cases = query.all()
            if not test_cases:
                raise HTTPException(status_code=400, detail="No test cases available for this question")
            return [
                {
                    "id": tc.id,
                    "input_data": tc.input_data or "",
                    "expected_output": tc.expected_output or "",
                    "is_sample": bool(tc.is_sample),
                }
                for tc in test_cases
            ]
        finally:
            db.close()

    test_cases = await run_db_sync(_load_test_cases)
    results_list = []
    for test_case in test_cases:
        runner = run_sql_test_case if language == "sql" else run_test_case
        result = await asyncio.to_thread(
            runner,
            code=body.code,
            input_data=test_case["input_data"],
            expected_output=test_case["expected_output"],
        )
        try:
            ensure_execution_available(result)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        results_list.append({
            "test_case_id": test_case["id"],
            "passed": bool(result.get("passed")),
            "input_data": test_case["input_data"],
            "expected_output": test_case["expected_output"],
            "actual_output": result.get("actual_output"),
            "error": result.get("error"),
            "is_sample": test_case["is_sample"],
        })

    passed_count = sum(1 for result in results_list if result["passed"])
    payload = {
        "results": results_list,
        "total": len(results_list),
        "passed": passed_count,
        "failed": len(results_list) - passed_count,
        "all_passed": passed_count == len(results_list),
    }
    return RunCodeResponse(**payload)
