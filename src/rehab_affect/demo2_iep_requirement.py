"""Mandatory IEP check for reports and long-term observation.

The platform may still save draft measurements without an IEP, but a formal
report/long-term conclusion must be anchored to one current, authorized IEP.
This module deliberately only reads the existing dossier gate; it never copies
IEP text into a measurement or a report.
"""
from __future__ import annotations

from .demo2_dossier_store import Demo2DossierStore, DossierError


class IepRequirementError(ValueError):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def current_iep(records, token: str, student_id: str) -> dict:
    """Return the unique current IEP, or raise a user-facing requirement error."""
    try:
        state = Demo2DossierStore(records).iep_context(token, student_id)
    except DossierError as exc:
        raise IepRequirementError(exc.status, exc.code, exc.message) from None
    except Exception:
        raise IepRequirementError(503, "iep_check_unavailable", "IEP 状态暂时无法读取，请稍后重试") from None
    status = str(state.get("status") or "")
    if status == "available":
        return state
    reason = str(state.get("reason") or "")
    if status == "not_found" or reason == "iep_not_found":
        raise IepRequirementError(409, "iep_required", "该学生尚未上传当前有效的 IEP 摘要；请先在学生资料中完成授权和 IEP 上传")
    if status == "ambiguous":
        raise IepRequirementError(409, "iep_ambiguous", "该学生存在多份当前有效的 IEP，请先核实并只保留一份")
    if status == "unavailable":
        raise IepRequirementError(409, "iep_unavailable", str(state.get("message") or "IEP 授权已到期或撤回，请重新登记授权"))
    raise IepRequirementError(409, "iep_required", "该学生当前没有可用于报告的 IEP 摘要")


def require_current_iep(records, token: str, student_id: str) -> dict:
    return current_iep(records, token, student_id)
