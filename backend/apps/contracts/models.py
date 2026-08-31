"""合同模型：对应原 Prisma ContractType / Contract / ContractFieldEffect。

- ContractType 为全局模板（无 competitionId），存储合同类型 DSL（partyRoles /
  inputSchema / effects / conditions / graph 均为 JSON 文本）。
- Contract 为比赛级合同实例，状态机 DRAFT/PENDING_EXEC/EXECUTED/TERMINATED。
- ContractFieldEffect 为合同落账的字段改写不可变审计记录，供删合同时按
  executedAt 重放复原。company_id / industry_field_id 为纯整型列（无外键，
  避免级联删除影响），与原 Prisma 一致。
"""
from django.db import models


class ContractType(models.Model):
    """合同类型模板（全局，不绑定比赛）。"""

    key = models.CharField(max_length=128, unique=True)
    name = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)
    # 参与方数一律由 partyRoles 推导（= 参与方节点数）
    party_count = models.IntegerField(default=2)
    # JSON 文本：[{role,label,selectable?,isHost?}]
    party_roles = models.TextField(default="[]")
    # JSON 文本：[{key,label,type,required?,default?,enum?,min?,max?}]
    input_schema = models.TextField(default="[]")
    # JSON 文本：效果定义数组（见合同引擎）
    effects = models.TextField(default="[]")
    # JSON 文本：前置检查数组
    conditions = models.TextField(default="[]")
    # JSON 文本：可视化图结构（节点+连线+布局），可空
    graph = models.TextField(null=True, blank=True)
    schema_version = models.IntegerField(default=1)
    enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "contract_types"

    def __str__(self):
        return self.name


class Contract(models.Model):
    """合同实例（比赛级）。删除比赛时级联删除。"""

    STATUS_CHOICES = [
        ("DRAFT", "DRAFT"),
        ("PENDING_EXEC", "PENDING_EXEC"),
        ("EXECUTED", "EXECUTED"),
        ("TERMINATED", "TERMINATED"),
    ]

    competition = models.ForeignKey(
        "competitions.Competition",
        on_delete=models.CASCADE,
        related_name="contracts",
    )
    # RESTRICT：有合同引用的合同类型不允许直接删除（由视图层显式阻断）
    contract_type = models.ForeignKey(
        ContractType,
        on_delete=models.RESTRICT,
        related_name="contracts",
    )
    name = models.CharField(max_length=255)
    status = models.CharField(max_length=16, default="DRAFT", choices=STATUS_CHOICES)
    # JSON 文本：[{role,companyId,isHost?,contractNumber?}]
    parties = models.TextField(default="[]")
    # JSON 文本：已填写的输入参数
    inputs = models.TextField(default="{}")
    execution_log = models.TextField(null=True, blank=True)
    execution_result = models.TextField(null=True, blank=True)
    signed_at = models.DateTimeField(null=True, blank=True)
    executed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "contracts"
        indexes = [models.Index(fields=["competition", "updated_at"])]

    def __str__(self):
        return self.name


class ContractFieldEffect(models.Model):
    """合同字段落账记录（不可变审计行）。

    供合同删除时按 executedAt 顺序重放复原字段值。contract 级联删除；
    company_id / industry_field_id 为纯整型列（无外键，与原 Prisma 一致）。
    """

    OP_CHOICES = [("ADD", "ADD"), ("SUB", "SUB"), ("SET", "SET")]

    contract = models.ForeignKey(
        Contract,
        on_delete=models.CASCADE,
        related_name="field_effects",
    )
    company_id = models.IntegerField()
    industry_field_id = models.IntegerField()
    field_key = models.CharField(max_length=128)
    field_name = models.CharField(max_length=255)
    op = models.CharField(max_length=8, choices=OP_CHOICES)
    value_raw = models.TextField()
    before_raw = models.TextField()
    after_raw = models.TextField()
    # 仅创建时间，无 updated_at（不可变记录）
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "contract_field_effects"
        indexes = [
            models.Index(fields=["contract"]),
            models.Index(fields=["company_id", "industry_field_id"]),
        ]
