"""组与批次路由（04 §5.8）+ 导入任务列表（04 §5.9）。

删除/归档为危险操作语义：删除只清客户侧组织关系（成员/批次挂靠置空），
不删事实、批次历史、账务（服务端实现保证，前端二次确认）。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from contracts.groups_exports import (
    ArchiveGroupRequest, BatchDetail, BatchView, CreateGroupRequest,
    GroupView, ImportJobView, RenameGroupRequest,
)
from contracts.submission import ImportAccepted, ImportCreate
from pandatrack_common import codes

from api.data import BRepository
from api.deps import Subject, get_repo, require_customer
from api.errors import ApiProblem, map_billing_error
from worker.billing.submission import (
    IdempotencyConflict, InsufficientBalance, request_fingerprint, submit,
)
from worker.cleaner.cleaner import Cleaner

router = APIRouter(prefix="/api/v1", tags=["groups"])


@router.get("/groups", response_model=list[GroupView])
def list_groups(subject: Subject = Depends(require_customer),
                repo: BRepository = Depends(get_repo)):
    return [GroupView(**r) for r in repo.list_groups(subject.customer_id)]


@router.post("/groups", response_model=GroupView, status_code=201)
def create_group(payload: CreateGroupRequest,
                 subject: Subject = Depends(require_customer),
                 repo: BRepository = Depends(get_repo)):
    return GroupView(**repo.create_group(subject.customer_id, payload.name))


@router.patch("/groups/{group_id}", response_model=GroupView)
def rename_group(group_id: str, payload: RenameGroupRequest,
                 subject: Subject = Depends(require_customer),
                 repo: BRepository = Depends(get_repo)):
    if not repo.rename_group(subject.customer_id, group_id, payload.name):
        raise ApiProblem(codes.NOT_FOUND)
    groups = [g for g in repo.list_groups(subject.customer_id)
              if g["id"] == group_id]
    if not groups:
        raise ApiProblem(codes.NOT_FOUND)
    return GroupView(**groups[0])


@router.post("/groups/{group_id}/archive", response_model=GroupView)
def archive_group(group_id: str, payload: ArchiveGroupRequest,
                  subject: Subject = Depends(require_customer),
                  repo: BRepository = Depends(get_repo)):
    if not repo.archive_group(subject.customer_id, group_id, payload.archived):
        raise ApiProblem(codes.NOT_FOUND)
    groups = [g for g in repo.list_groups(subject.customer_id)
              if g["id"] == group_id]
    if not groups:
        raise ApiProblem(codes.NOT_FOUND)
    return GroupView(**groups[0])


@router.delete("/groups/{group_id}")
def delete_group(group_id: str,
                 subject: Subject = Depends(require_customer),
                 repo: BRepository = Depends(get_repo)):
    ok = repo.delete_group(subject.customer_id, group_id)
    if not ok:
        raise ApiProblem(codes.NOT_FOUND)
    return {"ok": True, "effect": "只清除组织关系，事实与账务记录保留"}


@router.get("/groups/{group_id}/batches", response_model=list[BatchView])
def group_batches(group_id: str,
                  subject: Subject = Depends(require_customer),
                  repo: BRepository = Depends(get_repo)):
    return [BatchView(**r)
            for r in repo.list_batches(subject.customer_id, group_id=group_id)]


@router.get("/batches", response_model=list[BatchView])
def list_batches(limit: int = Query(default=50, ge=1, le=200),
                 subject: Subject = Depends(require_customer),
                 repo: BRepository = Depends(get_repo)):
    return [BatchView(**r)
            for r in repo.list_batches(subject.customer_id, limit=limit)]


@router.get("/batches/{batch_id}", response_model=BatchDetail)
def batch_detail(batch_id: str,
                 subject: Subject = Depends(require_customer),
                 repo: BRepository = Depends(get_repo)):
    detail = repo.batch_detail(subject.customer_id, batch_id)
    if detail is None:
        raise ApiProblem(codes.NOT_FOUND)
    return BatchDetail(**detail)


@router.get("/imports", response_model=list[ImportJobView])
def list_imports(limit: int = Query(default=50, ge=1, le=200),
                 subject: Subject = Depends(require_customer),
                 repo: BRepository = Depends(get_repo)):
    return [ImportJobView(**r)
            for r in repo.list_imports(subject.customer_id, limit=limit)]


@router.post("/imports", response_model=ImportAccepted, status_code=202)
def create_import(payload: ImportCreate,
                  subject: Subject = Depends(require_customer),
                  repo: BRepository = Depends(get_repo)):
    """大批量导入创建（04 §5.4 文件路径 / §5.9）：一次完成清洗、计费、受理。

    复用 submit() 同一事务语义（幂等键、集合化免扣、余额锁定）；import_job
    记录受理计数（202 语义：已受理，结果后台逐步更新，不即时返回轨迹）。
    """
    lines = payload.lines or []
    if not lines:
        raise ApiProblem(codes.INVALID_INPUT, {"reason": "empty_import"})

    cleaned = Cleaner().clean("\n".join(lines))
    fingerprint = request_fingerprint({
        "lines": lines, "source": "import", "file_name": payload.file_name,
        "target_group_name": payload.target_group_name,
    })

    with repo.connect() as conn:
        try:
            outcome = submit(
                conn, customer_id=subject.customer_id,
                client_request_id=payload.client_request_id,
                fingerprint=fingerprint, normalized_numbers=cleaned.billable_numbers,
            )
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT operation_id FROM submission_operation WHERE public_id=%s",
                    (outcome.operation_public_id,),
                )
                op_row = cur.fetchone()
                if op_row is None:
                    raise ApiProblem(codes.INTERNAL_ERROR)
                operation_id = op_row[0]
                if outcome.replayed:
                    # 幂等重放：不重复建 import_job，复用既有记录
                    cur.execute(
                        "SELECT public_id FROM import_job "
                        "WHERE customer_id=%s AND operation_id=%s LIMIT 1",
                        (subject.customer_id, operation_id),
                    )
                    row = cur.fetchone()
                    if row is not None:
                        import_public_id = str(row[0])
                    else:  # 首次提交未落 import_job（理论不可达），补建
                        cur.execute(
                            "INSERT INTO import_job (customer_id, status, total, done, "
                            " file_name, operation_id) VALUES (%s,'accepted',%s,%s,%s,%s) "
                            "RETURNING public_id",
                            (subject.customer_id, len(cleaned.candidates),
                             outcome.billable_count, payload.file_name, operation_id),
                        )
                        import_public_id = str(cur.fetchone()[0])
                else:
                    cur.execute(
                        "INSERT INTO import_job (customer_id, status, total, done, "
                        " file_name, enqueued, success_count, failed_count, "
                        " duplicate_count, operation_id) "
                        "VALUES (%s,'accepted',%s,%s,%s,%s,%s,%s,%s,%s) "
                        "RETURNING public_id",
                        (subject.customer_id, len(cleaned.candidates),
                         outcome.billable_count, payload.file_name,
                         outcome.billable_count,          # enqueued
                         outcome.billable_count,          # success_count（受理口径）
                         len(cleaned.candidates) - outcome.billable_count,  # failed
                         outcome.waived_count,            # duplicate（30 天免扣）
                         operation_id),
                    )
                    import_public_id = str(cur.fetchone()[0])
            conn.commit()
        except (IdempotencyConflict, InsufficientBalance) as exc:
            conn.rollback()
            raise map_billing_error(exc)
        except Exception:
            conn.rollback()
            raise ApiProblem(codes.INTERNAL_ERROR)

    # 受理后自动挂默认组（后置事务，失败不回滚受理，04 §5.8）
    try:
        gid = repo.ensure_default_group(subject.customer_id)
        repo.assign_operation_group(subject.customer_id,
                                    outcome.operation_public_id, gid)
    except Exception:
        import logging
        logging.getLogger("pandatrack.api.imports").warning(
            "group assign failed for operation %s",
            outcome.operation_public_id, exc_info=True)

    return ImportAccepted(
        import_job_id=import_public_id,
        operation_id=outcome.operation_public_id,
        total_count=len(cleaned.candidates),
        valid_count=outcome.billable_count,
        invalid_count=len(cleaned.candidates) - outcome.billable_count,
        points_charged=outcome.billable_count - outcome.waived_count,
        free_count=outcome.waived_count,
    )
