"""景观照明接口：园区阈值、回路台账、判定口径、亮灯排程、下发控制与电流告警。

业务判断全部在 app/services/lighting.py，路由层只负责参数接收与结果包装。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload
from app.services.lighting import lighting_service
from app.services.lighting_calendar import SOLAR_TERMS_2026

router = APIRouter(prefix="/api/lighting", tags=["景观照明"])


# ---------------------------------------------------------------- 园区阈值
@router.get("/parks")
def list_parks() -> dict[str, Any]:
    """各园区及其电流上限（阈值按园区分别配置）。"""
    return {"items": lighting_service.list_parks(), "total": len(lighting_service.list_parks())}


@router.post("/parks/{park_id}/threshold", response_model=ActionResult)
def update_park_threshold(park_id: int, payload: EntryPayload) -> ActionResult:
    """调整园区电流上限；入参 values 形如 {"电流上限": 15.5}。"""
    park, message = lighting_service.update_park_threshold(park_id, payload.values.get("电流上限"))
    if park is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=park)


# ---------------------------------------------------------------- 回路台账
@router.get("/circuits")
def list_circuits() -> dict[str, Any]:
    """照明台账：每条回路附带统一口径的当前档位结论。"""
    items = lighting_service.list_circuits()
    return {"items": items, "total": len(items)}


@router.get("/circuits/{circuit_id}")
def get_circuit(circuit_id: int) -> dict[str, Any]:
    circuit = lighting_service.get_circuit(circuit_id)
    if circuit is None:
        raise HTTPException(status_code=404, detail=f"灯具回路 {circuit_id} 不存在")
    return circuit


@router.post("/circuits/{circuit_id}/status", response_model=ActionResult)
def set_circuit_status(circuit_id: int, payload: EntryPayload) -> ActionResult:
    """标记回路 正常/故障；故障回路不参与排程，状态变化触发排程重算。"""
    status = str(payload.values.get("回路状态") or "").strip()
    entry, message = lighting_service.set_circuit_status(circuit_id, status, payload.values.get("故障描述"))
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/circuits/{circuit_id}/current", response_model=ActionResult)
def report_current(circuit_id: int, payload: EntryPayload) -> ActionResult:
    """上报回路电流；超过园区阈值时单独告警，返回体里带 alarm。"""
    entry, message, alarm = lighting_service.report_current(circuit_id, payload.values.get("当前电流"))
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry={"回路": entry, "告警": alarm})


# ---------------------------------------------------------------- 判定试算
@router.post("/decide")
def decide_light(payload: EntryPayload) -> dict[str, Any]:
    """按亮灯时段与节气日历试算某天某时刻各回路该不该开灯、开几档。"""
    values = payload.values
    day_text = str(values.get("日期") or "").strip()
    clock = str(values.get("时刻") or "").strip()
    if not day_text or not clock:
        raise HTTPException(status_code=400, detail="试算需要提供 日期(YYYY-MM-DD) 与 时刻(HH:MM)")
    try:
        items = lighting_service.trial_decide(day_text, clock)
    except ValueError:
        raise HTTPException(status_code=400, detail="日期格式应为 YYYY-MM-DD，时刻格式应为 HH:MM")
    return {"日期": day_text, "时刻": clock, "items": items, "total": len(items)}


@router.get("/calendar")
def calendar_terms() -> dict[str, Any]:
    """节气日历：返回 2026 年二十四节气交节日期，供页面展示判定依据。"""
    return {"年度": 2026, "节气": SOLAR_TERMS_2026}


# ---------------------------------------------------------------- 规则维护
@router.get("/rules/windows")
def list_window_rules() -> dict[str, Any]:
    return {"items": lighting_service.list_window_rules()}


@router.post("/rules/windows/{rule_id}", response_model=ActionResult)
def update_window_rule(rule_id: int, payload: EntryPayload) -> ActionResult:
    """修改节气亮灯时段/档位；判定标准变更后自动重算已有亮灯排程。"""
    entry, message = lighting_service.update_window_rule(rule_id, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.get("/rules/festivals")
def list_festivals() -> dict[str, Any]:
    return {"items": lighting_service.list_festivals()}


@router.post("/rules/festivals", response_model=ActionResult)
def upsert_festival(payload: EntryPayload) -> ActionResult:
    """新增或修改节庆日历（values 带 id 即修改）；变更后重算已有排程。"""
    entry, message = lighting_service.upsert_festival(payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


# ---------------------------------------------------------------- 亮灯排程
@router.get("/schedules")
def list_schedules(day: str | None = Query(default=None, alias="date", description="按日期 YYYY-MM-DD 过滤")) -> dict[str, Any]:
    items = lighting_service.list_schedules(day)
    return {"items": items, "total": len(items)}


@router.post("/schedules/generate", response_model=ActionResult)
def generate_schedules(payload: EntryPayload) -> ActionResult:
    """按当前判定标准重算（重建）指定日期区间的亮灯排程。"""
    start = str(payload.values.get("开始日期") or "").strip()
    end = str(payload.values.get("结束日期") or "").strip()
    if not start or not end:
        return ActionResult(ok=False, message="需要提供 开始日期 与 结束日期")
    items, message = lighting_service.generate_schedules(start, end)
    return ActionResult(ok=True, message=message, entry={"items": items, "total": len(items)})


# ---------------------------------------------------------------- 下发控制
@router.post("/circuits/{circuit_id}/issue", response_model=ActionResult)
def issue_control(circuit_id: int, payload: EntryPayload) -> ActionResult:
    """下发开灯：超出允许亮灯时段或回路故障会被拒并说明缘由；同一回路同一时段重复提交只生效一次。"""
    day_text = str(payload.values.get("日期") or "").strip()
    clock = str(payload.values.get("时刻") or "").strip()
    operator = str(payload.values.get("操作人") or "值班员").strip()
    if not day_text or not clock:
        return ActionResult(ok=False, message="下发需要提供 日期(YYYY-MM-DD) 与 时刻(HH:MM)")
    entry, message, created = lighting_service.issue(circuit_id, day_text, clock, operator)
    if entry is None:
        return ActionResult(ok=False, message=message)
    # 被口径拒绝时 ok=False 以便页面显式提示；重复提交是幂等成功。
    ok = bool(entry.get("生效"))
    return ActionResult(ok=ok, message=message, entry=entry)


@router.get("/controls")
def list_controls(
    only_effective: bool = Query(default=False, alias="effective"),
    circuit: int | None = Query(default=None, alias="circuit"),
) -> dict[str, Any]:
    """控制记录：另一个页面（监控页）的档位就是从这份已生效记录取的。"""
    items = lighting_service.list_controls(only_effective=only_effective, circuit_id=circuit)
    return {"items": items, "total": len(items)}


# ---------------------------------------------------------------- 电流告警
@router.get("/alarms")
def list_alarms(all_rows: bool = Query(default=False, alias="all")) -> dict[str, Any]:
    """电流超上限的独立告警清单，默认只看未解除。"""
    items = lighting_service.list_alarms(only_open=not all_rows)
    return {"items": items, "total": len(items)}


@router.post("/alarms/{alarm_id}/resolve", response_model=ActionResult)
def resolve_alarm(alarm_id: int) -> ActionResult:
    entry, message = lighting_service.resolve_alarm(alarm_id)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


# ---------------------------------------------------------------- 监控与自检
@router.get("/monitor")
def monitor() -> dict[str, Any]:
    """亮灯监控页：档位与台账、控制记录同一份口径。"""
    return lighting_service.monitor()


@router.get("/consistency")
def consistency() -> dict[str, Any]:
    """口径一致性自检：台账结论 = 控制记录结论 = 监控页档位。"""
    return lighting_service.consistency_check()
