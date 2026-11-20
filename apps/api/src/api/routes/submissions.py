"""提交路由：POST /api/v1/submissions（06/09，一次完成清洗+计费+受理）。

另含 POST /api/v1/submissions/estimate（04 §5.4 实时解析面板）：幂等只读、
不入账、不构成报价；分类与余额均来自服务端，前端不自算（09 §5.2.1）。
"""
from __future__ import annotations

import math

from fastapi import APIRouter, Depends

from contracts.submission import (
    SubmissionAccepted, SubmissionCreate, SubmissionEstimate,
    SubmissionEstimateRequest, SubmissionInvalidItem,
)
from pandatrack_common import codes
from worker.billing.submission import (
    BATCH_SIZE, IdempotencyConflict, InsufficientBalance, request_fingerprint, submit,
)
from worker.cleaner.cleaner import Cleaner

from api.data import BRepository
from api.deps import Subject, get_repo, require_customer
from api.errors import ApiProblem, map_billing_error

router = APIRouter(prefix="/api/v1", tags=["submissions"])


@router.post("/submissions/estimate", response_model=SubmissionEstimate)
def estimate_submission(payload: SubmissionEstimateRequest,
                        subject: Subject = Depends(require_customer),
                        repo: BRepository = Depends(get_repo)):
    """提交前预估（04 §5.4）：清洗分类 + 集合化免扣判定 + 余额快照。

    只读事务（显式 rollback），不写 operation/ledger/outbox；与正式提交
    使用同一 Cleaner 与同一免扣 SQL，保证口径一致（预估≠报价，以 202 为准）。
    """
    lines = payload.lines or []
    if not lines:
        raise ApiProblem(codes.INVALID_INPUT, {"reason": "empty_submission"})

    cleaned = Cleaner().clean("\n".join(lines))
    numbers = [c.normalized for c in cleaned.candidates
               if c.billable and c.normalized]

    billable = 0
    balance = 0
    with repo.connect() as conn:
        with conn.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS _estimate_candidates")
            cur.execute(
                "CREATE TEMP TABLE _estimate_candidates ("
                " seq INT PRIMARY KEY, normalized_number VARCHAR(50) NOT NULL) "
                "ON COMMIT DROP"
            )
            if numbers:
                with cur.copy(
                    "COPY _estimate_candidates (seq, normalized_number) FROM STDIN"
                ) as copy:
                    for i, num in enumerate(set(numbers)):
                        copy.write_row((i, num))
            # 与 submit() 第 3 步同一免扣口径（30×24h active 窗口）
            cur.execute(
                "SELECT COUNT(*) FROM _estimate_candidates c "
                "WHERE NOT EXISTS ("
                "  SELECT 1 FROM billing_charge_window w "
                "  WHERE w.customer_id=%s AND w.normalized_number=c.normalized_number "
                "    AND w.active=true AND w.expires_at>now())",
                (subject.customer_id,),
            )
            billable = cur.fetchone()[0]
            cur.execute(
                "SELECT balance FROM wallet WHERE customer_id=%s",
                (subject.customer_id,),
            )
            row = cur.fetchone()
            balance = row[0] if row else 0
        conn.rollback()  # 只读：临时表随事务结束清理，不产生任何写入

    total = len(cleaned.candidates)
    free = len(set(numbers)) - billable
    invalid = [
        SubmissionInvalidItem(line_no=c.line_no, raw=c.raw_number[:100],
                              reason=c.result_code)
        for c in cleaned.candidates if not c.billable
    ]
    return SubmissionEstimate(
        total_count=total,
        billable_count=billable,
        free_count=free,
        points_estimate=billable,
        balance=balance,
        insufficient=balance < billable,
        result_counts=cleaned.counts(),
        invalid_items=invalid[:100],
    )


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
    # 04 §5.8：受理后自动挂默认组（后置事务，崩溃最坏情况批次无组可补挂）。
    try:
        gid = repo.ensure_default_group(subject.customer_id)
        repo.assign_operation_group(subject.customer_id,
                                    outcome.operation_public_id, gid)
    except Exception:  # 挂组失败不回滚受理（受理已计费），记录后继续
        import logging
        logging.getLogger("pandatrack.api.submissions").warning(
            "group assign failed for operation %s",
            outcome.operation_public_id, exc_info=True)
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
    """切片后的批次序号（1-based；与 submit() 侧 BATCH_SIZE 同源）。"""
    if not valid_count:
        return []
    return list(range(1, math.ceil(valid_count / BATCH_SIZE) + 1))
