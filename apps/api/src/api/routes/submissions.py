"""提交路由：POST /api/v1/submissions（06/09，一次完成清洗+计费+受理）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from contracts.submission import (
    SubmissionAccepted, SubmissionCreate, SubmissionInvalidItem,
)
from pandatrack_common import codes
from worker.billing.submission import (
    IdempotencyConflict, InsufficientBalance, request_fingerprint, submit,
)
from worker.cleaner.cleaner import Cleaner

from api.data import BRepository
from api.deps import Subject, get_repo, require_customer
from api.errors import ApiProblem, map_billing_error

router = APIRouter(prefix="/api/v1", tags=["submissions"])


@router.post("/submissions", response_model=SubmissionAccepted, status_code=202)
def create_submission(payload: SubmissionCreate,
                      subject: Subject = Depends(require_customer),
                      repo: BRepository = Depends(get_repo)):
    # 粘贴与文件都归一为原始行数组（文件来源由导入任务在 04 侧拆解后复用此路径）。
    lines = payload.lines or []
    if not lines and not payload.import_file_ref:
        raise ApiProblem(codes.INVALID_INPUT, {"reason": "empty_submission"})

    # Cleaner.clean 接受整个原始文本（内部按 CRLF/LF/CR 切行并保留行号）。
    cleaned = Cleaner().clean("\n".join(lines))
    numbers = cleaned.billable_numbers
    fingerprint = request_fingerprint({
        "lines": lines, "import_file_ref": payload.import_file_ref,
        "target_group_name": payload.target_group_name,
    })

    with repo.connect() as conn:
        try:
            outcome = submit(
                conn, customer_id=subject.customer_id,
                client_request_id=payload.client_request_id,
                fingerprint=fingerprint, normalized_numbers=numbers,
            )
            conn.commit()
        except (IdempotencyConflict, InsufficientBalance) as exc:
            conn.rollback()
            raise map_billing_error(exc)
        except Exception:
            conn.rollback()
            raise ApiProblem(codes.INTERNAL_ERROR)

    invalid = [
        SubmissionInvalidItem(line_no=c.line_no, raw=c.raw_number[:100],
                              reason=c.result_code)
        for c in cleaned.candidates if not c.billable
    ]
    return SubmissionAccepted(
        operation_id=outcome.operation_public_id,
        total_count=outcome.total_count,
        valid_count=outcome.billable_count,
        invalid_count=outcome.total_count - outcome.billable_count,
        points_charged=outcome.billable_count - outcome.waived_count,
        free_count=outcome.waived_count,
        invalid_items=invalid[:100],   # 响应体上限，完整明细在 operation 快照
        batches=_batch_indices(outcome.billable_count),
    )


def _batch_indices(valid_count: int) -> list[int]:
    """35 切片后的批次序号（1-based）。"""
    if not valid_count:
        return []
    import math
    return list(range(1, math.ceil(valid_count / 35) + 1))
