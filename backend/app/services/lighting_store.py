"""景观照明模块的内存数据仓库。

主仓 app/store.py 里的业务表都是「编号 + 8 个文本字段」的通用台账；
景观照明要放园区阈值、节气日历、排程、控制记录等结构化数据，通用表
装不下，所以这里单独维护一份带示例数据的仓库，对外仍然是单例 store，
保证台账、排程、控制记录、监控页读到的是同一份数据。
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any


def _seed() -> dict[str, list[dict[str, Any]]]:
    """构造一份示例数据：两个园区、四条回路（含一条故障回路）、默认节气时段与节庆日历。"""
    parks = [
        {
            "id": 1,
            "园区名称": "滨江公园",
            "电流上限": 16.0,
            "备注": "沿江步道与堤岸景观带",
        },
        {
            "id": 2,
            "园区名称": "中央广场",
            "电流上限": 12.0,
            "备注": "中心广场及中轴线亮化",
        },
    ]
    circuits = [
        {
            "id": 1,
            "回路编号": "LIGHT-BJ-01",
            "回路名称": "堤岸洗墙灯回路",
            "园区": "滨江公园",
            "电流上限": 16.0,
            "当前电流": 14.2,
            "回路状态": "正常",
        },
        {
            "id": 2,
            "回路编号": "LIGHT-BJ-02",
            "回路名称": "步道庭院灯回路",
            "园区": "滨江公园",
            "电流上限": 16.0,
            "当前电流": 17.3,
            "回路状态": "正常",
        },
        {
            "id": 3,
            "回路编号": "LIGHT-ZY-01",
            "回路名称": "广场投光灯回路",
            "园区": "中央广场",
            "电流上限": 12.0,
            "当前电流": 9.8,
            "回路状态": "正常",
        },
        {
            "id": 4,
            "回路编号": "LIGHT-ZY-02",
            "回路名称": "中轴地埋灯回路",
            "园区": "中央广场",
            "电流上限": 12.0,
            "当前电流": None,
            "回路状态": "故障",
            "故障描述": "回路绝缘故障，待检修",
        },
    ]
    # 节气亮灯时段（常规口径）：以四季首个节气为锚点划分，档位居中取常规档。
    window_rules = [
        {"id": 1, "季节": "春", "起始节气": "立春", "开灯时间": "18:30", "关灯时间": "22:00", "开灯档位": 2},
        {"id": 2, "季节": "夏", "起始节气": "立夏", "开灯时间": "19:30", "关灯时间": "23:00", "开灯档位": 2},
        {"id": 3, "季节": "秋", "起始节气": "立秋", "开灯时间": "18:00", "关灯时间": "22:00", "开灯档位": 2},
        {"id": 4, "季节": "冬", "起始节气": "立冬", "开灯时间": "17:00", "关灯时间": "21:30", "开灯档位": 1},
    ]
    # 节庆日历：节庆时段与常规时段冲突时，一律以节庆口径为准。
    festivals = [
        {
            "id": 1,
            "节庆名称": "中秋节",
            "开始日期": "2026-09-25",
            "结束日期": "2026-09-27",
            "开灯时间": "18:00",
            "关灯时间": "23:00",
            "开灯档位": 3,
        },
        {
            "id": 2,
            "节庆名称": "国庆节",
            "开始日期": "2026-10-01",
            "结束日期": "2026-10-07",
            "开灯时间": "18:00",
            "关灯时间": "23:30",
            "开灯档位": 3,
        },
    ]
    return {
        "lighting_park": parks,
        "lighting_circuit": circuits,
        "lighting_window_rule": window_rules,
        "lighting_festival": festivals,
        "lighting_schedule": [],
        "lighting_control": [],
        "lighting_alarm": [],
    }


class LightingStore:
    """景观照明专用仓库：表初始化、自增主键、整表替换都集中在这里。"""

    def __init__(self) -> None:
        self._tables: dict[str, list[dict[str, Any]]] = _seed()

    def reset(self) -> None:
        """清空后回到初始示例数据（测试隔离用）。"""
        self._tables = _seed()

    def rows(self, table: str) -> list[dict[str, Any]]:
        return self._tables.setdefault(table, [])

    def find(self, table: str, entry_id: int) -> dict[str, Any] | None:
        for row in self.rows(table):
            if int(row.get("id", 0)) == entry_id:
                return row
        return None

    def find_by(self, table: str, **criteria: Any) -> dict[str, Any] | None:
        for row in self.rows(table):
            if all(row.get(key) == value for key, value in criteria.items()):
                return row
        return None

    def insert(self, table: str, row: dict[str, Any]) -> dict[str, Any]:
        rows = self.rows(table)
        row["id"] = max((int(item.get("id", 0)) for item in rows), default=0) + 1
        rows.append(row)
        return row

    def snapshot(self) -> dict[str, list[dict[str, Any]]]:
        """供测试与一致性核对使用的深拷贝，避免外部直接改内存。"""
        return deepcopy(self._tables)


lighting_store = LightingStore()
