"""景观照明领域服务：开灯口径判定、亮灯排程、控制下发与电流告警。

口径说明（与值班员约定的同一套规则，照明台账与控制记录都从这里取结论）：
1. 允许亮灯时段 = 按节气划分的常规亮灯窗口 + 节庆日历窗口；同一日期节庆与常规冲突时，节庆优先。
2. 档位只有三档：0=关灯、1=基础（节能）、2=常规、3=满档（节庆）。
3. 请求下发的时刻不在任何允许亮灯窗口内，一律拒绝并给出缘由；故障回路不参与排程也不允许下发。
4. 同一条灯具回路、同一个时段日期重复下发只生效一次（幂等）。
5. 回路电流超过所属园区阈值时单独写入告警表；阈值按园区分别配置。
6. 判定标准（常规窗口/节庆日历/阈值）变更后自动重算既有亮灯排程，已下发的控制记录保留、排程档位随之刷新。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from app.store import store

# ---------------------------------------------------------------------------
# 常量与口径
# ---------------------------------------------------------------------------

PARK_TABLE = "lighting_parks"
CIRCUIT_TABLE = "lighting_circuits"
WINDOW_TABLE = "lighting_windows"
FESTIVAL_TABLE = "lighting_festivals"
SCHEDULE_TABLE = "lighting_schedules"
CONTROL_TABLE = "lighting_controls"
ALARM_TABLE = "lighting_alarms"
LIGHTING_TABLES = {
    PARK_TABLE,
    CIRCUIT_TABLE,
    WINDOW_TABLE,
    FESTIVAL_TABLE,
    SCHEDULE_TABLE,
    CONTROL_TABLE,
    ALARM_TABLE,
}

GEAR_OFF = 0
GEAR_BASIC = 1
GEAR_NORMAL = 2
GEAR_FULL = 3
GEAR_LABELS = {0: "关灯", 1: "基础", 2: "常规", 3: "满档"}

# 2026 年二十四节气交节日期；判定某一天属于哪个季节常规窗口。
# 立春/立夏/立秋/立冬为四季起点，节气当天即归入新季节。
SOLAR_TERMS_2026: dict[date, str] = {
    date(2026, 2, 4): "立春",
    date(2026, 2, 18): "雨水",
    date(2026, 3, 5): "惊蛰",
    date(2026, 3, 20): "春分",
    date(2026, 4, 5): "清明",
    date(2026, 4, 20): "谷雨",
    date(2026, 5, 5): "立夏",
    date(2026, 5, 21): "小满",
    date(2026, 6, 5): "芒种",
    date(2026, 6, 21): "夏至",
    date(2026, 7, 7): "小暑",
    date(2026, 7, 23): "大暑",
    date(2026, 8, 7): "立秋",
    date(2026, 8, 23): "处暑",
    date(2026, 9, 7): "白露",
    date(2026, 9, 23): "秋分",
    date(2026, 10, 8): "寒露",
    date(2026, 10, 23): "霜降",
    date(2026, 11, 7): "立冬",
    date(2026, 11, 22): "小雪",
    date(2026, 12, 7): "大雪",
    date(2026, 12, 21): "冬至",
    date(2027, 1, 5): "小寒",
    date(2027, 1, 20): "大寒",
}

# 季节到最近一次交节日的反查在 season_of_date 里做，这里只声明口径顺序。
SEASON_BOUNDS = [
    (date(2026, 2, 4), "春季"),
    (date(2026, 5, 5), "夏季"),
    (date(2026, 8, 7), "秋季"),
    (date(2026, 11, 7), "冬季"),
]

SCHEDULE_HORIZON_DAYS = 7


def _today() -> date:
    return datetime.now().date()


def season_of_date(day: date) -> str:
    """按节气日历判定日期所属季节：立春→春季，立夏→夏季，立秋→秋季，立冬→冬季。

    年初立春之前仍属上一年冬季。
    """
    current = "冬季"
    for bound, name in SEASON_BOUNDS:
        if day >= bound:
            current = name
    return current


def parse_hhmm(value: str) -> tuple[int, int]:
    """把 HH:MM 解析成时分；格式非法时抛 ValueError。"""
    text = str(value or "").strip()
    parts = text.split(":")
    if len(parts) != 2:
        raise ValueError(f"时间「{value}」格式应为 HH:MM")
    hour, minute = int(parts[0]), int(parts[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"时间「{value}」超出合法范围")
    return hour, minute


def _to_minutes(value: str) -> int:
    hour, minute = parse_hhmm(value)
    return hour * 60 + minute


def time_in_window(hhmm: str, begin: str, end: str) -> bool:
    """判断 HH:MM 是否落在 [begin, end) 窗口内，支持跨午夜（如 18:00-次日06:00）。"""
    point = _to_minutes(hhmm)
    start = _to_minutes(begin)
    stop = _to_minutes(end)
    if start <= stop:
        return start <= point < stop
    return point >= start or point < stop


# ---------------------------------------------------------------------------
# 示例数据（首次启动时注入内存库）
# ---------------------------------------------------------------------------

def ensure_seed() -> None:
    """景观照明模块的示例台账，幂等：已经注入过就不再重复。"""
    if PARK_TABLE in store._tables and store.rows(PARK_TABLE):
        return

    parks = [
        {"id": 1, "园区编号": "PARK-CY", "园区名称": "中央公园", "电流上限A": 32.0},
        {"id": 2, "园区编号": "PARK-BH", "园区名称": "滨湖步道", "电流上限A": 20.0},
        {"id": 3, "园区编号": "PARK-WH", "园区名称": "文化广场", "电流上限A": 25.0},
    ]
    # 回路状态：正常 / 故障；故障回路不参与排程。
    circuits = [
        {"id": 1, "回路编号": "LGT-CY-01", "回路名称": "主轴步道灯", "园区": "中央公园",
         "额定电流A": 12.0, "当前电流A": 11.2, "回路状态": "正常"},
        {"id": 2, "回路编号": "LGT-CY-02", "回路名称": "广场投光灯", "园区": "中央公园",
         "额定电流A": 28.0, "当前电流A": 34.6, "回路状态": "正常"},
        {"id": 3, "回路编号": "LGT-CY-03", "回路名称": "水景轮廓灯", "园区": "中央公园",
         "额定电流A": 9.0, "当前电流A": 0.0, "回路状态": "故障"},
        {"id": 4, "回路编号": "LGT-BH-01", "回路名称": "栈桥洗墙灯", "园区": "滨湖步道",
         "额定电流A": 8.5, "当前电流A": 7.9, "回路状态": "正常"},
        {"id": 5, "回路编号": "LGT-BH-02", "回路名称": "护坡投光灯", "园区": "滨湖步道",
         "额定电流A": 15.0, "当前电流A": 13.8, "回路状态": "正常"},
        {"id": 6, "回路编号": "LGT-WH-01", "回路名称": "门区景观灯", "园区": "文化广场",
         "额定电流A": 10.0, "当前电流A": 9.6, "回路状态": "正常"},
        {"id": 7, "回路编号": "LGT-WH-02", "回路名称": "雕塑庭院灯", "园区": "文化广场",
         "额定电流A": 12.0, "当前电流A": 11.1, "回路状态": "正常"},
    ]
    # 常规亮灯窗口按节气季节配置；时间为允许亮灯的时段，档位为该时段目标档。
    windows = [
        {"id": 1, "季节": "春季", "开始时间": "18:30", "结束时间": "22:00", "档位": GEAR_NORMAL},
        {"id": 2, "季节": "夏季", "开始时间": "19:30", "结束时间": "22:30", "档位": GEAR_NORMAL},
        {"id": 3, "季节": "秋季", "开始时间": "18:00", "结束时间": "22:00", "档位": GEAR_NORMAL},
        {"id": 4, "季节": "冬季", "开始时间": "17:30", "结束时间": "21:30", "档位": GEAR_NORMAL},
    ]
    festivals = [
        {"id": 1, "节庆名称": "国庆节", "开始日期": "2026-10-01", "结束日期": "2026-10-07",
         "开始时间": "18:00", "结束时间": "23:00", "档位": GEAR_FULL},
        {"id": 2, "节庆名称": "中秋节", "开始日期": "2026-09-25", "结束日期": "2026-09-25",
         "开始时间": "18:00", "结束时间": "23:00", "档位": GEAR_FULL},
        {"id": 3, "节庆名称": "春节", "开始日期": "2027-02-06", "结束日期": "2027-02-12",
         "开始时间": "17:30", "结束时间": "23:30", "档位": GEAR_FULL},
    ]
    store._tables[PARK_TABLE] = parks
    store._tables[CIRCUIT_TABLE] = circuits
    store._tables[WINDOW_TABLE] = windows
    store._tables[FESTIVAL_TABLE] = festivals
    store._tables[SCHEDULE_TABLE] = []
    store._tables[CONTROL_TABLE] = []
    store._tables[ALARM_TABLE] = []

    LightingService().rebuild_schedules(reason="初始化亮灯排程")
    LightingService().evaluate_all_currents(reason="初始化电流巡检")


# ---------------------------------------------------------------------------
# 领域服务
# ---------------------------------------------------------------------------

class LightingService:
    # ----- 园区阈值 -----
    def list_parks(self) -> list[dict[str, Any]]:
        return store.rows(PARK_TABLE)

    def update_park_threshold(self, park_id: int, threshold: Any) -> tuple[dict[str, Any] | None, str]:
        park = store.find(PARK_TABLE, park_id)
        if park is None:
            return None, f"园区 {park_id} 不存在"
        try:
            value = float(threshold)
        except (TypeError, ValueError):
            return None, "电流上限必须是数字，单位 A"
        if value <= 0:
            return None, "电流上限必须大于 0"
        park["电流上限A"] = value
        # 阈值属于判定标准，变更后对既有电流结论重新巡检（排程不依赖阈值，无需重算）。
        self.evaluate_all_currents(reason=f"园区「{park['园区名称']}」阈值调整为 {value:g}A")
        return park, f"园区「{park['园区名称']}」电流上限已更新为 {value:g}A，并重新巡检告警"

    # ----- 灯具回路台账 -----
    def list_circuits(self, *, park: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
        rows = store.rows(CIRCUIT_TABLE)
        if park:
            rows = [row for row in rows if row.get("园区") == park]
        if status:
            rows = [row for row in rows if row.get("回路状态") == status]
        return rows

    def create_circuit(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        required = ["回路编号", "回路名称", "园区", "额定电流A"]
        missing = [field for field in required if str(values.get(field) or "").strip() == ""]
        if missing:
            return None, missing
        park_name = str(values["园区"]).strip()
        if not any(row["园区名称"] == park_name for row in store.rows(PARK_TABLE)):
            return None, ["园区（需先在园区阈值中登记）"]
        rows = store.rows(CIRCUIT_TABLE)
        if any(row.get("回路编号") == str(values["回路编号"]).strip() for row in rows):
            return None, ["回路编号（已存在）"]
        try:
            rated = float(values["额定电流A"])
        except (TypeError, ValueError):
            return None, ["额定电流A（必须是数字）"]
        entry = {"id": self._next_id(CIRCUIT_TABLE)}
        entry["回路编号"] = str(values["回路编号"]).strip()
        entry["回路名称"] = str(values["回路名称"]).strip()
        entry["园区"] = park_name
        entry["额定电流A"] = rated
        entry["当前电流A"] = float(values.get("当前电流A") or 0)
        entry["回路状态"] = "正常"
        rows.append(entry)
        self.rebuild_schedules(reason=f"新灯具回路「{entry['回路编号']}」登记")
        self.evaluate_all_currents(reason=f"新灯具回路「{entry['回路编号']}」登记")
        return entry, []

    def report_current(self, circuit_id: int, current: Any) -> tuple[dict[str, Any] | None, str]:
        circuit = store.find(CIRCUIT_TABLE, circuit_id)
        if circuit is None:
            return None, f"灯具回路 {circuit_id} 不存在"
        try:
            value = float(current)
        except (TypeError, ValueError):
            return None, "电流读数必须是数字，单位 A"
        circuit["当前电流A"] = value
        self.evaluate_all_currents(reason=f"回路「{circuit['回路编号']}」上报电流 {value:g}A")
        return circuit, f"回路「{circuit['回路编号']}」电流读数已更新并重新巡检"

    def mark_status(self, circuit_id: int, fault: bool) -> tuple[dict[str, Any] | None, str]:
        circuit = store.find(CIRCUIT_TABLE, circuit_id)
        if circuit is None:
            return None, f"灯具回路 {circuit_id} 不存在"
        circuit["回路状态"] = "故障" if fault else "正常"
        # 回路健康状况直接影响排程覆盖面，必须重算。
        self.rebuild_schedules(
            reason=f"回路「{circuit['回路编号']}」标记为{'故障，退出排程' if fault else '修复，重新纳入排程'}"
        )
        return circuit, f"回路「{circuit['回路编号']}」已标记为{circuit['回路状态']}，亮灯排程已重算"

    # ----- 判定标准：常规窗口 -----
    def list_windows(self) -> list[dict[str, Any]]:
        return store.rows(WINDOW_TABLE)

    def update_window(self, window_id: int, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        window = store.find(WINDOW_TABLE, window_id)
        if window is None:
            return None, f"季节窗口 {window_id} 不存在"
        begin = str(values.get("开始时间") or window["开始时间"]).strip()
        end = str(values.get("结束时间") or window["结束时间"]).strip()
        try:
            parse_hhmm(begin)
            parse_hhmm(end)
        except ValueError as exc:
            return None, str(exc)
        gear = values.get("档位", window["档位"])
        if int(gear) not in GEAR_LABELS or int(gear) == GEAR_OFF:
            return None, "常规窗口档位只能是 1 基础 / 2 常规 / 3 满档"
        window["开始时间"] = begin
        window["结束时间"] = end
        window["档位"] = int(gear)
        self.rebuild_schedules(reason=f"{window['季节']}常规亮灯窗口口径变更")
        return window, f"{window['季节']}常规窗口已更新，既有亮灯排程已按新口径重算"

    # ----- 判定标准：节庆日历 -----
    def list_festivals(self) -> list[dict[str, Any]]:
        return store.rows(FESTIVAL_TABLE)

    def create_festival(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        required = ["节庆名称", "开始日期", "结束日期", "开始时间", "结束时间", "档位"]
        missing = [field for field in required if str(values.get(field) or "").strip() == ""]
        if missing:
            return None, missing
        try:
            begin_day = date.fromisoformat(str(values["开始日期"]).strip())
            end_day = date.fromisoformat(str(values["结束日期"]).strip())
            parse_hhmm(str(values["开始时间"]))
            parse_hhmm(str(values["结束时间"]))
            gear = int(values["档位"])
        except ValueError:
            return None, ["日期/时间/档位格式不合法（日期 YYYY-MM-DD、时间 HH:MM、档位 1-3）"]
        if end_day < begin_day:
            return None, ["结束日期不能早于开始日期"]
        if gear not in (GEAR_BASIC, GEAR_NORMAL, GEAR_FULL):
            return None, ["档位（只允许 1 基础 / 2 常规 / 3 满档）"]
        entry = {
            "id": self._next_id(FESTIVAL_TABLE),
            "节庆名称": str(values["节庆名称"]).strip(),
            "开始日期": begin_day.isoformat(),
            "结束日期": end_day.isoformat(),
            "开始时间": str(values["开始时间"]).strip(),
            "结束时间": str(values["结束时间"]).strip(),
            "档位": gear,
        }
        store.rows(FESTIVAL_TABLE).append(entry)
        self.rebuild_schedules(reason=f"新增节庆「{entry['节庆名称']}」")
        return entry, []

    def delete_festival(self, festival_id: int) -> str:
        rows = store.rows(FESTIVAL_TABLE)
        target = next((row for row in rows if int(row["id"]) == festival_id), None)
        if target is None:
            return f"节庆 {festival_id} 不存在"
        name = target["节庆名称"]
        rows.remove(target)
        self.rebuild_schedules(reason=f"删除节庆「{name}」")
        return f"节庆「{name}」已删除，既有亮灯排程已重算"

    # ----- 口径判定引擎（台账与控制记录共用的唯一结论来源） -----
    def evaluate(self, *, day: date, hhmm: str, park: str | None = None) -> dict[str, Any]:
        """判定某一时刻（可选限定园区，节庆口径全市统一）的开灯档位。

        返回：{allowed, gear, gear_label, reason, season, source, window}
        节庆窗口与常规窗口冲突时一律以节庆为准；都不命中则不允许开灯。
        """
        season = season_of_date(day)

        festival = self._festival_at(day, hhmm)
        if festival is not None:
            return {
                "allowed": True,
                "gear": festival["档位"],
                "gear_label": GEAR_LABELS[int(festival["档位"])],
                "reason": f"{day} 属节庆「{festival['节庆名称']}」亮灯时段，节庆要求优先于常规时段",
                "season": season,
                "source": "节庆日历",
                "window": {"开始时间": festival["开始时间"], "结束时间": festival["结束时间"],
                           "名称": festival["节庆名称"]},
            }

        window = self._season_window(season)
        if window is not None and time_in_window(hhmm, window["开始时间"], window["结束时间"]):
            return {
                "allowed": True,
                "gear": window["档位"],
                "gear_label": GEAR_LABELS[int(window["档位"])],
                "reason": f"{day} 为节气日历{season}，{hhmm} 在{season}常规亮灯时段"
                          f" {window['开始时间']}-{window['结束时间']} 内",
                "season": season,
                "source": "常规节气窗口",
                "window": {"开始时间": window["开始时间"], "结束时间": window["结束时间"], "名称": season},
            }

        return {
            "allowed": False,
            "gear": GEAR_OFF,
            "gear_label": GEAR_LABELS[GEAR_OFF],
            "reason": f"{day} {hhmm} 不属于{season}常规亮灯时段，也不在任何节庆亮灯日历内，按口径不允许开灯",
            "season": season,
            "source": None,
            "window": None,
        }

    def _festival_at(self, day: date, hhmm: str) -> dict[str, Any] | None:
        for festival in store.rows(FESTIVAL_TABLE):
            begin_day = date.fromisoformat(festival["开始日期"])
            end_day = date.fromisoformat(festival["结束日期"])
            if begin_day <= day <= end_day and time_in_window(hhmm, festival["开始时间"], festival["结束时间"]):
                return festival
        return None

    def _season_window(self, season: str) -> dict[str, Any] | None:
        return next(
            (row for row in store.rows(WINDOW_TABLE) if row.get("季节") == season),
            None,
        )

    # ----- 亮灯排程 -----
    def list_schedules(self, *, day: str | None = None, park: str | None = None,
                       circuit_no: str | None = None) -> list[dict[str, Any]]:
        rows = store.rows(SCHEDULE_TABLE)
        if day:
            rows = [row for row in rows if row.get("日期") == day]
        if park:
            rows = [row for row in rows if row.get("园区") == park]
        if circuit_no:
            rows = [row for row in rows if row.get("回路编号") == circuit_no]
        return rows

    def rebuild_schedules(self, *, reason: str) -> dict[str, Any]:
        """按现行口径重算未来 SCHEDULE_HORIZON_DAYS 天的亮灯排程。

        故障回路不参与；已下发的排程保留其下发记录关联，仅刷新档位结论。
        """
        today = _today()
        days = [(today + timedelta(days=i)).isoformat() for i in range(SCHEDULE_HORIZON_DAYS)]
        healthy = [c for c in store.rows(CIRCUIT_TABLE) if c.get("回路状态") != "故障"]

        old_rows = store.rows(SCHEDULE_TABLE)
        # 已下发排程按 (回路,日期) 记忆，重算后档位以新口径为准，下发事实不变。
        dispatched = {
            (row["回路编号"], row["日期"]): row
            for row in old_rows
            if row.get("状态") == "已下发"
        }

        new_rows: list[dict[str, Any]] = []
        seq = 0
        for day_text in days:
            day_obj = date.fromisoformat(day_text)
            # 以窗口起始时刻作为该日排程档位的判定锚点：节庆优先，否则取当日季节常规档。
            festival = next(
                (f for f in store.rows(FESTIVAL_TABLE)
                 if date.fromisoformat(f["开始日期"]) <= day_obj <= date.fromisoformat(f["结束日期"])),
                None,
            )
            if festival is not None:
                gear = int(festival["档位"])
                source = f"节庆：{festival['节庆名称']}"
                begin, end = festival["开始时间"], festival["结束时间"]
            else:
                window = self._season_window(season_of_date(day_obj))
                if window is None:
                    continue
                gear = int(window["档位"])
                source = f"节气：{season_of_date(day_obj)}常规"
                begin, end = window["开始时间"], window["结束时间"]

            for circuit in healthy:
                seq += 1
                key = (circuit["回路编号"], day_text)
                prior = dispatched.get(key)
                new_rows.append({
                    "id": seq,
                    "日期": day_text,
                    "园区": circuit["园区"],
                    "回路编号": circuit["回路编号"],
                    "回路名称": circuit["回路名称"],
                    "开始时间": begin,
                    "结束时间": end,
                    "档位": gear,
                    "档位名称": GEAR_LABELS[gear],
                    "判定依据": source,
                    "状态": prior["状态"] if prior else "待下发",
                    "控制记录id": prior["控制记录id"] if prior else None,
                })

        # 重排 id，保持稳定可读。
        store._tables[SCHEDULE_TABLE] = new_rows
        store.set_meta("lighting_criteria_version", int(store.get_meta("lighting_criteria_version", 0)) + 1)
        store.set_meta("lighting_last_rebuild_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        store.set_meta("lighting_last_rebuild_reason", reason)
        return {"条数": len(new_rows), "天数": SCHEDULE_HORIZON_DAYS, "原因": reason}

    # ----- 控制下发（幂等 + 时段口径校验 + 电流告警） -----
    def list_controls(self, *, circuit_no: str | None = None, day: str | None = None) -> list[dict[str, Any]]:
        rows = store.rows(CONTROL_TABLE)
        if circuit_no:
            rows = [row for row in rows if row.get("回路编号") == circuit_no]
        if day:
            rows = [row for row in rows if row.get("下发时间", "").startswith(day)]
        return rows

    def dispatch(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str, bool]:
        """下发一条开灯指令。

        返回 (记录或None, 说明, 是否幂等命中已有记录)。
        时段口径以 evaluate() 的结论为准；同一回路同一时段日期只允许存在一条生效记录。
        """
        circuit_no = str(values.get("回路编号") or "").strip()
        slot_date_text = str(values.get("时段日期") or "").strip()
        hhmm = str(values.get("时刻") or datetime.now().strftime("%H:%M")).strip()

        if not circuit_no or not slot_date_text:
            return None, "缺少回路编号或时段日期", False
        circuit = next((c for c in store.rows(CIRCUIT_TABLE) if c["回路编号"] == circuit_no), None)
        if circuit is None:
            return None, f"灯具回路「{circuit_no}」台账中不存在", False
        try:
            slot_day = date.fromisoformat(slot_date_text)
        except ValueError:
            return None, "时段日期格式应为 YYYY-MM-DD", False
        try:
            parse_hhmm(hhmm)
        except ValueError as exc:
            return None, str(exc), False

        if circuit.get("回路状态") == "故障":
            return None, f"回路「{circuit_no}」已故障，按口径不参与排程，禁止下发", False

        verdict = self.evaluate(day=slot_day, hhmm=hhmm, park=circuit["园区"])
        if not verdict["allowed"]:
            return None, f"已拦截，不允许开灯：{verdict['reason']}", False

        # 幂等：同一回路、同一时段日期只生效一次。
        existing = next(
            (row for row in store.rows(CONTROL_TABLE)
             if row["回路编号"] == circuit_no and row["时段日期"] == slot_date_text),
            None,
        )
        if existing is not None:
            return existing, f"回路「{circuit_no}」{slot_date_text} 时段已下发过（记录#{existing['id']}），重复提交只生效一次", True

        record = {
            "id": self._next_id(CONTROL_TABLE),
            "回路编号": circuit_no,
            "回路名称": circuit["回路名称"],
            "园区": circuit["园区"],
            "时段日期": slot_date_text,
            "下发时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "档位": verdict["gear"],
            "档位名称": verdict["gear_label"],
            "判定依据": verdict["source"],
            "判定说明": verdict["reason"],
            "状态": "已生效",
        }
        store.rows(CONTROL_TABLE).append(record)

        # 回填当日排程状态，保证排程与控制记录同源。
        schedule = next(
            (row for row in store.rows(SCHEDULE_TABLE)
             if row["回路编号"] == circuit_no and row["日期"] == slot_date_text),
            None,
        )
        if schedule is not None:
            schedule["状态"] = "已下发"
            schedule["控制记录id"] = record["id"]
            schedule["档位"] = record["档位"]
            schedule["档位名称"] = record["档位名称"]

        alarm_note = self._check_current(circuit, record)
        if alarm_note:
            record["状态"] = "已生效（电流告警）"
        return record, f"已按{verdict['source']}下发：{verdict['reason']}。{alarm_note}".rstrip("。"), False

    # ----- 电流告警（阈值按园区） -----
    def list_alarms(self, *, active_only: bool = False) -> list[dict[str, Any]]:
        rows = store.rows(ALARM_TABLE)
        if active_only:
            rows = [row for row in rows if row.get("状态") == "未处理"]
        return rows

    def evaluate_all_currents(self, *, reason: str) -> int:
        """按各园区现行阈值巡检全部在用回路电流，超限的保证有一条未处理告警；恢复后自动关闭。"""
        parks = {row["园区名称"]: float(row["电流上限A"]) for row in store.rows(PARK_TABLE)}
        count = 0
        for circuit in store.rows(CIRCUIT_TABLE):
            limit = parks.get(circuit["园区"])
            current = float(circuit.get("当前电流A") or 0)
            over = limit is not None and current > limit

            open_alarm = next(
                (row for row in store.rows(ALARM_TABLE)
                 if row["回路编号"] == circuit["回路编号"] and row["状态"] == "未处理"),
                None,
            )
            if over and open_alarm is None:
                store.rows(ALARM_TABLE).append({
                    "id": self._next_id(ALARM_TABLE),
                    "告警编号": f"ALM-{len(store.rows(ALARM_TABLE)) + 1:04d}",
                    "园区": circuit["园区"],
                    "回路编号": circuit["回路编号"],
                    "回路名称": circuit["回路名称"],
                    "当前电流A": current,
                    "阈值A": limit,
                    "告警时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "触发原因": reason,
                    "状态": "未处理",
                })
                count += 1
            elif not over and open_alarm is not None:
                open_alarm["状态"] = "已恢复"
                open_alarm["恢复说明"] = f"电流 {current:g}A 已回落至阈值 {limit:g}A 以内"
        return count

    def _check_current(self, circuit: dict[str, Any], record: dict[str, Any]) -> str:
        """下发后即时校核该回路电流，超限立刻单独告警。"""
        park = next((row for row in store.rows(PARK_TABLE) if row["园区名称"] == circuit["园区"]), None)
        if park is None:
            return ""
        limit = float(park["电流上限A"])
        current = float(circuit.get("当前电流A") or 0)
        if current <= limit:
            return ""
        store.rows(ALARM_TABLE).append({
            "id": self._next_id(ALARM_TABLE),
            "告警编号": f"ALM-{len(store.rows(ALARM_TABLE)) + 1:04d}",
            "园区": circuit["园区"],
            "回路编号": circuit["回路编号"],
            "回路名称": circuit["回路名称"],
            "当前电流A": current,
            "阈值A": limit,
            "告警时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "触发原因": f"控制记录#{record['id']} 下发后电流校核",
            "状态": "未处理",
        })
        return f"电流校核：{current:g}A 超过园区「{circuit['园区']}」上限 {limit:g}A，已单独告警。"

    def resolve_alarm(self, alarm_id: int) -> tuple[dict[str, Any] | None, str]:
        alarm = store.find(ALARM_TABLE, alarm_id)
        if alarm is None:
            return None, f"告警 {alarm_id} 不存在"
        alarm["状态"] = "已处理"
        return alarm, f"告警 {alarm['告警编号']} 已处理"

    # ----- 台账视图 & 口径核对（与控制记录结论必须一致） -----
    def ledger(self) -> list[dict[str, Any]]:
        """照明台账：当前档位结论直接取控制记录（单一数据源），任何页面读到的都是同一份。"""
        now = datetime.now()
        verdict = self.evaluate(day=now.date(), hhmm=now.strftime("%H:%M"))
        latest_controls: dict[str, dict[str, Any]] = {}
        for record in store.rows(CONTROL_TABLE):
            latest_controls[record["回路编号"]] = record

        parks = {row["园区名称"]: float(row["电流上限A"]) for row in store.rows(PARK_TABLE)}
        result = []
        for circuit in store.rows(CIRCUIT_TABLE):
            record = latest_controls.get(circuit["回路编号"])
            limit = parks.get(circuit["园区"])
            current = float(circuit.get("当前电流A") or 0)
            if circuit["回路状态"] == "故障":
                gear, gear_label, source = GEAR_OFF, "故障停用", "回路故障，不参与排程"
            elif record is not None:
                gear, gear_label, source = record["档位"], record["档位名称"], f"控制记录#{record['id']}"
            elif verdict["allowed"]:
                gear, gear_label, source = verdict["gear"], verdict["gear_label"], "现行口径（尚未下发）"
            else:
                gear, gear_label, source = GEAR_OFF, GEAR_LABELS[GEAR_OFF], "当前非允许亮灯时段"
            result.append({
                "回路编号": circuit["回路编号"],
                "回路名称": circuit["回路名称"],
                "园区": circuit["园区"],
                "回路状态": circuit["回路状态"],
                "额定电流A": circuit["额定电流A"],
                "当前电流A": current,
                "电流上限A": limit,
                "电流是否超限": limit is not None and current > limit,
                "当前档位": gear,
                "当前档位名称": gear_label,
                "档位来源": source,
                "控制记录id": record["id"] if record else None,
                "此刻口径是否允许开灯": verdict["allowed"] and circuit["回路状态"] != "故障",
            })
        return result

    def consistency_check(self) -> dict[str, Any]:
        """核对照明台账与控制记录：逐条比对同一回路的档位结论，二者必须一致。"""
        ledger_rows = self.ledger()
        latest: dict[str, dict[str, Any]] = {}
        for record in store.rows(CONTROL_TABLE):
            latest[record["回路编号"]] = record

        items = []
        mismatches = 0
        for row in ledger_rows:
            record = latest.get(row["回路编号"])
            record_gear = record["档位"] if record else None
            if row["回路状态"] == "故障":
                # 故障回路当前档位强制为关灯；只要台账如实标注故障停用即视为一致，
                # 历史控制记录仍保留在控制记录页可查。
                consistent = row["当前档位"] == GEAR_OFF and row["当前档位名称"] == "故障停用"
            elif record is not None:
                consistent = row["当前档位"] == record_gear
            else:
                consistent = True  # 无控制记录时以口径判定为准，不存在对不上的问题
            if not consistent:
                mismatches += 1
            items.append({
                "回路编号": row["回路编号"],
                "台账档位": row["当前档位"],
                "控制记录档位": record_gear,
                "是否一致": consistent,
            })
        return {
            "一致": mismatches == 0,
            "不一致条数": mismatches,
            "口径版本": store.get_meta("lighting_criteria_version", 1),
            "核对时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "明细": items,
        }

    def current_snapshot(self) -> dict[str, Any]:
        """供各页面共用的当下档位快照：与控制记录同源。"""
        now = datetime.now()
        verdict = self.evaluate(day=now.date(), hhmm=now.strftime("%H:%M"))
        return {
            "当前时间": now.strftime("%Y-%m-%d %H:%M"),
            "节气季节": verdict["season"],
            "允许开灯": verdict["allowed"],
            "口径档位": verdict["gear"],
            "口径档位名称": verdict["gear_label"],
            "判定依据": verdict["source"],
            "判定说明": verdict["reason"],
            "口径版本": store.get_meta("lighting_criteria_version", 1),
            "最近重算": store.get_meta("lighting_last_rebuild_at"),
            "最近重算原因": store.get_meta("lighting_last_rebuild_reason"),
        }

    # ----- 内部工具 -----
    def _next_id(self, table: str) -> int:
        return max((int(row.get("id", 0)) for row in store.rows(table)), default=0) + 1


lighting_service = LightingService()
