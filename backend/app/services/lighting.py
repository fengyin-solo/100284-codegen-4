"""景观照明业务规则：开关口径判定、亮灯排程重算、下发幂等与电流告警。

所有页面共用这一份服务：照明台账、控制记录、监控页看到的档位结论都从
``current_gear`` 一个口径取数，避免各说各话。
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from app.services.lighting_calendar import GEAR_LABELS, decide
from app.services.lighting_store import lighting_store

GEAR_TEXT = {0: "关灯", **GEAR_LABELS}
SCHEDULE_PENDING = "待下发"
SCHEDULE_ISSUED = "已下发"
SCHEDULE_EXCLUDED = "不参与排程"
CONTROL_EFFECTIVE = "生效"
CONTROL_REJECTED = "拒绝"


def _parse_day(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _today() -> date:
    return date.today()


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class LightingService:
    # ---------------------------------------------------------------- 园区阈值
    def list_parks(self) -> list[dict[str, Any]]:
        return lighting_store.rows("lighting_park")

    def update_park_threshold(self, park_id: int, current_limit: Any) -> tuple[dict[str, Any] | None, str]:
        """阈值按园区单独设置；改完同步该园区全部回路并按新阈值重新评估告警。"""
        park = lighting_store.find("lighting_park", park_id)
        if park is None:
            return None, f"园区 {park_id} 不存在"
        try:
            limit = round(float(current_limit), 2)
        except (TypeError, ValueError):
            return None, "电流上限必须是数字"
        if limit <= 0:
            return None, "电流上限必须大于 0"
        park["电流上限"] = limit
        for circuit in lighting_store.rows("lighting_circuit"):
            if circuit["园区"] == park["园区名称"]:
                circuit["电流上限"] = limit
                self._evaluate_alarm(circuit)
        return park, f"{park['园区名称']}电流上限已调整为 {limit} A，回路阈值与告警已同步"

    # ---------------------------------------------------------------- 回路台账
    def list_circuits(self) -> list[dict[str, Any]]:
        """照明台账：档位结论直接取控制记录（current_gear），台账与控制记录结论一致。"""
        result = []
        for circuit in lighting_store.rows("lighting_circuit"):
            item = dict(circuit)
            item.update(self.current_gear(circuit["id"]))
            result.append(item)
        return result

    def get_circuit(self, circuit_id: int) -> dict[str, Any] | None:
        circuit = lighting_store.find("lighting_circuit", circuit_id)
        if circuit is None:
            return None
        item = dict(circuit)
        item.update(self.current_gear(circuit_id))
        return item

    def set_circuit_status(
        self, circuit_id: int, status: str, fault_desc: str | None = None
    ) -> tuple[dict[str, Any] | None, str]:
        """回路置故障/修复：故障回路不参与排程，状态变更后重算已有亮灯排程。"""
        circuit = lighting_store.find("lighting_circuit", circuit_id)
        if circuit is None:
            return None, f"灯具回路 {circuit_id} 不存在"
        if status not in ("正常", "故障"):
            return None, "回路状态只支持 正常 / 故障"
        circuit["回路状态"] = status
        if status == "故障":
            circuit["故障描述"] = (fault_desc or "").strip() or "回路故障，待检修"
            circuit["当前电流"] = None
        else:
            circuit.pop("故障描述", None)
            circuit["当前电流"] = 0.0
        changed = self.recalc_schedules()
        return self.get_circuit(circuit_id), f"回路已标记为{status}，已重算 {changed} 条已有亮灯排程"

    def report_current(self, circuit_id: int, current_value: Any) -> tuple[dict[str, Any] | None, str, dict[str, Any] | None]:
        """上报回路电流：超过该回路（园区）上限时单独产生一条电流告警。"""
        circuit = lighting_store.find("lighting_circuit", circuit_id)
        if circuit is None:
            return None, f"灯具回路 {circuit_id} 不存在", None
        try:
            ampere = round(float(current_value), 2)
        except (TypeError, ValueError):
            return None, "电流值必须是数字", None
        if ampere < 0:
            return None, "电流值不能为负", None
        if circuit["回路状态"] == "故障":
            return None, "回路故障中，电流数据不采信，请先修复回路", None
        circuit["当前电流"] = ampere
        alarm = self._evaluate_alarm(circuit)
        if alarm is not None:
            message = (
                f"电流 {ampere} A 超过 {circuit['园区']}允许上限 {circuit['电流上限']} A，已单独告警"
            )
        else:
            message = f"电流 {ampere} A 上报正常，未超过上限 {circuit['电流上限']} A"
        return dict(circuit), message, alarm

    def _evaluate_alarm(self, circuit: dict[str, Any]) -> dict[str, Any] | None:
        """按当前电流与上限评估告警：超限则开出/更新未解除告警，回到限值内则自动解除。"""
        ampere = circuit.get("当前电流")
        limit = circuit.get("电流上限")
        open_alarm = lighting_store.find_by(
            "lighting_alarm", 回路编号=circuit["回路编号"], 状态="未解除"
        )
        if ampere is None or limit is None or ampere <= limit:
            if open_alarm is not None:
                open_alarm["状态"] = "已解除"
                open_alarm["解除时间"] = _now_text()
            return None
        if open_alarm is not None:
            open_alarm["最新电流"] = ampere
            open_alarm["上报次数"] = int(open_alarm.get("上报次数", 1)) + 1
            open_alarm["最近上报"] = _now_text()
            return open_alarm
        alarm = {
            "回路编号": circuit["回路编号"],
            "回路名称": circuit["回路名称"],
            "园区": circuit["园区"],
            "电流上限": limit,
            "最新电流": ampere,
            "上报次数": 1,
            "首次上报": _now_text(),
            "最近上报": _now_text(),
            "状态": "未解除",
        }
        return lighting_store.insert("lighting_alarm", alarm)

    def list_alarms(self, only_open: bool = True) -> list[dict[str, Any]]:
        rows = lighting_store.rows("lighting_alarm")
        if only_open:
            rows = [row for row in rows if row["状态"] == "未解除"]
        return rows

    def resolve_alarm(self, alarm_id: int) -> tuple[dict[str, Any] | None, str]:
        alarm = lighting_store.find("lighting_alarm", alarm_id)
        if alarm is None:
            return None, f"告警 {alarm_id} 不存在"
        alarm["状态"] = "已解除"
        alarm["解除时间"] = _now_text()
        return alarm, "电流告警已人工解除"

    # ---------------------------------------------------------------- 判定口径
    def trial_decide(self, day_text: str, clock: str) -> list[dict[str, Any]]:
        """试算：不落数据，按亮灯时段与节气日历给出每条正常回路的档位结论。"""
        day = _parse_day(day_text)
        verdict = decide(
            day,
            clock,
            lighting_store.rows("lighting_window_rule"),
            lighting_store.rows("lighting_festival"),
        )
        items = []
        for circuit in lighting_store.rows("lighting_circuit"):
            if circuit["回路状态"] == "故障":
                items.append({
                    "回路编号": circuit["回路编号"],
                    "园区": circuit["园区"],
                    "允许开灯": False,
                    "档位": 0,
                    "档位文本": GEAR_TEXT[0],
                    "依据类型": "—",
                    "依据": "—",
                    "亮灯时段": "—",
                    "缘由": "回路故障，不参与排程与开灯",
                })
                continue
            items.append({
                "回路编号": circuit["回路编号"],
                "园区": circuit["园区"],
                "允许开灯": verdict["allowed"],
                "档位": verdict["gear"],
                "档位文本": GEAR_TEXT[verdict["gear"]],
                "依据类型": verdict["rule_type"],
                "依据": verdict["rule_name"],
                "亮灯时段": f'{verdict["window_start"]}-{verdict["window_end"]}' if verdict["window_start"] else "—",
                "缘由": verdict["reason"],
            })
        return items

    # ---------------------------------------------------------------- 排程
    def list_schedules(self, day_text: str | None = None) -> list[dict[str, Any]]:
        rows = lighting_store.rows("lighting_schedule")
        if day_text:
            rows = [row for row in rows if row["日期"] == day_text]
        return rows

    def generate_schedules(self, start_text: str, end_text: str) -> tuple[list[dict[str, Any]], str]:
        """按当前判定标准生成指定日期区间的亮灯排程；区间内旧排程作废重建。"""
        start, end = _parse_day(start_text), _parse_day(end_text)
        if start > end:
            return [], "开始日期不能晚于结束日期"
        schedules = lighting_store.rows("lighting_schedule")
        schedules[:] = [row for row in schedules if not (start <= _parse_day(row["日期"]) <= end)]
        days: list[str] = []
        cursor = start
        from datetime import timedelta
        while cursor <= end:
            days.append(cursor.isoformat())
            cursor += timedelta(days=1)
        for day_text in days:
            self._build_day_schedule(_parse_day(day_text))
        return self.list_schedules(), f"已按当前口径生成 {len(days)} 天的亮灯排程"

    def _build_day_schedule(self, day: date) -> None:
        """为某一天给所有回路铺排程行：正常回路按时段档位，故障回路直接排除。"""
        # 取当天适用的时段口径（节庆优先，否则按节气季节）。
        rule = self._day_window(day)
        for circuit in lighting_store.rows("lighting_circuit"):
            if circuit["回路状态"] == "故障":
                row = {
                    "日期": day.isoformat(),
                    "回路id": circuit["id"],
                    "回路编号": circuit["回路编号"],
                    "回路名称": circuit["回路名称"],
                    "园区": circuit["园区"],
                    "依据类型": rule["rule_type"],
                    "依据": rule["rule_name"],
                    "开灯时间": rule["window_start"] or "—",
                    "关灯时间": rule["window_end"] or "—",
                    "应开档位": 0,
                    "档位文本": GEAR_TEXT[0],
                    "状态": SCHEDULE_EXCLUDED,
                    "判定说明": f"回路故障（{circuit.get('故障描述', '原因未填')}），不参与排程",
                    "控制记录id": None,
                }
                lighting_store.insert("lighting_schedule", row)
                continue
            gear = rule["gear"]
            row = {
                "日期": day.isoformat(),
                "回路id": circuit["id"],
                "回路编号": circuit["回路编号"],
                "回路名称": circuit["回路名称"],
                "园区": circuit["园区"],
                "依据类型": rule["rule_type"],
                "依据": rule["rule_name"],
                "开灯时间": rule["window_start"],
                "关灯时间": rule["window_end"],
                "应开档位": gear,
                "档位文本": GEAR_TEXT[gear],
                "状态": SCHEDULE_PENDING,
                "判定说明": rule["reason"],
                "控制记录id": None,
            }
            lighting_store.insert("lighting_schedule", row)
        self._sync_schedule_status(day)

    def _day_window(self, day: date) -> dict[str, Any]:
        """取某一天适用的时段口径（在当天开灯时刻试算，必然落在自己的时段内）。"""
        from app.services.lighting_calendar import pick_festival, season_of

        festivals = lighting_store.rows("lighting_festival")
        festival = pick_festival(festivals, day)
        if festival is not None:
            gear = int(festival["开灯档位"])
            return {
                "rule_type": "节庆",
                "rule_name": festival["节庆名称"],
                "window_start": festival["开灯时间"],
                "window_end": festival["关灯时间"],
                "gear": gear,
                "reason": f"{festival['节庆名称']}口径优先，亮灯 {festival['开灯时间']}-{festival['关灯时间']}，应开{GEAR_LABELS[gear]}",
            }
        rules = lighting_store.rows("lighting_window_rule")
        season = season_of(day)
        rule = next((item for item in rules if item["季节"] == season), None)
        if rule is None:
            return {
                "rule_type": "常规",
                "rule_name": f"{season}季",
                "window_start": None,
                "window_end": None,
                "gear": 0,
                "reason": f"{season}季常规亮灯时段未配置，不排开灯",
            }
        gear = int(rule["开灯档位"])
        return {
            "rule_type": "常规",
            "rule_name": f"{season}季（{rule['起始节气']}起）",
            "window_start": rule["开灯时间"],
            "window_end": rule["关灯时间"],
            "gear": gear,
            "reason": f"{season}季常规亮灯 {rule['开灯时间']}-{rule['关灯时间']}，应开{GEAR_LABELS[gear]}",
        }

    def recalc_schedules(self) -> int:
        """判定标准（节气时段/节庆日历/回路状态）变更后，重算已有的亮灯排程。"""
        existing = lighting_store.rows("lighting_schedule")
        if not existing:
            return 0
        days = sorted({row["日期"] for row in existing})
        start_text, end_text = days[0], days[-1]
        self.generate_schedules(start_text, end_text)
        return len(days)

    def _sync_schedule_status(self, day: date) -> None:
        """把当天排程行与已生效控制记录对齐：同一回路同一时段已下发过的标记为已下发。"""
        controls = [
            row
            for row in lighting_store.rows("lighting_control")
            if row["日期"] == day.isoformat() and row["生效"]
        ]
        for row in lighting_store.rows("lighting_schedule"):
            if row["日期"] != day.isoformat() or row["状态"] == SCHEDULE_EXCLUDED:
                continue
            hit = next(
                (
                    control
                    for control in controls
                    if control["回路id"] == row["回路id"]
                    and control["开灯时间"] == row["开灯时间"]
                    and control["关灯时间"] == row["关灯时间"]
                ),
                None,
            )
            if hit is not None:
                row["状态"] = SCHEDULE_ISSUED
                row["应开档位"] = hit["档位"]
                row["档位文本"] = GEAR_TEXT[hit["档位"]]
                row["控制记录id"] = hit["id"]
            else:
                row["状态"] = SCHEDULE_PENDING
                row["控制记录id"] = None

    # ---------------------------------------------------------------- 下发控制
    def issue(
        self, circuit_id: int, day_text: str, clock: str, operator: str
    ) -> tuple[dict[str, Any] | None, str, bool]:
        """下发开灯：按统一口径判定；同一回路同一时段重复提交只生效一次。

        返回 (控制记录, 说明, 是否新生效)；不允许开灯时控制记录也留痕（状态=拒绝）。
        """
        circuit = lighting_store.find("lighting_circuit", circuit_id)
        if circuit is None:
            return None, f"灯具回路 {circuit_id} 不存在", False
        day = _parse_day(day_text)
        if circuit["回路状态"] == "故障":
            record = self._save_control(circuit, day, "—", "—", 0, "拒绝", False,
                                        "回路故障，不参与排程，禁止下发", operator)
            return record, f"回路 {circuit['回路编号']} 故障未修复，不参与排程，禁止开灯", False
        verdict = decide(
            day,
            clock,
            lighting_store.rows("lighting_window_rule"),
            lighting_store.rows("lighting_festival"),
        )
        if not verdict["allowed"]:
            record = self._save_control(
                circuit, day, verdict["window_start"] or "—", verdict["window_end"] or "—", 0,
                CONTROL_REJECTED, False, verdict["reason"], operator,
                rule_type=verdict["rule_type"], rule_name=verdict["rule_name"],
            )
            return record, f"不许开灯：{verdict['reason']}", False
        start, end, gear = verdict["window_start"], verdict["window_end"], verdict["gear"]
        duplicate = lighting_store.find_by(
            "lighting_control",
            回路id=circuit_id, 日期=day_text, 开灯时间=start, 关灯时间=end, 生效=True,
        )
        if duplicate is not None:
            return duplicate, (
                f"回路 {circuit['回路编号']} 在 {day_text} {start}-{end} 时段已下发过"
                f"（控制记录 #{duplicate['id']}，{GEAR_LABELS[gear]}），本次提交不重复生效"
            ), False
        record = self._save_control(
            circuit, day, start, end, gear, CONTROL_EFFECTIVE, True, verdict["reason"],
            operator, rule_type=verdict["rule_type"], rule_name=verdict["rule_name"],
        )
        self._sync_schedule_status(day)
        return record, (
            f"下发成功：{circuit['回路编号']} {day_text} {start}-{end} 开{GEAR_LABELS[gear]}"
            f"（依据：{verdict['rule_type']}·{verdict['rule_name']}）"
        ), True

    def _save_control(
        self,
        circuit: dict[str, Any],
        day: date,
        start: str,
        end: str,
        gear: int,
        status: str,
        effective: bool,
        reason: str,
        operator: str,
        *,
        rule_type: str = "—",
        rule_name: str = "—",
    ) -> dict[str, Any]:
        record = {
            "回路id": circuit["id"],
            "回路编号": circuit["回路编号"],
            "回路名称": circuit["回路名称"],
            "园区": circuit["园区"],
            "日期": day.isoformat(),
            "开灯时间": start,
            "关灯时间": end,
            "档位": gear,
            "档位文本": GEAR_TEXT[gear],
            "依据类型": rule_type,
            "依据": rule_name,
            "判定说明": reason,
            "操作人": operator or "值班员",
            "下发时间": _now_text(),
            "状态": status,
            "生效": effective,
        }
        return lighting_store.insert("lighting_control", record)

    def list_controls(self, only_effective: bool = False, circuit_id: int | None = None) -> list[dict[str, Any]]:
        rows = lighting_store.rows("lighting_control")
        if only_effective:
            rows = [row for row in rows if row["生效"]]
        if circuit_id is not None:
            rows = [row for row in rows if row["回路id"] == circuit_id]
        return rows

    def current_gear(self, circuit_id: int) -> dict[str, Any]:
        """唯一档位口径：取该回路最近一条已生效控制记录。台账与监控页都调这里。"""
        effective = [
            row for row in lighting_store.rows("lighting_control")
            if row["回路id"] == circuit_id and row["生效"]
        ]
        if not effective:
            return {"当前档位": 0, "档位结论": GEAR_TEXT[0], "档位依据": "尚无生效控制记录", "控制记录id": None}
        latest = max(effective, key=lambda row: row["id"])
        return {
            "当前档位": latest["档位"],
            "档位结论": latest["档位文本"],
            "档位依据": f"控制记录 #{latest['id']}（{latest['日期']} {latest['开灯时间']}-{latest['关灯时间']}，{latest['依据类型']}·{latest['依据']}）",
            "控制记录id": latest["id"],
        }

    # ---------------------------------------------------------------- 规则维护
    def list_window_rules(self) -> list[dict[str, Any]]:
        return lighting_store.rows("lighting_window_rule")

    def update_window_rule(self, rule_id: int, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        """修改节气亮灯时段/档位；改完重算已有排程。"""
        rule = lighting_store.find("lighting_window_rule", rule_id)
        if rule is None:
            return None, f"节气时段规则 {rule_id} 不存在"
        start, end = values.get("开灯时间"), values.get("关灯时间")
        if start is not None and not self._valid_clock(str(start)):
            return None, "开灯时间格式应为 HH:MM"
        if end is not None and not self._valid_clock(str(end)):
            return None, "关灯时间格式应为 HH:MM"
        if start and end and str(start) >= str(end):
            return None, "开灯时间必须早于关灯时间"
        gear = values.get("开灯档位")
        if gear is not None and int(gear) not in GEAR_LABELS:
            return None, "开灯档位只支持 1 节能 / 2 常规 / 3 全开"
        if start:
            rule["开灯时间"] = str(start)
        if end:
            rule["关灯时间"] = str(end)
        if gear is not None:
            rule["开灯档位"] = int(gear)
        changed_days = self.recalc_schedules()
        return rule, f"{rule['季节']}季亮灯口径已更新，已重算 {changed_days} 天的已有亮灯排程"

    def list_festivals(self) -> list[dict[str, Any]]:
        return lighting_store.rows("lighting_festival")

    def upsert_festival(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        """新增/修改节庆日历（带 id 即修改）；节庆口径变化后重算已有排程。"""
        required = ["节庆名称", "开始日期", "结束日期", "开灯时间", "关灯时间", "开灯档位"]
        missing = [name for name in required if values.get(name) in (None, "")]
        if missing:
            return None, f"缺少必填字段：{'、'.join(missing)}"
        try:
            start_day, end_day = _parse_day(str(values["开始日期"])), _parse_day(str(values["结束日期"]))
        except ValueError:
            return None, "节庆日期格式应为 YYYY-MM-DD"
        if start_day > end_day:
            return None, "节庆开始日期不能晚于结束日期"
        if not self._valid_clock(str(values["开灯时间"])) or not self._valid_clock(str(values["关灯时间"])):
            return None, "亮灯时间格式应为 HH:MM"
        if str(values["开灯时间"]) >= str(values["关灯时间"]):
            return None, "开灯时间必须早于关灯时间"
        if int(values["开灯档位"]) not in GEAR_LABELS:
            return None, "开灯档位只支持 1 节能 / 2 常规 / 3 全开"
        festival_id = values.get("id")
        if festival_id:
            festival = lighting_store.find("lighting_festival", int(festival_id))
            if festival is None:
                return None, f"节庆 {festival_id} 不存在"
        payload = {name: values[name] for name in required}
        payload["开灯档位"] = int(payload["开灯档位"])
        if festival_id:
            festival.update(payload)
            target = festival
            action = "更新"
        else:
            target = lighting_store.insert("lighting_festival", payload)
            action = "新增"
        changed_days = self.recalc_schedules()
        return target, f"已{action}节庆「{target['节庆名称']}」，已重算 {changed_days} 天的已有亮灯排程"

    @staticmethod
    def _valid_clock(value: str) -> bool:
        try:
            datetime.strptime(value, "%H:%M")
            return True
        except ValueError:
            return False

    # ---------------------------------------------------------------- 监控与自检
    def monitor(self) -> dict[str, Any]:
        """监控页数据：档位结论与台账、控制记录同源（current_gear）。"""
        circuits = []
        for circuit in lighting_store.rows("lighting_circuit"):
            item = dict(circuit)
            item.update(self.current_gear(circuit["id"]))
            item["电流告警"] = lighting_store.find_by(
                "lighting_alarm", 回路编号=circuit["回路编号"], 状态="未解除"
            ) is not None
            circuits.append(item)
        return {
            "采集时间": _now_text(),
            "回路总数": len(circuits),
            "故障回路": sum(1 for item in circuits if item["回路状态"] == "故障"),
            "电流告警中": sum(1 for item in circuits if item["电流告警"]),
            "生效中档位": [
                {"回路编号": item["回路编号"], "园区": item["园区"], "档位": item["当前档位"], "档位文本": item["档位结论"], "依据": item["档位依据"]}
                for item in circuits
                if item["当前档位"]
            ],
            "items": circuits,
        }

    def consistency_check(self) -> dict[str, Any]:
        """自检：台账结论 == 控制记录结论 == 监控页结论；排程档位与控制记录对齐。"""
        monitor_items = {item["回路编号"]: item for item in self.monitor()["items"]}
        mismatches: list[str] = []
        for circuit in self.list_circuits():
            monitored = monitor_items.get(circuit["回路编号"])
            if monitored is None:
                mismatches.append(f"{circuit['回路编号']} 不在监控数据中")
                continue
            if monitored["当前档位"] != circuit["当前档位"] or monitored["档位依据"] != circuit["档位依据"]:
                mismatches.append(f"{circuit['回路编号']} 监控页档位与台账结论不一致")
        for row in lighting_store.rows("lighting_schedule"):
            if row["状态"] != SCHEDULE_ISSUED:
                continue
            control = lighting_store.find("lighting_control", int(row["控制记录id"]))
            if control is None or control["档位"] != row["应开档位"]:
                mismatches.append(f"{row['日期']} {row['回路编号']} 排程档位与控制记录不一致")
        return {"ok": not mismatches, "不一致项": mismatches, "核对时间": _now_text()}


def seed_demo_data(service: LightingService) -> None:
    """服务首启时铺一份演示排程与控制记录，让页面打开就能看到口径在跑。"""
    # 覆盖中秋节（节庆）与国庆节（节庆）之间的一段日期。
    service.generate_schedules("2026-09-25", "2026-10-07")
    # 滨江堤岸回路：09-30 常规时段内已成功下发常规档（台账/监控读到的就是这条）。
    service.issue(1, "2026-09-30", "19:10", "值班管理员")
    # 中央广场投光灯回路：白天申请开灯被拒并留痕（超出允许亮灯时段）。
    service.issue(3, "2026-09-30", "15:00", "值班管理员")
    # 滨江步道回路电流 17.3 A 超过园区上限 16 A，单独告警。
    service.report_current(2, 17.3)


lighting_service = LightingService()
seed_demo_data(lighting_service)


def reset_lighting_service() -> None:
    """测试辅助：内存表回初始示例数据，再铺一遍演示排程与控制记录。

    store 是被路由和服务共同引用的同一对象，这里就地重建它的表，
    不替换单例引用。
    """
    lighting_store.reset()
    seed_demo_data(lighting_service)
