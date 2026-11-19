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
from pandatrack_common import codes

from api.data import BRepository
from api.deps import Subject, get_repo, require_customer
from api.errors import ApiProblem

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
