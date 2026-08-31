"""零件与配比/科技需求模型：对应原 Prisma Part / PartMaterial / PartTechRequirement。

PartMaterial / PartTechRequirement 为复合主键关联表（Prisma @@id）。
Django 不原生支持复合主键，沿用本仓库 FiscalYear 的既定约定：
显式自增 id 作主键 + unique_together 表达复合唯一约束。
"""
from django.db import models


class Part(models.Model):
    """零件主数据。删除比赛时级联删除。"""

    name = models.CharField(max_length=128)
    competition = models.ForeignKey(
        "competitions.Competition",
        on_delete=models.CASCADE,
        related_name="parts",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "parts"
        unique_together = (("competition", "name"),)
        indexes = [models.Index(fields=["competition", "updated_at"])]

    def __str__(self):
        return self.name


class PartMaterial(models.Model):
    """零件-原料配比。part / material 任一删除均级联删除本关联行。"""

    part = models.ForeignKey(
        Part,
        on_delete=models.CASCADE,
        related_name="part_materials",
    )
    material = models.ForeignKey(
        "materials.Material",
        on_delete=models.CASCADE,
        related_name="part_materials",
    )
    ratio = models.FloatField()

    class Meta:
        db_table = "part_materials"
        unique_together = (("part", "material"),)

    def __str__(self):
        return f"{self.part_id}-{self.material_id}"


class PartTechRequirement(models.Model):
    """零件-科技节点需求。part / techNode 任一删除均级联删除本关联行。"""

    part = models.ForeignKey(
        Part,
        on_delete=models.CASCADE,
        related_name="tech_requirements",
    )
    tech_node = models.ForeignKey(
        "tech_tree.TechNode",
        on_delete=models.CASCADE,
        related_name="part_requirements",
    )

    class Meta:
        db_table = "part_tech_requirements"
        unique_together = (("part", "tech_node"),)

    def __str__(self):
        return f"{self.part_id}-{self.tech_node_id}"
