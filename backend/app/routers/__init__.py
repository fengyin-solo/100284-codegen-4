"""业务模块路由汇总。

这里统一按别名导入再暴露 ROUTERS：模块名有可能和内置名撞车（某个业务模块就叫 dict、list
这种名字时），按名字直接 import 会把内置类型覆盖掉，函数注解在运行时求值就会报
'module' object is not subscriptable。
"""
from __future__ import annotations

from app.routers import plot as router_plot
from app.routers import tree as router_tree
from app.routers import shrub as router_shrub
from app.routers import lawn as router_lawn
from app.routers import flower as router_flower
from app.routers import pest as router_pest
from app.routers import irrigation as router_irrigation
from app.routers import fertilize as router_fertilize
from app.routers import prune as router_prune
from app.routers import patrol as router_patrol
from app.routers import weed as router_weed
from app.routers import support as router_support
from app.routers import transplant as router_transplant
from app.routers import facility as router_facility
from app.routers import equipment as router_equipment
from app.routers import seedling as router_seedling
from app.routers import waterbody as router_waterbody
from app.routers import code as router_code
from app.routers import complaint as router_complaint
from app.routers import seasonplan as router_seasonplan
from app.routers import lighting as router_lighting

ROUTERS = [router_plot, router_tree, router_shrub, router_lawn, router_flower, router_pest, router_irrigation, router_fertilize, router_prune, router_patrol, router_weed, router_support, router_transplant, router_facility, router_equipment, router_seedling, router_waterbody, router_code, router_complaint, router_seasonplan, router_lighting]
