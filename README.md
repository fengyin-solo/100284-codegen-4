# 园林绿化养护管理平台

面向城市园林绿化植物的栽植养护、修剪造型、病虫害防治、灌溉施肥与绿地巡查的一体化绿化管理后台。

这是一个前后端分离的管理平台：前端 Vue 3 + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 Vue 3 + Vite + TypeScript 前端
│   ├── src/views/            每个业务模块一个页面
│   ├── src/api/              统一请求封装
│   ├── src/stores/           会话与筛选状态
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/          每个业务模块一组接口
│   ├── app/services/         业务规则与状态流转
│   └── app/store.py          内存数据仓库与示例数据
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8000/api/health`

### 前端

```bash
cd frontend
npm install
npm run dev
```

前端默认监听 `http://127.0.0.1:5173/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8000`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 绿地台账 | `plot` | 绿地 | 绿地编号、绿地名称、所属区域 |
| 乔木管理 | `tree` | 乔木 | 树木编号、树种名称、胸径 |
| 灌木管理 | `shrub` | 灌木 | 灌木编号、品种名称、栽植面积 |
| 草坪管理 | `lawn` | 草坪 | 草坪编号、草种类型、草坪面积 |
| 花卉造景 | `flower` | 花卉造景 | 造景编号、造景主题、花卉品种 |
| 病虫害防治 | `pest` | 防治记录 | 防治编号、受害植物、病虫种类 |
| 灌溉作业 | `irrigation` | 灌溉任务 | 灌溉编号、灌溉区域、灌溉方式 |
| 施肥作业 | `fertilize` | 施肥记录 | 施肥编号、施肥区域、肥料类型 |
| 修剪造型 | `prune` | 修剪任务 | 修剪编号、修剪对象、修剪类型 |
| 绿地巡查 | `patrol` | 巡查记录 | 巡查编号、巡查区域、巡查日期 |
| 杂草清除 | `weed` | 除草任务 | 除草编号、除草区域、杂草种类 |
| 树木支撑 | `support` | 支撑设施 | 支撑编号、所属树木、支撑方式 |
| 苗木移植 | `transplant` | 移植记录 | 移植编号、移植树种、移植数量 |
| 园建设施 | `facility` | 园建设施 | 设施编号、设施名称、设施类型 |
| 园林机械 | `equipment` | 园林机械 | 机械编号、机械名称、规格型号 |
| 苗木基地 | `seedling` | 苗圃 | 苗圃编号、苗圃名称、苗圃面积 |
| 水体养护 | `waterbody` | 水体 | 水体编号、水体类型、水体面积 |
| 名木古树 | `code` | 名木古树 | 古树编号、树种、树龄 |
| 市民热线 | `complaint` | 热线记录 | 记录编号、来电人、来电内容 |
| 季度养护方案 | `seasonplan` | 养护方案 | 方案编号、方案季度、覆盖绿地 |
| 景观照明 | `lighting` | 灯具回路/亮灯排程/控制记录/电流告警 | 回路编号、园区、亮灯时段、开灯档位、电流上限 |

### 景观照明开关口径

景观照明按统一口径自动判定，不再靠值班员凭感觉：

- **档位判定**：按亮灯时段与节气日历（立春/立夏/立秋/立冬分四季）判定开灯档位
  （1 节能 / 2 常规 / 3 全开）；节庆日历与常规时段冲突时节庆优先。
- **超时段拒绝**：超出当天允许亮灯时段的开灯申请直接拒绝，并在控制记录里留痕、
  说明缘由。
- **电流告警**：电流上限按园区分别配置；回路电流超过本园区上限时单独告警，
  回落到限值内自动解除。
- **排程重算**：节气时段、节庆日历、园区阈值、回路状态变更后，已有亮灯排程
  按新标准重算。
- **故障回路**：回路标记故障后不参与排程、禁止下发、电流不采信，修复后恢复。
- **同一结论**：照明台账、控制记录、亮灯监控页（`/lighting-monitor`）共用
  `current_gear` 一个档位口径；`GET /api/lighting/consistency` 可做一致性自检。
- **下发幂等**：同一回路同一日期同一亮灯时段重复提交，只有一条生效控制记录。

后端回归测试在 `backend/tests/`，运行：

```bash
cd backend
PYTHONPATH=. python3 -m unittest discover -s tests
```

## 约定

- 每个模块的前端页面在 `frontend/src/views/<模块>/index.vue`，后端接口在
  `backend/app/routers/<模块>.py`，业务规则在 `backend/app/services/<模块>.py`。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。
