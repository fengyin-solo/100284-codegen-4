"""景观照明开关口径回归测试：对照需求十条逐项验证。

运行：PYTHONPATH=. python3 -m unittest discover -s tests -v
依赖：fastapi、httpx（TestClient）。
"""
from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from app.main import app
from app.services.lighting import reset_lighting_service
from app.services.lighting_calendar import season_of
from datetime import date

API = "/api/lighting"


class LightingRuleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)

    def setUp(self) -> None:
        reset_lighting_service()

    def post(self, path: str, values: dict) -> dict:
        return self.client.post(f"{API}{path}", json={"values": values}).json()

    def test_season_by_solar_terms(self) -> None:
        # 节气日历：立春前算冬，立春后算春，立秋后算秋。
        self.assertEqual(season_of(date(2026, 2, 3)), "冬")
        self.assertEqual(season_of(date(2026, 2, 4)), "春")
        self.assertEqual(season_of(date(2026, 8, 7)), "秋")
        self.assertEqual(season_of(date(2026, 11, 7)), "冬")

    def test_normal_window_gear(self) -> None:
        # 2026-09-30 是秋季常规日，19:00 落在 18:00-22:00，应开常规档。
        data = self.post("/decide", {"日期": "2026-09-30", "时刻": "19:00"})
        row = next(item for item in data["items"] if item["回路编号"] == "LIGHT-BJ-01")
        self.assertTrue(row["允许开灯"])
        self.assertEqual(row["档位"], 2)

    def test_outside_window_rejected_with_reason(self) -> None:
        result = self.post("/circuits/1/issue", {"日期": "2026-09-30", "时刻": "15:00"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["entry"]["状态"], "拒绝")
        self.assertIn("允许亮灯时段", result["message"])

    def test_over_current_alarm_isolated(self) -> None:
        # 中央广场阈值 12A，13.5A 必须单独告警；回落到限值内自动解除。
        result = self.post("/circuits/3/current", {"当前电流": 13.5})
        self.assertTrue(result["ok"])
        self.assertIsNotNone(result["entry"]["告警"])
        self.post("/circuits/3/current", {"当前电流": 8})
        open_alarms = self.client.get(f"{API}/alarms").json()["items"]
        self.assertFalse(any(a["回路编号"] == "LIGHT-ZY-01" for a in open_alarms))

    def test_rule_change_recalculates_schedules(self) -> None:
        def first_row() -> dict:
            items = self.client.get(f"{API}/schedules", params={"date": "2026-09-30"}).json()["items"]
            return next(x for x in items if x["回路编号"] == "LIGHT-BJ-01")

        self.assertEqual(first_row()["开灯时间"], "18:00")
        result = self.post("/rules/windows/3", {"开灯时间": "18:05"})
        self.assertTrue(result["ok"])
        self.assertIn("重算", result["message"])
        self.assertEqual(first_row()["开灯时间"], "18:05")
        self.post("/rules/windows/3", {"开灯时间": "18:00"})

    def test_park_thresholds_independent(self) -> None:
        parks = {p["id"]: p for p in self.client.get(f"{API}/parks").json()["items"]}
        self.assertEqual(parks[1]["电流上限"], 16.0)
        self.assertEqual(parks[2]["电流上限"], 12.0)
        self.post("/parks/2/threshold", {"电流上限": 14})
        circuits = {c["回路编号"]: c for c in self.client.get(f"{API}/circuits").json()["items"]}
        self.assertEqual(circuits["LIGHT-ZY-01"]["电流上限"], 14.0)
        self.assertEqual(circuits["LIGHT-BJ-01"]["电流上限"], 16.0)
        self.post("/parks/2/threshold", {"电流上限": 12})

    def test_broken_circuit_excluded(self) -> None:
        rows = self.client.get(f"{API}/schedules", params={"date": "2026-10-02"}).json()["items"]
        broken = next(x for x in rows if x["回路编号"] == "LIGHT-ZY-02")
        self.assertEqual(broken["状态"], "不参与排程")
        result = self.post("/circuits/4/issue", {"日期": "2026-10-02", "时刻": "19:00"})
        self.assertFalse(result["ok"])
        self.assertIn("故障", result["message"])

    def test_ledger_matches_control_and_monitor(self) -> None:
        ledger = {c["id"]: c for c in self.client.get(f"{API}/circuits").json()["items"]}
        monitor = self.client.get(f"{API}/monitor").json()
        mon1 = next(x for x in monitor["items"] if x["回路编号"] == "LIGHT-BJ-01")
        # 台账与监控页都指向同一条生效控制记录。
        self.assertEqual(ledger[1]["当前档位"], mon1["当前档位"])
        self.assertEqual(ledger[1]["控制记录id"], mon1["控制记录id"])
        self.assertTrue(self.client.get(f"{API}/consistency").json()["ok"])

    def test_duplicate_issue_idempotent(self) -> None:
        first = self.post("/circuits/2/issue", {"日期": "2026-10-05", "时刻": "19:00"})
        self.assertTrue(first["ok"])
        second = self.post("/circuits/2/issue", {"日期": "2026-10-05", "时刻": "20:00"})
        self.assertIn("不重复生效", second["message"])
        controls = [
            x for x in self.client.get(f"{API}/controls", params={"effective": True}).json()["items"]
            if x["回路编号"] == "LIGHT-BJ-02" and x["日期"] == "2026-10-05"
        ]
        self.assertEqual(len(controls), 1)

    def test_festival_overrides_regular(self) -> None:
        # 国庆 22:30：常规秋季时段 22:00 已关灯，节庆口径延至 23:30 且全开。
        result = self.post("/circuits/3/issue", {"日期": "2026-10-01", "时刻": "22:30"})
        self.assertTrue(result["ok"])
        self.assertEqual(result["entry"]["档位"], 3)
        self.assertEqual(result["entry"]["依据"], "国庆节")
        # 节庆时段外依旧拒绝。
        denied = self.post("/circuits/3/issue", {"日期": "2026-10-01", "时刻": "23:45"})
        self.assertFalse(denied["ok"])


if __name__ == "__main__":
    unittest.main()
