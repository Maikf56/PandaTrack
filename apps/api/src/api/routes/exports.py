"""导出任务路由（04 §5.9：短期有效下载链接，过期显示重新导出）。"""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse

from contracts.groups_exports import CreateExportRequest, ExportJobView
from pandatrack_common import codes

from api.data import BRepository
from api.deps import Subject, get_repo, require_customer
from api.errors import ApiProblem

router = APIRouter(prefix="/api/v1/exports", tags=["exports"])

DEFAULT_EXPORT_DIR = "~/.pandatrack-exports"


def _export_dir() -> str:
    return os.environ.get("PT_EXPORT_DIR", DEFAULT_EXPORT_DIR)


@router.post("", response_model=ExportJobView, status_code=201)
def create_export(payload: CreateExportRequest,
                  subject: Subject = Depends(require_customer),
                  repo: BRepository = Depends(get_repo)):
    if payload.scope in ("group", "batch") and not payload.scope_ref:
        raise ApiProblem(codes.INVALID_INPUT)
    try:
        out = repo.create_export(
            subject.customer_id, scope=payload.scope,
            scope_ref=payload.scope_ref, export_dir=_export_dir())
    except ValueError:
        raise ApiProblem(codes.INVALID_INPUT)
    token = out.pop("token")
    view = ExportJobView(**out)
    view.download_url = f"/api/v1/exports/{out['id']}/download?token={token}"
    return view


@router.get("", response_model=list[ExportJobView])
def list_exports(subject: Subject = Depends(require_customer),
                 repo: BRepository = Depends(get_repo)):
    return [ExportJobView(**r)
            for r in repo.list_exports(subject.customer_id)]


@router.get("/{export_id}/download")
def download(export_id: str,
             token: str = Query(min_length=1),
             subject: Subject = Depends(require_customer),
             repo: BRepository = Depends(get_repo)):
    resolved = repo.resolve_download(subject.customer_id, export_id, token)
    if resolved is None:
        # 统一 410：过期/无效 token 不区分（不泄露存在性，04 §5.9 不显路径）。
        raise ApiProblem(codes.NOT_FOUND,
                         {"reason": "export_expired",
                          "message": "文件已过期，请重新导出"})
    path, filename = resolved
    return FileResponse(path, media_type="text/csv", filename=filename)
