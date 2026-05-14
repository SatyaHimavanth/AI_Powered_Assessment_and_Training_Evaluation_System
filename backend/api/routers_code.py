"""
Code Execution API Router

Provides endpoints for:
- Running code against test cases (sample or all)
- Getting test cases for a coding question
"""

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from core.auth import get_current_user
from core.code_runner import run_test_case
from core.sql_runner import run_sql_test_case
from db.models import Question, QuestionType, TestCase, User
from db.async_helpers import run_db_sync
from db.database import SessionLocal
from pydantic import BaseModel
import re

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

    - run_sample_only=True: run only sample (visible) test cases (for "Run" button)
    - run_sample_only=False: run all test cases including hidden (for final submission scoring)
    """

    def _sync_work():
        db = SessionLocal()
        try:
            question = db.query(Question).filter(Question.id == body.question_id).first()
            if not question:
                raise HTTPException(status_code=404, detail="Question not found")
            if question.type != QuestionType.coding:
                raise HTTPException(status_code=400, detail="Not a coding question")

            if not body.code.strip():
                raise HTTPException(status_code=400, detail="No code provided")

            # Security: basic code length check
            if len(body.code) > 50_000:
                raise HTTPException(status_code=400, detail="Code exceeds maximum length (50000 chars)")

            # Get appropriate test cases
            query = db.query(TestCase).filter(TestCase.question_id == body.question_id)
            if body.run_sample_only:
                query = query.filter(TestCase.is_sample == True).limit(2)
            test_cases = query.all()

            if not test_cases:
                raise HTTPException(status_code=400, detail="No test cases available for this question")

            results_list = []

            language = (body.language or "python").strip().lower()
            if language not in ("python", "sql"):
                raise HTTPException(status_code=400, detail="Invalid language. Supported: 'python', 'sql'")

            for tc in test_cases:
                if language == "sql":
                    result = run_sql_test_case(
                        code=body.code,
                        input_data=tc.input_data,
                        expected_output=tc.expected_output,
                    )
                else:
                    result = run_test_case(
                        code=body.code,
                        input_data=tc.input_data,
                        expected_output=tc.expected_output,
                    )

                results_list.append({
                    "test_case_id": tc.id,
                    "passed": bool(result.get("passed")),
                    "input_data": tc.input_data if tc.is_sample else "(hidden)",
                    "expected_output": tc.expected_output if tc.is_sample else "(hidden)",
                    "actual_output": result.get("actual_output") if tc.is_sample else ("correct" if result.get("passed") else "wrong answer"),
                    "error": result.get("error"),
                    "is_sample": bool(tc.is_sample),
                })

            passed_count = sum(1 for r in results_list if r["passed"])
            return {
                "results": results_list,
                "total": len(results_list),
                "passed": passed_count,
                "failed": len(results_list) - passed_count,
                "all_passed": passed_count == len(results_list),
            }
        finally:
            db.close()

    payload = await run_db_sync(_sync_work)
    return RunCodeResponse(**payload)
