"""账务路由：wallet/ledger/redemptions（09 §4/§5，06 套餐）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from contracts.billing import (
    BillingSummary, LedgerEntry, RedemptionRequest, RedemptionResponse,
)
from pandatrack_common import codes

from api.data import BRepository
from api.deps import Subject, get_repo, require_customer
from api.errors import ApiProblem

router = APIRouter(prefix="/api/v1/billing", tags=["billing"])


@router.get("/wallet", response_model=BillingSummary)
def wallet(subject: Subject = Depends(require_customer),
           repo: BRepository = Depends(get_repo)):
    row = repo.wallet_detail(subject.customer_id)
    if row is None:
        raise ApiProblem(codes.NOT_FOUND)
    return BillingSummary(balance=row["balance"], frozen=row["frozen"],
                          lifetime_consumed=row["lifetime_consumed"])


@router.get("/ledger", response_model=list[LedgerEntry])
def ledger(subject: Subject = Depends(require_customer),
           repo: BRepository = Depends(get_repo)):
    return [LedgerEntry(**r) for r in repo.ledger_entries(subject.customer_id)]


@router.post("/redemptions", response_model=RedemptionResponse)
def redeem(payload: RedemptionRequest,
           subject: Subject = Depends(require_customer),
           repo: BRepository = Depends(get_repo)):
    try:
        points, balance = repo.redeem(subject.customer_id, payload.code)
    except ValueError:
        raise ApiProblem(codes.REDEMPTION_CODE_INVALID)
    return RedemptionResponse(points_added=points, balance=balance)
