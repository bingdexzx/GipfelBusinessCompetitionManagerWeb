"""科技树模型：对应原 Prisma TechNode / TechPrerequisite。

TechPrerequisite 为 TechNode 自关联多对多的显式中间模型（双向）：
- nodeId → 前置依赖此节点的科技
- prerequisiteNodeId → 本节点依赖的前置科技
"""
from django.db import models


class TechNode(models.Model):
    name = models.CharField(max_length=128)
    description = models.TextField(null=True, blank=True)
    tier = models.IntegerField(default=0)
    research_cost = models.FloatField(default=0)
    competition = models.ForeignKey(
        "competitions.Competition",
        on_delete=models.CASCADE,
        related_name="tech_nodes",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "tech_nodes"
        unique_together = (("competition", "name"),)
        indexes = [models.Index(fields=["competition", "updated_at"])]

    def __str__(self):
        return self.name


class TechPrerequisite(models.Model):
    """科技节点的前置依赖关系（自关联多对多中间表）。"""

    node = models.ForeignKey(
        TechNode,
        on_delete=models.CASCADE,
        related_name="prerequisites",
    )
    prerequisite = models.ForeignKey(
        TechNode,
        on_delete=models.CASCADE,
        related_name="required_by",
    )

    class Meta:
        db_table = "tech_prerequisites"
        unique_together = (("node", "prerequisite"),)
