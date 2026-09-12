"""比赛建包库（纯 Python · 不依赖 Django · 不直接写数据库）。

一句话用法：

    from apps.preparation.builder import CompetitionBuilder

    b = CompetitionBuilder("2026 春季赛")
    steel = b.industry_type(1, "钢铁")
    b.add_field(steel, "所在地", "location", field_type="STRING")
    b.company("甲钢铁", industry_type=steel, region=b.region("东区"))
    b.save("spring-2026.json")

再把产物导入目标比赛：

    python manage.py build_competition spring-2026.json --competition 7 --dry-run

模块划分：
- `core.CompetitionBuilder` —— 构建器主体（每类资源一个登记方法）；
- `types` —— 异常、引用、字段类型枚举、计算图助手；
- `schema` —— 「每类资源有哪些列、哪些必填」的自描述表格，供查字段与生成文档。

设计约束（与 `apps.preparation.archive` 的关系）：
本库只产出归档 JSON，导入仍走 `archive.apply_import`，
因此不新增任何写库路径，现有功能不受影响。
"""
from .core import (
    CompetitionBuilder,
    GENERATOR,
    RESOURCE_LABELS,
    RESOURCE_ORDER,
    SCOPES,
    SCHEMA_VERSION,
)
from .schema import (
    RESOURCE_SCHEMA,
    Column,
    ResourceSchema,
    describe_resource,
    schema_markdown,
    verify_rows,
)
from .types import (
    BuilderError,
    FIELD_TYPES,
    Ref,
    TIMER_FY_END,
    TIMER_FY_START,
    TIMER_TRIGGERS,
    calc_graph,
    calc_node,
)

__all__ = [
    # 主体
    "CompetitionBuilder",
    # 类型与常量
    "BuilderError",
    "Ref",
    "Column",
    "ResourceSchema",
    "RESOURCE_SCHEMA",
    "RESOURCE_ORDER",
    "RESOURCE_LABELS",
    "SCOPES",
    "SCHEMA_VERSION",
    "GENERATOR",
    "FIELD_TYPES",
    "TIMER_TRIGGERS",
    "TIMER_FY_START",
    "TIMER_FY_END",
    # 计算图助手
    "calc_node",
    "calc_graph",
    # 自查 / 文档
    "describe_resource",
    "schema_markdown",
    "verify_rows",
]
