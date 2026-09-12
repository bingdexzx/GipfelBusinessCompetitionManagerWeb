"""比赛数据快照与实体引用：让「引用一条比赛数据」变成一次可校验的查表。

解决什么问题
------------
引擎里引用一条比赛数据需要 `{"type":"ENTITY","entityType":"MATERIAL",
"entityRef":"<输入项key>","attribute":"price"}`：

1. `entityRef` 必须是**输入项的 key**，所以引用一个固定实体也得先造隐藏输入项；
2. `attribute` 走 `getattr(camel→snake, 0)`——**属性名写错静默为 0**。
   旧的字段表里 `MATERIAL.price` 就是这样一条错声明（原料价格存在 `node_prices`
   里，模型上没有 `price` 字段），走这条路取价恒为 0；
3. 名字是否存在只能到运行期才知道，错了不报错、只是数字不对。

本层的做法
----------
`snapshot(competition_id)` 一次性把比赛数据读成**只读索引**，之后所有引用都在
内存里解析：

    snap = snapshot(7)
    iron = snap.material("铁矿石")     # 不存在 → 立刻报错，并给出最相近的名字
    iron.carbon                        # 属性名对白名单校验，拼错立刻报错

三层保证：
- **存在性**：`snap.material / part / product / vehicle / ...` 查不到就抛错；
- **属性合法性**：属性名取自模型真实字段（`values.ENTITY_ATTRIBUTES`）；
- **口径唯一**：原料单价等「需要多跳解析」的量不暴露为属性，只走 `total_price()`
  这类聚合，避免两条路径给出不同答案。

只读性
------
本模块**只读数据库**：只做 `filter(...).values(...)`，不写、不发广播、不落审计。
体检与建库都可以安全反复调用。
"""
from __future__ import annotations

from typing import Any, Iterable

from .errors import DataError, BuildError, unknown_name
from .values import (
    ENTITY_ATTRIBUTES,
    ENTITY_TYPE_LABEL,
    Value,
    _as_value,
)


class EntityRef:
    """一条比赛数据实体的具名引用（只读）。

    属性访问是**白名单**的：读不到会报错，不会静默为 0。
    """

    __slots__ = ("snapshot", "entity_type", "name", "entity_id")

    def __init__(self, snapshot: "CompetitionSnapshot", entity_type: str, name: str, entity_id: int) -> None:
        self.snapshot = snapshot
        self.entity_type = entity_type
        self.name = name
        self.entity_id = int(entity_id)

    # ---------- 展示 ----------

    @property
    def type_label(self) -> str:
        return ENTITY_TYPE_LABEL.get(self.entity_type, self.entity_type)

    def __repr__(self) -> str:  # pragma: no cover - 调试可读性
        return f"<{self.entity_type} {self.name}#{self.entity_id}>"

    def __str__(self) -> str:
        return self.name

    # ---------- 属性读取 ----------

    @property
    def available_attributes(self) -> tuple[str, ...]:
        return ENTITY_ATTRIBUTES.get(self.entity_type, ())

    def attr(self, attribute: str) -> Value:
        """读取实体属性（需在内置白名单内）。"""
        key = str(attribute or "").strip()
        allowed = self.available_attributes
        if key not in allowed:
            extra_hint = _ATTRIBUTE_HINTS.get((self.entity_type, key), "")
            raise BuildError(
                f"{self.type_label}「{self.name}」没有可读属性「{key}」",
                hint=extra_hint or f"可用属性：{'、'.join(allowed) or '（无）'}",
            )
        return Value(
            {
                "type": "ENTITY",
                "entityType": self.entity_type,
                "entityRef": self.snapshot.pin(self),
                "attribute": key,
            },
            label=f"{self.type_label}「{self.name}」的 {key}",
        )

    def __getattr__(self, item: str) -> Any:
        """支持 `iron.carbon` 这样的短写法（映射到 attr()）。"""
        if item.startswith("_"):
            raise AttributeError(item)
        short = _SHORT_ATTR.get((self.entity_type, item))
        if short:
            return self.attr(short)
        if item in self.available_attributes:
            return self.attr(item)
        raise AttributeError(
            f"{self.type_label}「{self.name}」没有属性「{item}」；可用：{'、'.join(self.available_attributes)}"
        )

    # ---------- 便利属性（按类型提供，读不到直接 AttributeError） ----------

    @property
    def display_name(self) -> Value:
        return self.attr("name")


# ==================== 属性短名 ====================
# 让脚本写得更自然（iron.carbon 而不是 iron.attr("carbonEmissionCoefficient")）
_SHORT_ATTR: dict[tuple[str, str], str] = {
    ("MATERIAL", "carbon"): "carbonEmissionCoefficient",
    ("FUEL", "price"): "pricePerLiter",
    ("VEHICLE", "fuel_per_km"): "fuelConsumptionPerKm",
    ("VEHICLE", "cargo"): "maxCargo",
    ("VEHICLE", "carbon"): "carbonEmission",
    ("WAREHOUSE", "storage"): "capacity",
    ("PRODUCTION_LINE", "labor"): "laborCount",
    ("PRODUCTION_LINE", "capacity"): "maxPerYear",
}

# 属性名与「更该用的方法」的对应提示
_ATTRIBUTE_HINTS: dict[tuple[str, str], str] = {
    ("MATERIAL", "price"): (
        "原料价格按地图节点存储（node_prices），模型上没有 price 字段，"
        "直接读会恒为 0。请用 total_price(原料清单, at=参与方) 取地点价总额，"
        "或 avg_price(原料清单) 取市场均价"
    ),
    ("TECH_NODE", "researchCost"): "单点研发费用请用 tech_research_cost(清单)；研发费用汇总用 research_cost(清单)",
    ("PRODUCTION_LINE", "max_per_year"): "属性名用 camelCase：maxPerYear",
    ("WAREHOUSE", "capacity"): "属性名就是 capacity；每种种类的总存储量请用 warehouse_storage(清单)",
}


# ==================== 比赛数据快照 ====================


class CompetitionSnapshot:
    """一场比赛的数据索引（只读）。

    覆盖引擎 `ENTITY_MODEL_NAMES` 支持的全部 10 类实体，外加产业类型/字段与公司。
    """

    #: 实体类型 → 该类型在「清单类输入项」里的对应输入类型
    INPUT_TYPE_OF: dict[str, str] = {
        "MATERIAL": "materialList",
        "PART": "partList",
        "PRODUCT": "productList",
        "INFRASTRUCTURE": "infrastructureList",
        "FUEL": "fuelList",
        "VEHICLE": "vehicleList",
        "WAREHOUSE": "warehouseList",
    }

    def __init__(self, competition_id: int) -> None:
        self.competition_id = int(competition_id)
        # entity_type -> {name: id}
        self._index: dict[str, dict[str, int]] = {k: {} for k in ENTITY_ATTRIBUTES}
        # 引擎的 entityRef 需要一个「输入项 key」；快照为每个被引用的实体登记一个固定槽位
        self._pinned: dict[int, str] = {}      # entity_id -> 槽位 key
        self._pinned_inputs: list[dict[str, Any]] = []  # 待注入 inputSchema 的输入项
        self._location_by_company: dict[int, str] = {}
        self._company_industry: dict[int, int | None] = {}
        self._industry_name: dict[int, str] = {}
        # 工厂/原料的额外信息（体检用）
        self.material_node_prices: dict[str, dict[int, Any]] = {}
        self.loaded = False

    # ---------- 加载 ----------

    def load(self) -> "CompetitionSnapshot":
        """读取比赛数据（只读）。重复调用是幂等的。"""
        if self.loaded:
            return self
        from apps.competitions.models import Competition

        if not Competition.objects.filter(pk=self.competition_id).exists():
            raise DataError(f"比赛 #{self.competition_id} 不存在")
        cid = self.competition_id

        for entity_type, model_path, name_field in _ENTITY_SOURCES:
            model = _get_model(model_path)
            rows = model.objects.filter(competition_id=cid).values("id", name_field)
            self._index[entity_type] = {
                str(r[name_field]): int(r["id"]) for r in rows if r.get(name_field)
            }

        # 原料地点价（体检用：判断某节点是否有报价）
        from apps.materials.models import Material

        for row in Material.objects.filter(competition_id=cid).values("name", "node_prices"):
            self.material_node_prices[str(row["name"])] = _parse_node_prices(row["node_prices"])

        self._load_companies()
        self.loaded = True
        return self

    def _load_companies(self) -> None:
        """公司 → 产业类型、所在地（引擎的 `location` 字段口径）。"""
        from apps.companies.models import Company, CompanyFieldValue
        from apps.industry_types.models import IndustryField, IndustryType

        cid = self.competition_id
        self._industry_name = {
            int(r["id"]): str(r["name"]) for r in IndustryType.objects.all().values("id", "name")
        }
        for row in Company.objects.filter(competition_id=cid).values("id", "industry_type_id"):
            self._company_industry[int(row["id"])] = row["industry_type_id"]

        location_field_ids = set(
            IndustryField.objects.filter(field_key="location").values_list("id", flat=True)
        )
        if not location_field_ids:
            return
        for row in CompanyFieldValue.objects.filter(
            company__competition_id=cid, industry_field_id__in=location_field_ids
        ).values("company_id", "value"):
            self._location_by_company[int(row["company_id"])] = _unquote(row["value"])

    # ---------- 实体解析 ----------

    def _resolve(self, entity_type: str, name: Any) -> EntityRef:
        if not self.loaded:
            self.load()
        key = str(name or "").strip()
        if not key:
            raise BuildError(f"{ENTITY_TYPE_LABEL.get(entity_type, entity_type)}名称不能为空")
        found = self._index.get(entity_type, {}).get(key)
        if found is None:
            raise unknown_name(
                ENTITY_TYPE_LABEL.get(entity_type, entity_type) + "（本场比赛）",
                key,
                self._index.get(entity_type, {}).keys(),
            )
        return EntityRef(self, entity_type, key, found)

    def material(self, name: Any) -> EntityRef:
        """原料引用。"""
        return self._resolve("MATERIAL", name)

    def part(self, name: Any) -> EntityRef:
        """零件引用。"""
        return self._resolve("PART", name)

    def product(self, name: Any) -> EntityRef:
        """成品引用。"""
        return self._resolve("PRODUCT", name)

    def tech(self, name: Any) -> EntityRef:
        """科技节点引用。"""
        return self._resolve("TECH_NODE", name)

    def warehouse(self, name: Any) -> EntityRef:
        """仓库引用。"""
        return self._resolve("WAREHOUSE", name)

    def production_line(self, name: Any) -> EntityRef:
        """生产线引用。"""
        return self._resolve("PRODUCTION_LINE", name)

    def fuel(self, name: Any) -> EntityRef:
        """燃料引用。"""
        return self._resolve("FUEL", name)

    def vehicle(self, name: Any) -> EntityRef:
        """载具引用。"""
        return self._resolve("VEHICLE", name)

    def infrastructure(self, name: Any) -> EntityRef:
        """基建引用。"""
        return self._resolve("INFRASTRUCTURE", name)

    def map_node(self, name: Any) -> EntityRef:
        """地图节点引用。"""
        return self._resolve("MAP_NODE", name)

    def entity(self, entity_type: str, name: Any) -> EntityRef:
        """通用入口：按引擎实体类型名解析。"""
        key = str(entity_type or "").strip().upper()
        if key not in ENTITY_ATTRIBUTES:
            raise BuildError(
                f"未知实体类型：{entity_type}",
                hint=f"可用：{'、'.join(ENTITY_ATTRIBUTES)}",
            )
        return self._resolve(key, name)

    def names(self, entity_type: str) -> list[str]:
        """某类实体的全部名字（体检报告用）。"""
        if not self.loaded:
            self.load()
        return sorted(self._index.get(str(entity_type).upper(), {}))

    # ---------- 公司 / 产业 ----------

    def company_industry_type(self, company_id: int) -> int | None:
        """公司所属产业类型 id（未设置返回 None）。"""
        if not self.loaded:
            self.load()
        return self._company_industry.get(int(company_id))

    def company_location(self, company_id: int) -> str | None:
        """公司所在地（`location` 字段的值，即地图节点名）。

        未填 / 填了空串都返回 None——引擎的 `resolve_party_location_node_id` 对空串
        与缺失一视同仁（都会回退市场均价），这里保持同一口径，
        避免体检拿到空串却以为「有地点」。
        """
        if not self.loaded:
            self.load()
        value = self._location_by_company.get(int(company_id))
        text = (value or "").strip()
        return text or None

    def industry_name(self, industry_type_id: Any) -> str:
        if not self.loaded:
            self.load()
        try:
            return self._industry_name.get(int(industry_type_id), f"#{industry_type_id}")
        except (TypeError, ValueError):
            return f"#{industry_type_id}"

    def industry_field_types(self) -> dict[int, dict[str, str]]:
        """`{产业类型 id: {fieldKey: fieldType}}`（静态体检用，只读）。"""
        from apps.industry_types.models import IndustryField

        out: dict[int, dict[str, str]] = {}
        for row in IndustryField.objects.all().values("industry_type_id", "field_key", "field_type"):
            tid = int(row["industry_type_id"])
            out.setdefault(tid, {})[str(row["field_key"])] = str(row["field_type"] or "STRING")
        return out

    def industry_field_keys(self) -> dict[int, set[str]]:
        """`{产业类型 id: {fieldKey}}`。"""
        return {tid: set(fields) for tid, fields in self.industry_field_types().items()}

    def all_industry_field_keys(self) -> set[str]:
        """库中**所有**产业字段 key 的并集（体检用来发现「哪个产业都没有这个字段」）。"""
        keys: set[str] = set()
        for fields in self.industry_field_types().values():
            keys.update(fields)
        return keys

    def industry_names(self) -> dict[int, str]:
        """`{产业类型 id: 名称}`（报错信息里用中文名而不是 #id）。"""
        if not self.loaded:
            self.load()
        return dict(self._industry_name)

    def companies(self) -> list[dict[str, Any]]:
        """本场比赛的公司列表：`[{id, name, industryTypeId, location}]`。

        试算与体检用它枚举真实公司，避免把「一家公司顶所有参与方」当成验证。
        """
        from apps.companies.models import Company

        if not self.loaded:
            self.load()
        rows = (
            Company.objects.filter(competition_id=self.competition_id)
            .order_by("id")
            .values("id", "name", "industry_type_id")
        )
        return [
            {
                "id": int(r["id"]),
                "name": str(r["name"]),
                "industryTypeId": r["industry_type_id"],
                "location": self._location_by_company.get(int(r["id"])),
            }
            for r in rows
        ]

    def material_price_at(self, material_name: str, node_name: str | None) -> Any | None:
        """某原料在某地点的报价；该地点没有报价时返回 None（体检据此提示回退均价）。"""
        if not self.loaded:
            self.load()
        prices = self.material_node_prices.get(str(material_name))
        if not prices or not node_name:
            return None
        node_id = self._index.get("MAP_NODE", {}).get(str(node_name))
        if node_id is None:
            return None
        return prices.get(node_id)

    # ---------- 实体槽位（把「固定实体」变成引擎能读的 ENTITY 值源） ----------

    def pin(self, ref: EntityRef) -> str:
        """为一个实体登记固定输入槽位，返回引擎 `entityRef` 需要的输入项 key。

        这是「消灭隐藏输入项」的实现：使用者不再需要手写这个输入项，
        快照按需生成，并在 `drain_pinned_inputs()` 时由构建器注入 inputSchema。
        槽位带 `hidden` 标记，前端表单据此可以不渲染。
        """
        slot = self._pinned.get(ref.entity_id)
        if slot:
            return slot
        slot = f"__ref_{ref.entity_type.lower()}_{ref.entity_id}"
        self._pinned[ref.entity_id] = slot
        self._pinned_inputs.append(
            {
                "key": slot,
                "label": f"{ref.type_label}：{ref.name}",
                "type": "ENTITY",
                "entityType": ref.entity_type,
                "required": False,
                "default": ref.entity_id,
                "hidden": True,
            }
        )
        return slot

    def drain_pinned_inputs(self) -> list[dict[str, Any]]:
        """取出并清空待注入的槽位输入项（构建器在编译前调用）。"""
        out = list(self._pinned_inputs)
        self._pinned_inputs.clear()
        return out

    # ---------- 一致性自检 ----------

    def assert_engine_parity(self) -> None:
        """校验本库的属性白名单与引擎的实体表一致（导入期 fail-fast）。

        - 白名单里的每个实体类型都必须在 `engine.ENTITY_MODEL_NAMES` 里；
        - 白名单里的每个属性都必须能映射到模型上的真实标量字段。
          这一条正是「`MATERIAL.price` 静默为 0」那类问题的防线。
        """
        from apps.contracts.engine import ENTITY_MODEL_NAMES, _camel_to_snake

        problems: list[str] = []
        for entity_type, attrs in ENTITY_ATTRIBUTES.items():
            model_path = ENTITY_MODEL_NAMES.get(entity_type)
            if not model_path:
                problems.append(f"实体类型 {entity_type} 不在 engine.ENTITY_MODEL_NAMES 里")
                continue
            model = _get_model(model_path)
            scalar_fields = {
                f.name for f in model._meta.get_fields() if not f.is_relation and f.name not in ("id", "created_at", "updated_at")
            }
            for attr in attrs:
                snake = _camel_to_snake(attr)
                if snake not in scalar_fields:
                    problems.append(
                        f"{entity_type}.{attr} → 模型字段 {snake} 不存在（可用：{sorted(scalar_fields)}）"
                    )
        if problems:
            raise DataError(
                "实体属性白名单与模型不一致（本库缺陷，请修正 ENTITY_ATTRIBUTES）：\n  - "
                + "\n  - ".join(problems)
            )


# ==================== 数据来源表 ====================

_ENTITY_SOURCES: tuple[tuple[str, str, str], ...] = (
    ("MATERIAL", "materials.Material", "name"),
    ("PART", "parts.Part", "name"),
    ("PRODUCT", "products.Product", "name"),
    ("TECH_NODE", "tech_tree.TechNode", "name"),
    ("WAREHOUSE", "warehouses.Warehouse", "name"),
    ("PRODUCTION_LINE", "production_lines.ProductionLine", "name"),
    ("FUEL", "fuels.Fuel", "name"),
    ("VEHICLE", "vehicles.Vehicle", "name"),
    ("INFRASTRUCTURE", "infrastructures.Infrastructure", "name"),
    ("MAP_NODE", "maps.MapNode", "name"),
)


def _get_model(path: str):
    from django.apps import apps as django_apps

    return django_apps.get_model(path)


def _parse_node_prices(raw: Any) -> dict[int, Any]:
    import json

    if isinstance(raw, dict):
        data = raw
    elif isinstance(raw, str) and raw.strip():
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            return {}
    else:
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[int, Any] = {}
    for k, v in data.items():
        try:
            out[int(k)] = v
        except (TypeError, ValueError):
            continue
    return out


def _unquote(raw: Any) -> str:
    """字段值可能是 `"东区港"`（带引号的 JSON 字符串）也可能是裸文本，统一取文本。"""
    import json

    if raw is None:
        return ""
    text = str(raw)
    if text.startswith('"') and text.endswith('"') and len(text) >= 2:
        try:
            parsed = json.loads(text)
            if isinstance(parsed, str):
                return parsed
        except (ValueError, TypeError):
            pass
    return text


def snapshot(competition_id: int) -> CompetitionSnapshot:
    """读取并返回一场比赛的数据快照（只读，立即加载）。"""
    snap = CompetitionSnapshot(competition_id)
    snap.load()
    snap.assert_engine_parity()
    return snap
