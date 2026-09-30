"""节气日历与亮灯档位判定口径。

判定规则（统一收口在这里，台账、排程、监控页都调用同一份逻辑）：

1. 先看日期落不落在节庆日历内：落在节庆时段内，按节庆时段判定，
   节庆与常规冲突时节庆优先；
2. 不在节庆内的，按节气日历找到当天所属季节，用该季节的允许亮灯时段
   判定（以立春/立夏/立秋/立冬为锚点划分四季）；
3. 申请开灯的时刻必须落在允许亮灯时段 [开灯时间, 关灯时间] 内，否则
   不许开灯，并给出拒绝缘由；
4. 允许开灯时给出应开档位（1 节能 / 2 常规 / 3 全开）。
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

# 2026 年二十四节气交节日期（公历年只示范到年末，跨年判定时按上一年同月日近似处理）。
SOLAR_TERMS_2026: dict[str, str] = {
    "小寒": "2026-01-05",
    "大寒": "2026-01-20",
    "立春": "2026-02-04",
    "雨水": "2026-02-18",
    "惊蛰": "2026-03-05",
    "春分": "2026-03-20",
    "清明": "2026-04-05",
    "谷雨": "2026-04-20",
    "立夏": "2026-05-05",
    "小满": "2026-05-21",
    "芒种": "2026-06-05",
    "夏至": "2026-06-21",
    "小暑": "2026-07-07",
    "大暑": "2026-07-23",
    "立秋": "2026-08-07",
    "处暑": "2026-08-23",
    "白露": "2026-09-07",
    "秋分": "2026-09-23",
    "寒露": "2026-10-08",
    "霜降": "2026-10-23",
    "立冬": "2026-11-07",
    "小雪": "2026-11-22",
    "大雪": "2026-12-07",
    "冬至": "2026-12-22",
}

# 四季的锚定节气（常规亮灯时段按这四个节气切换）。
SEASON_ANCHORS = [
    ("春", "立春", "02-04"),
    ("夏", "立夏", "05-05"),
    ("秋", "立秋", "08-07"),
    ("冬", "立冬", "11-07"),
]

GEAR_LABELS = {1: "节能档", 2: "常规档", 3: "全开档"}


def season_of(day: date) -> str:
    """按节气锚点（月-日）判断当天所属季节：立春至立夏前为春，以此类推。"""
    month_day = (day.month, day.day)
    boundaries = [(season, tuple(int(part) for part in md.split("-"))) for season, _term, md in SEASON_ANCHORS]
    # 1 月 1 日到立春前仍属冬季。
    if month_day < boundaries[0][1]:
        return "冬"
    current = "冬"
    for season, anchor in boundaries:
        if month_day >= anchor:
            current = season
    return current


def _parse_day(value: str | date) -> date:
    if isinstance(value, date):
        return value
    return datetime.strptime(value, "%Y-%m-%d").date()


def _parse_clock(value: str) -> tuple[int, int]:
    hour, minute = (int(part) for part in value.split(":"))
    return hour, minute


def within_window(clock: str, start: str, end: str) -> bool:
    """时刻是否落在亮灯时段内（闭区间）；正常时段不跨午夜。"""
    return _parse_clock(start) <= _parse_clock(clock) <= _parse_clock(end)


def pick_festival(festivals: list[dict[str, Any]], day: date) -> dict[str, Any] | None:
    """找出当天适用的节庆；同一天命中多个节庆时取开始日期更晚的（最新节庆口径优先）。"""
    matched = [
        festival
        for festival in festivals
        if _parse_day(festival["开始日期"]) <= day <= _parse_day(festival["结束日期"])
    ]
    if not matched:
        return None
    return max(matched, key=lambda item: _parse_day(item["开始日期"]))


def decide(
    day: date,
    clock: str,
    window_rules: list[dict[str, Any]],
    festivals: list[dict[str, Any]],
) -> dict[str, Any]:
    """判定某个时刻该不该开灯、开几档。

    返回：
      allowed=False 时 reason 说明不许开灯的缘由（超出允许亮灯时段/未配置口径）；
      allowed=True 时给出 gear、rule_type（节庆/常规）、rule_name 与适用时段。
    """
    festival = pick_festival(festivals, day)
    if festival is not None:
        start, end = festival["开灯时间"], festival["关灯时间"]
        if within_window(clock, start, end):
            return {
                "allowed": True,
                "rule_type": "节庆",
                "rule_name": festival["节庆名称"],
                "gear": int(festival["开灯档位"]),
                "window_start": start,
                "window_end": end,
                "reason": f"处于{festival['节庆名称']}亮灯时段（{start}-{end}），节庆口径优先，应开{GEAR_LABELS[int(festival['开灯档位'])]}",
            }
        return {
            "allowed": False,
            "rule_type": "节庆",
            "rule_name": festival["节庆名称"],
            "gear": 0,
            "window_start": start,
            "window_end": end,
            "reason": f"当前时刻 {clock} 不在{festival['节庆名称']}允许亮灯时段（{start}-{end}）内，不许开灯",
        }

    season = season_of(day)
    rule = next((item for item in window_rules if item["季节"] == season), None)
    if rule is None:
        return {
            "allowed": False,
            "rule_type": "常规",
            "rule_name": season,
            "gear": 0,
            "window_start": None,
            "window_end": None,
            "reason": f"{season}季常规亮灯时段尚未配置，无开关口径可依，不许开灯",
        }
    start, end = rule["开灯时间"], rule["关灯时间"]
    if within_window(clock, start, end):
        gear = int(rule["开灯档位"])
        return {
            "allowed": True,
            "rule_type": "常规",
            "rule_name": f"{season}季（{rule['起始节气']}起）",
            "gear": gear,
            "window_start": start,
            "window_end": end,
            "reason": f"处于{season}季常规亮灯时段（{start}-{end}），应开{GEAR_LABELS[gear]}",
        }
    return {
        "allowed": False,
        "rule_type": "常规",
        "rule_name": f"{season}季（{rule['起始节气']}起）",
        "gear": 0,
        "window_start": start,
        "window_end": end,
        "reason": (
            f"当前时刻 {clock} 不在{season}季允许亮灯时段（{start}-{end}）内，"
            "超出允许亮灯时段，不许开灯"
        ),
    }
