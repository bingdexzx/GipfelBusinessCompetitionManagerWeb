"""比赛准备事项清单（目录定义）。

本模块只描述「比赛开始前需要准备什么」，不触碰数据库：
每个事项记录所属分组、称谓、是否需要先准备、入口路由与操作提示。
实际统计与体检由 apps.preparation.plan 完成。

新增准备事项时，只需在 _ITEMS 里追加一条 PrepItem，并在 plan.collect()
的 _COLLECTORS 里补上同名收集函数；前端无需改动即可自动展示与导出。
"""
from __future__ import annotations

import dataclasses
from typing import Any


@dataclasses.dataclass(frozen=True)
class PrepItem:
    """一条比赛准备事项的元信息。"""

    key: str
    category_key: str
    title: str
    # 该事项是否属于「比赛开始前必须完成」
    required: bool
    # 为什么需要它 / 它对比赛运行的影响
    description: str
    # 在前端哪里做
    route: str
    # 操作提示（分步）
    steps: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "categoryKey": self.category_key,
            "title": self.title,
            "required": self.required,
            "description": self.description,
            "route": self.route,
            "steps": list(self.steps),
        }


@dataclasses.dataclass(frozen=True)
class PrepCategory:
    """准备事项分组。"""

    key: str
    title: str
    description: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "description": self.description,
        }


# ==================== 分组 ====================

CATEGORIES: tuple[PrepCategory, ...] = (
    PrepCategory(
        key="competition",
        title="① 比赛基础",
        description="比赛的建立与时间轴。后续所有数据都挂在这场比赛下面，删比赛会级联删除全部子数据。",
    ),
    PrepCategory(
        key="industry",
        title="② 行业口径",
        description="产业类型与产业字段（全局库，各比赛共用），决定公司有哪些字段、哪些字段自动计算、哪些字段在财年切换时被定时器改写。",
    ),
    PrepCategory(
        key="company",
        title="③ 参赛主体",
        description="公司、所属产业类型、所在区域与初始字段值。公司是合同、股票、区域总览的挂载主体。",
    ),
    PrepCategory(
        key="supply",
        title="④ 物资与产能",
        description="原料、零件、产品、生产线、基建、载具、仓库与燃料，构成生产链与采购链的基础数据。",
    ),
    PrepCategory(
        key="geo",
        title="⑤ 地理与物流",
        description="区域、地图节点与连线，是原料产地、公司所在地、运输路程与路径类型的依据。",
    ),
    PrepCategory(
        key="tech",
        title="⑥ 科技与需求",
        description="科技树节点与前置依赖、消费者需求，决定研发与订单来源。",
    ),
    PrepCategory(
        key="market",
        title="⑦ 市场与规则",
        description="股票、资金账户、区域总览卡片、合同类型与合同实例、比赛内消息。",
    ),
    PrepCategory(
        key="access",
        title="⑧ 账号与权限",
        description="参赛账号、角色与公司范围。没有公司范围的玩家账号看不到也不可操作自己的公司。",
    ),
    PrepCategory(
        key="acceptance",
        title="⑨ 开赛前验收",
        description="所有准备完成后逐项确认，确认通过即可开始财年。",
    ),
)

CATEGORY_BY_KEY: dict[str, PrepCategory] = {c.key: c for c in CATEGORIES}


# ==================== 准备事项（按准备顺序排列） ====================

_ITEMS: tuple[PrepItem, ...] = (
    # ---------- ① 比赛基础 ----------
    PrepItem(
        key="competition.base",
        category_key="competition",
        title="创建比赛并启用",
        required=True,
        description="比赛是租户根：公司、地图、物资、股票、合同全部挂在比赛下。状态为 ACTIVE 才可正常使用。",
        route="/competitions",
        steps=(
            "进入「比赛管理」，点「+ 新建比赛」，填写比赛名称（全局唯一，不可与已有比赛重名）。",
            "确认该比赛状态显示为「进行中」（ACTIVE），点行内「选择」把它设为当前比赛。",
            "如已有历史比赛，删比赛会级联删除其全部子数据，务必确认不是在复用旧比赛。",
        ),
    ),
    PrepItem(
        key="competition.map_background",
        category_key="competition",
        title="上传地图背景图",
        required=False,
        description="地图画布底图，用于地图节点定位。不配置时地图仍可用，但节点只能靠坐标辨认。",
        route="/maps",
        steps=(
            "进入「地图管理」，上传背景图。",
            "背景图会随比赛保存，导出归档时只记录图片地址与尺寸，不导出图片本体。",
        ),
    ),
    PrepItem(
        key="competition.fiscal_year",
        category_key="competition",
        title="建立财年（时间轴）",
        required=True,
        description="财年是比赛的回合/年度时间轴。新建财年或把财年从非 ACTIVE 改为 ACTIVE 会触发 FY_START 定时器，改写启用了该时机的产业字段。",
        route="/competitions",
        steps=(
            "在「比赛管理」点「选择」选中比赛，下方「财年管理」面板会列出该比赛的财年。",
            "点「开始新财年」创建财年（系统按已有最大年份 +1 推算），新财年即为「进行中」。",
            "新建财年这一步会立刻触发 FY_START 定时器，请先完成②中的定时器字段配置再开始财年。",
            "财年一旦「结束财年」不可撤销，开赛前不要误点。",
        ),
    ),
    PrepItem(
        key="competition.stock_config",
        category_key="competition",
        title="确认股票系统参数",
        required=False,
        description="比赛的股票引擎参数（涨跌幅限幅、做市商深度与点差、自然波动回归强度等）。未配置时使用系统默认配置。",
        route="/stock-management",
        steps=(
            "不配置即沿用默认参数，一般无需改动。",
            "如需调参，请保持：单轮限幅 limitPct ≥ 单轮最大波动 maxMovePct；做市商最小数量 ≤ 最大数量。",
        ),
    ),
    # ---------- ② 行业口径 ----------
    PrepItem(
        key="industry.types",
        category_key="industry",
        title="产业类型",
        required=True,
        description="全局资源（各比赛共用）。公司必须归属于某个产业类型，合同效果也按产业类型解析字段。",
        route="/industry-types",
        steps=(
            "进入「产业类型管理」，为本次比赛涉及的每个行业建一条产业类型。",
            "产业类型 code 全局唯一，复用历史比赛时不要重复建同名类型。",
        ),
    ),
    PrepItem(
        key="industry.fields",
        category_key="industry",
        title="产业字段（含计算字段与财年定时器）",
        required=True,
        description="定义公司要填报的字段。isCalculated 字段由产业计算图级联重算；timerEnabled 字段在财年切换时被自动写入。这两个开关是开赛前最容易漏配的地方。",
        route="/industry-types",
        steps=(
            "每个产业类型至少保留「所在地」字段（location），地图与运费逻辑依赖它。",
            "把需要自动推导的字段设为「计算字段」并配置产业计算图，否则它永远是初始值。",
            "需要财年切换自动改写的字段，设置定时器触发时机（财年开始/结束）与设定值，注意与「计算字段」互斥。",
            "字段 fieldKey 是合同、图表、股票绑定的依据，开赛后改名会导致既有引用失效。",
        ),
    ),
    # ---------- ③ 参赛主体 ----------
    PrepItem(
        key="company.companies",
        category_key="company",
        title="公司与产业类型归属",
        required=True,
        description="参赛主体。公司必须绑定产业类型（决定字段集合）与区域（决定区域总览归属），否则字段填报、合同与区域卡片都会缺位。",
        route="/companies",
        steps=(
            "进入「公司管理」，为每支参赛队伍建一家公司，并选择所属产业类型。",
            "为公司选择所在区域，区域总览按区域聚合公司卡片。",
            "公司名在同一比赛内建议唯一，便于玩家与合同参与方辨认。",
        ),
    ),
    PrepItem(
        key="company.field_values",
        category_key="company",
        title="公司字段初始值",
        required=True,
        description="开赛时各公司的起始数值。未填写的字段在引擎侧按字段类型取空值（数字 0 / 文本空 / 布尔否），可能导致开局数值异常。",
        route="/companies",
        steps=(
            "逐家公司填写全部「非计算字段」的初始值；计算字段无需手填（由计算图推导）。",
            "填写冲突时后端用乐观锁 version 拦截并返回 409，前端刷新后重试即可。",
            "推荐顺序：先填全部基础字段，再改计算字段的下游依赖，最后核对计算结果。",
        ),
    ),
    # ---------- ④ 物资与产能 ----------
    PrepItem(
        key="supply.materials",
        category_key="supply",
        title="原料",
        required=True,
        description="生产链起点。原料的产地与价格参与「原料总价格」「碳排放合计」等合同聚合端点，也决定按公司所在地取地点价。",
        route="/materials",
        steps=(
            "录入原料名称；名称是合同清单、零件配比、库存字典的键，开赛后改名会断链。",
            "填写产地（与地图节点对应）与碳排放系数。",
            "需要地点差异定价的原料，配置各地图节点的地点价（未配置则回退基础价）。",
        ),
    ),
    PrepItem(
        key="supply.parts",
        category_key="supply",
        title="零件与配比、科技需求",
        required=True,
        description="零件的原料配比决定「所需原料」聚合结果；科技需求决定研发前置校验。配比缺失会让生产计算得到空字典。",
        route="/parts",
        steps=(
            "录入零件，并为每个零件配置原料配比（数量系数）。",
            "如该零件需要研发前置，勾选对应科技节点。",
        ),
    ),
    PrepItem(
        key="supply.products",
        category_key="supply",
        title="产品与零件配比、科技需求",
        required=True,
        description="产品是消费者需求与销售的对象；产品→零件配比决定「需要的零件」聚合结果。",
        route="/products",
        steps=(
            "录入产品，并配置所需零件及数量系数。",
            "如需研发前置，勾选对应科技节点。",
            "产品名称需与④需求中的产品类型对应，否则需求会指向不存在的产品。",
        ),
    ),
    PrepItem(
        key="supply.production_lines",
        category_key="supply",
        title="生产线",
        required=True,
        description="产能数据，供玩家购置与产能核算使用。",
        route="/production-lines",
        steps=("录入生产线名称与单价，覆盖本次比赛可购买的全部产能档位。",),
    ),
    PrepItem(
        key="supply.infrastructures",
        category_key="supply",
        title="基建",
        required=True,
        description="基建的价格、占地与各项加成，是合同「基建总价格 / 总占地面积 / 各项加成」聚合端点的数据来源。",
        route="/infrastructures",
        steps=(
            "录入基建名称、占地面积、单价与启用费用。",
            "填写就业率、人口、高素质人口、幸福度、人均收益、减碳等加成系数。",
        ),
    ),
    PrepItem(
        key="supply.vehicles",
        category_key="supply",
        title="载具与可通行路径类型",
        required=True,
        description="载具的载货量、每公里油耗与碳排参与运输成本计算；可通行路径类型决定它能走哪些边。载具必须绑定燃料。",
        route="/vehicles",
        steps=(
            "先确保燃料与路径类型已录入，再建载具。",
            "填写载货量、每公里油耗、碳排放系数与单价。",
            "为该载具勾选可通行的路径类型，未勾选时运输路径校验会失败。",
        ),
    ),
    PrepItem(
        key="supply.warehouses",
        category_key="supply",
        title="仓库",
        required=True,
        description="仓库按种类（原料/零件/产品/燃料）提供存储容量，合同「每种种类的仓库总存储量」按此聚合。",
        route="/warehouses",
        steps=("录入仓库名称、种类、容量与单价。四种种类建议都有覆盖，否则对应物资无处存放。",),
    ),
    PrepItem(
        key="supply.fuels",
        category_key="supply",
        title="燃料",
        required=True,
        description="燃料单价参与运费计算，且被载具以外键 PROTECT 引用（有载具引用时不能删除）。",
        route="/fuels",
        steps=("录入燃料名称与每升单价。", "确认每种载具都能绑定到一种燃料。"),
    ),
    # ---------- ⑤ 地理与物流 ----------
    PrepItem(
        key="geo.regions",
        category_key="geo",
        title="区域",
        required=True,
        description="区域用于聚合公司与区域总览卡片，也是消费者需求的归属维度。",
        route="/region-overview",
        steps=("建立本次比赛的全部区域，并确保每家公司都归属到某个区域。",),
    ),
    PrepItem(
        key="geo.map_node_types",
        category_key="geo",
        title="地图节点类型",
        required=True,
        description="节点分类（如城市/港口），用于地图着色与快速筛选。",
        route="/maps",
        steps=("建立节点类型并设置颜色，供地图节点引用。",),
    ),
    PrepItem(
        key="geo.path_types",
        category_key="geo",
        title="路径类型",
        required=True,
        description="连线类型（如公路/铁路/航线）。载具按路径类型决定可通行性，合同「存在的路径类型」输出该列表。",
        route="/maps",
        steps=("建立路径类型，供地图连线与载具可通行性引用。",),
    ),
    PrepItem(
        key="geo.map_nodes",
        category_key="geo",
        title="地图节点",
        required=True,
        description="所有地理引用的落点：原料产地、公司所在地、运输起讫点。孤立节点（没有任何连线）不可达，会导致路程计算失败。",
        route="/maps",
        steps=(
            "在画布上放置节点，填写名称、所属区域与节点类型。",
            "节点名称是合同「目的地/起始节点名」等字段的展示依据。",
        ),
    ),
    PrepItem(
        key="geo.map_edges",
        category_key="geo",
        title="地图连线（含距离与路径类型）",
        required=True,
        description="连线定义可达性；距离与路径类型是运费、路程与载具通行性的输入。",
        route="/maps",
        steps=(
            "连接节点并填写距离与路径类型。",
            "确认没有孤立节点（每个节点至少一条连线）。",
            "同一对节点只允许一条连线（唯一约束），重复连线需先删旧边。",
        ),
    ),
    # ---------- ⑥ 科技与需求 ----------
    PrepItem(
        key="tech.nodes",
        category_key="tech",
        title="科技树节点",
        required=True,
        description="研发对象。研发费用与层级影响研发节奏，也是合同「研发费用」「前置节点」的数据来源。",
        route="/tech-tree",
        steps=("按层级录入科技节点，填写研发费用与说明。",),
    ),
    PrepItem(
        key="tech.prerequisites",
        category_key="tech",
        title="科技前置依赖",
        required=True,
        description="节点间的前置关系。前置成环会让研发永远无法解锁，开赛前必须排查。",
        route="/tech-tree",
        steps=(
            "为每个节点配置其前置节点。",
            "检查是否存在环路（A 依赖 B、B 又依赖 A）；本页体检会自动提示。",
        ),
    ),
    PrepItem(
        key="demand.consumer_demands",
        category_key="tech",
        title="消费者需求",
        required=True,
        description="各区域对产品的需求量，是订单与销售的来源。需求指向的产品必须存在，否则玩家无法交付。",
        route="/region-overview",
        steps=(
            "按区域 × 产品录入需求量。",
            "确认需求的产品已在④产品中录入，且需求量不为 0。",
        ),
    ),
    # ---------- ⑦ 市场与规则 ----------
    PrepItem(
        key="market.stocks",
        category_key="market",
        title="股票与上市绑定",
        required=False,
        description="股票的基础信息（股本、净利润、初始价）与碳排/幸福度联动绑定。绑定引用了区域总览卡片，卡片缺失会导致行情指标取不到值。",
        route="/stock-management",
        steps=(
            "录入股票代码、名称、总股本、初始净利润与初始价格。",
            "如需碳排/幸福度联动，先建好区域总览卡片，再选择卡片引用。",
            "可关联到公司，使股票与公司经营数据联动。",
        ),
    ),
    PrepItem(
        key="market.funds_accounts",
        category_key="market",
        title="资金账户",
        required=False,
        description="玩家下单的资金来源。账户按比赛隔离，且与持有股票、订单强关联。",
        route="/stock-management",
        steps=(
            "为每家公司建立资金账户，owner 类型选公司。",
            "如需与公司字段联动（现金跟随产业字段），绑定对应产业字段。",
            "账户初始现金请核对，撮合后余额会随成交变化，开赛前是可自由设定的最后时机。",
        ),
    ),
    PrepItem(
        key="market.overview_cards",
        category_key="market",
        title="区域总览卡片",
        required=False,
        description="区域页面上展示的公司字段卡片。股票碳排/幸福度绑定引用卡片 id，因此卡片必须在开赛前建好。",
        route="/region-overview",
        steps=(
            "在每个区域页配置卡片，选择公司 + 产业字段。",
            "卡片的 id 会被股票的指标绑定引用，删除卡片会让股票绑定失效。",
        ),
    ),
    PrepItem(
        key="contract.types",
        category_key="market",
        title="合同类型（全局库）",
        required=False,
        description="全局资源（各比赛共用）。合同类型决定可签哪些合同、需要哪些参与方与字段、执行时如何改写公司字段。",
        route="/contract-types",
        steps=(
            "在「合同类型管理」用「可视化新建」搭建合同类型，或用「简单新建」做基础版。",
            "保存后务必点「试算」验证效果与检查是否按预期生效。",
            "合同类型为全局资源，导出归档时会一并记录，便于复用到其他比赛。",
        ),
    ),
    PrepItem(
        key="contract.instances",
        category_key="market",
        title="合同实例（本比赛预设合同）",
        required=False,
        description="比赛级合同实例。开赛前预置好合同可让玩家直接进入履约环节，无需管理员现场创建。",
        route="/contracts",
        steps=(
            "在「合同管理」点「+ 新建」，选择合同类型并为每个参与方角色选择公司。",
            "填写合同数据与合同编号；全部非主办方编号齐备后合同自动进入「待执行」。",
            "执行会立刻改写公司字段并落账，若只想预置，请保持「草稿」状态。",
        ),
    ),
    PrepItem(
        key="market.messages",
        category_key="market",
        title="比赛内消息",
        required=False,
        description="面向玩家发布的比赛内通知（规则说明、开局公告、阶段提醒）。",
        route="/messages",
        steps=("在「消息中心」撰写消息并选择接收范围（全体或指定账号）。",),
    ),
    # ---------- ⑧ 账号与权限 ----------
    PrepItem(
        key="access.users",
        category_key="access",
        title="参赛账号与角色",
        required=True,
        description="三类角色：SUPER_ADMIN（超管，全局）、COMPETITION_ADMIN（比赛管理员）、PLAYER（选手）。玩家账号必须归属到本比赛。",
        route="/accounts",
        steps=(
            "为每位选手建 PLAYER 账号，并选择所属比赛。",
            "必要时为本场比赛配一名 COMPETITION_ADMIN，负责日常运营（默认含合同审核/执行/新建权）。",
            "首次登录会强制改密，建议开赛前把账号与初始密码发给选手并让其自行改密。",
        ),
    ),
    PrepItem(
        key="access.scopes",
        category_key="access",
        title="账号公司范围（数据可见范围）",
        required=True,
        description="四套范围：公司管理范围 companyScopes、查看范围 viewCompanyScopes、合同查看范围 contractViewCompanyScopes、股票范围 stockCompanyScopes。范围为空会导致该账号看不到任何数据。",
        route="/accounts",
        steps=(
            "为玩家账号配置所属公司的范围，至少包含自己的公司。",
            "公司范围同时决定合同执行权：合同最后一个非主办方参与方公司必须在该账号范围内才可执行。",
            "范围为空时股票、合同、公司列表都会是空的，属于最常见的「登录后什么都看不到」原因。",
        ),
    ),
    # ---------- ⑨ 开赛前验收 ----------
    PrepItem(
        key="acceptance.data_check",
        category_key="acceptance",
        title="体检结果清零",
        required=True,
        description="本页对各准备事项做的自动体检：字段未配计算图、地图孤立节点、科技前置成环、需求指向空产品等问题都在这里汇总。",
        route="/settings",
        steps=(
            "逐条处理带「提醒」的事项，直到全部事项状态为「就绪」。",
            "导出本页报告并存档，作为本场比赛准备完成的凭证。",
        ),
    ),
    PrepItem(
        key="acceptance.api_smoke",
        category_key="acceptance",
        title="接口冒烟自检",
        required=True,
        description="确认迁移后功能可用：health → login → 改密 → me → competitions CRUD → maps/full → stocks/industry-types 全部返回 200。",
        route="终端",
        steps=(
            "后端目录执行 python manage.py check，确认无系统检查错误。",
            "执行 python manage.py showmigrations，确认没有未应用的迁移。",
            "前端目录执行 npm run typecheck，确认类型检查通过。",
        ),
    ),
    PrepItem(
        key="acceptance.backup",
        category_key="acceptance",
        title="备份与归档",
        required=True,
        description="把本场比赛的准备数据导出归档：既是复用模板，也是出问题时的对照基线。",
        route="/settings",
        steps=(
            "点「导出 Markdown」保存人类可读的准备报告（含全部明细清单）。",
            "点「导出 JSON」保存机器可读快照，便于比对两次准备的差异。",
            "开赛前对数据库做一次备份（SQLite 直接复制 db.sqlite3，或 pg_dump）。",
        ),
    ),
)

ITEM_BY_KEY: dict[str, PrepItem] = {i.key: i for i in _ITEMS}

# 导出顺序：按 _ITEMS 声明顺序（已按准备先后排列）
ALL_ITEMS: tuple[PrepItem, ...] = _ITEMS


def items_of(category_key: str) -> tuple[PrepItem, ...]:
    """取某分组下的全部准备事项。"""
    return tuple(i for i in _ITEMS if i.category_key == category_key)


def catalog_as_dict() -> dict[str, Any]:
    """目录结构（不含统计数据），供前端渲染分组标题与说明。"""
    return {
        "categories": [c.to_dict() for c in CATEGORIES],
        "items": [i.to_dict() for i in _ITEMS],
    }
