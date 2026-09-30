"""景观照明接口：园区阈值、灯具回路台账、判定口径、亮灯排程、控制下发与电流告警。

口径（开关灯的唯一入口）：
- GET  /api/lighting/snapshot       当下档位快照（台账页与监控页共用，保证读到同一份）
- GET  /api/lighting/ledger         照明台账：当前档位结论取自控制记录
- GET  /api/lighting/consistency    台账与控制记录口径核对
- GET  /api/lighting/parks          园区列表（含各自电流上限）
- POST /api/lighting/parks/{id}/threshold  调整园区电流阈值
- GET/POST /api/lighting/circuits   灯具回路台账 / 登记回路
- POST /api/lighting/circuits/{id}/current 上报回路电流
- POST /api/lighting/circuits/{id}/status   标记故障/修复
- GET/PUT /api/lighting/windows[/{id}]      按节气的常规亮灯窗口
- GET/POST/DELETE /api/lighting/festivals[/...]  节庆亮灯日历（节庆优先于常规）
- POST /api/lighting/criteria/rebuild      判定标准变更后手动重算排程（标准变更时也会自动重算）
- GET /api/lighting/schedules       亮灯排程
- GET /api/lighting/controls        控制记录（另一页面读档位也走这里的同源数据）
- POST /api/lighting/controls/dispatch     下发开灯指令（时段口径校验 + 幂等 + 超限告警）
- GET /api/lighting/alarms          电流告警
- POST /api/lighting/alarms/{id}/resolve   处理告警
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.schemas import ActionResult, EntryPayload
from app.services.lighting import GEAR_LABELS, lighting_service

router = APIRouter(prefix="/api/lighting", tags=["景观照明"])

service = lighting_service


class OptionalPayload(BaseModel):
    """允许空请求体的动作入参。"""

    values: dict[str, Any] = {}


def _payload_values(payload: EntryPayload) -> dict[str, Any]:
    return payload.values


# ----- 当下口径快照（两个页面共用） -----
@router.get("/snapshot")
def snapshot() -> dict[str, Any]:
    """当前时刻的开灯口径结论；监控页与台账页读的是同一份数据。"""
    return service.current_snapshot()


# ----- 园区与阈值 -----
@router.get("/parks")
def list_parks() -> dict[str, Any]:
    """园区列表：每个园区各自维护电流上限。"""
    return {"items": service.list_parks()}


@router.post("/parks/{park_id}/threshold", response_model=ActionResult)
def update_park_threshold(park_id: int, payload: EntryPayload) -> ActionResult:
    """调整某园区电流上限，调整后立即按新阈值重新巡检全部回路电流。"""
    park, message = service.update_park_threshold(park_id, payload.values.get("电流上限A"))
    if park is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=park)


# ----- 灯具回路台账 -----
@router.get("/circuits")
def list_circuits(
    park: str | None = Query(default=None, description="按园区名称过滤"),
    status: str | None = Query(default=None, description="正常 / 故障"),
) -> dict[str, Any]:
    """灯具回路台账；故障回路仍在台账中可见，但不进入亮灯排程。"""
    return {"items": service.list_circuits(park=park, status=status)}


@router.post("/circuits", response_model=ActionResult)
def create_circuit(payload: EntryPayload) -> ActionResult:
    """登记灯具回路，登记后自动纳入亮灯排程并巡检一次电流。"""
    entry, missing = service.create_circuit(_payload_values(payload))
    if missing:
        return ActionResult(ok=False, message=f"缺少或不合法字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="灯具回路已登记并纳入排程", entry=entry)


@router.post("/circuits/{circuit_id}/current", response_model=ActionResult)
def report_current(circuit_id: int, payload: EntryPayload) -> ActionResult:
    """上报回路实时电流，超过所属园区阈值的单独产生告警。"""
    circuit, message = service.report_current(circuit_id, payload.values.get("当前电流A"))
    if circuit is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=circuit)


@router.post("/circuits/{circuit_id}/status", response_model=ActionResult)
def mark_circuit_status(circuit_id: int, payload: EntryPayload) -> ActionResult:
    """标记回路故障/修复；故障回路立即退出亮灯排程，修复后重新纳入并重算。"""
    fault = str(payload.values.get("回路状态") or "").strip() == "故障"
    circuit, message = service.mark_status(circuit_id, fault)
    if circuit is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=circuit)


# ----- 判定标准：常规亮灯窗口 -----
@router.get("/windows")
def list_windows() -> dict[str, Any]:
    """按节气季节配置的常规亮灯窗口。"""
    items = [
        {**row, "档位名称": GEAR_LABELS.get(int(row["档位"]), str(row["档位"]))}
        for row in service.list_windows()
    ]
    return {"items": items}


@router.put("/windows/{window_id}", response_model=ActionResult)
def update_window(window_id: int, payload: EntryPayload) -> ActionResult:
    """变更常规亮灯窗口口径；变更后既有亮灯排程自动按新口径重算。"""
    window, message = service.update_window(window_id, _payload_values(payload))
    if window is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=window)


# ----- 判定标准：节庆亮灯日历 -----
@router.get("/festivals")
def list_festivals() -> dict[str, Any]:
    """节庆亮灯日历；节庆要求与常规时段冲突时以节庆为准。"""
    return {"items": service.list_festivals()}


@router.post("/festivals", response_model=ActionResult)
def create_festival(payload: EntryPayload) -> ActionResult:
    """新增节庆亮灯要求；保存后亮灯排程自动重算。"""
    entry, missing = service.create_festival(_payload_values(payload))
    if missing:
        return ActionResult(ok=False, message=f"缺少或不合法字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message=f"节庆「{entry['节庆名称']}」已加入日历，排程已重算", entry=entry)


@router.delete("/festivals/{festival_id}", response_model=ActionResult)
def delete_festival(festival_id: int) -> ActionResult:
    """删除节庆要求；删除后排程回到常规口径并重算。"""
    return ActionResult(ok=True, message=service.delete_festival(festival_id))


# ----- 排程重算 -----
@router.post("/criteria/rebuild", response_model=ActionResult)
def rebuild_criteria(payload: OptionalPayload = OptionalPayload()) -> ActionResult:
    """手动按现行判定标准重算未来 7 天亮灯排程（标准变更时系统也会自动重算）。"""
    reason = payload.values.get("原因") or "值班员手动重算"
    result = service.rebuild_schedules(reason=str(reason))
    return ActionResult(ok=True, message=f"亮灯排程已重算：未来 {result['天数']} 天共 {result['条数']} 条",
                        entry=result)


# ----- 亮灯排程 -----
@router.get("/schedules")
def list_schedules(
    date: str | None = Query(default=None, alias="date", description="按日期过滤 YYYY-MM-DD"),
    park: str | None = Query(default=None, description="按园区过滤"),
    circuit_no: str | None = Query(default=None, description="按回路编号过滤"),
) -> dict[str, Any]:
    """重算后的亮灯排程；故障回路不出现，已下发的保留下发标记。"""
    items = service.list_schedules(day=date, park=park, circuit_no=circuit_no)
    return {"items": items, "total": len(items)}


# ----- 控制记录与下发 -----
@router.get("/controls")
def list_controls(
    circuit_no: str | None = Query(default=None, description="按回路编号过滤"),
    date: str | None = Query(default=None, description="按下发日期过滤 YYYY-MM-DD"),
) -> dict[str, Any]:
    """控制记录：所有页面展示的当前档位都以此为单一数据源。"""
    items = service.list_controls(circuit_no=circuit_no, day=date)
    return {"items": items, "total": len(items)}


@router.post("/controls/dispatch", response_model=ActionResult)
def dispatch_control(payload: EntryPayload) -> ActionResult:
    """下发开灯指令。

    - 超出允许亮灯时段（含回路故障）直接拦截并说明缘由，不产生记录；
    - 同一回路同一时段日期重复提交只生效一次，返回首次记录；
    - 回路电流超园区上限时，指令生效同时单独写入一条电流告警。
    """
    record, message, duplicated = service.dispatch(_payload_values(payload))
    if record is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=record)


# ----- 电流告警 -----
@router.get("/alarms")
def list_alarms(active_only: bool = Query(default=False, description="只看未处理")) -> dict[str, Any]:
    """电流超上限的单独告警列表。"""
    items = service.list_alarms(active_only=active_only)
    return {"items": items, "total": len(items)}


@router.post("/alarms/{alarm_id}/resolve", response_model=ActionResult)
def resolve_alarm(alarm_id: int) -> ActionResult:
    """将一条电流告警标记为已处理。"""
    alarm, message = service.resolve_alarm(alarm_id)
    if alarm is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=alarm)


# ----- 照明台账与口径核对 -----
@router.get("/ledger")
def lighting_ledger() -> dict[str, Any]:
    """照明台账视图：当前档位结论与控制记录同源，保证两个页面结论一致。"""
    return {"items": service.ledger()}


@router.get("/consistency")
def consistency() -> dict[str, Any]:
    """核对照明台账与控制记录的档位结论是否一致。"""
    return service.consistency_check()
