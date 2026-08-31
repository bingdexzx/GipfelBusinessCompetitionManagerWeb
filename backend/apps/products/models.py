"""产品与配比/科技需求模型：对应原 Prisma Product / ProductPart / ProductTechRequirement。

ProductPart / ProductTechRequirement 为复合主键关联表（Prisma @@id），沿用本仓库
既定约定：自增 id 作主键 + unique_together 表达复合唯一约束。
"""
from django.db import models


class Product(models.Model):
    """产品主数据。删除比赛时级联删除。"""

    name = models.CharField(max_length=128)
    competition = models.ForeignKey(
        "competitions.Competition",
        on_delete=models.CASCADE,
        related_name="products",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "products"
        unique_together = (("competition", "name"),)
        indexes = [models.Index(fields=["competition", "updated_at"])]

    def __str__(self):
        return self.name


class ProductPart(models.Model):
    """产品-零件配比。product / part 任一删除均级联删除本关联行。"""

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="product_parts",
    )
    part = models.ForeignKey(
        "parts.Part",
        on_delete=models.CASCADE,
        related_name="product_parts",
    )
    ratio = models.FloatField()

    class Meta:
        db_table = "product_parts"
        unique_together = (("product", "part"),)

    def __str__(self):
        return f"{self.product_id}-{self.part_id}"


class ProductTechRequirement(models.Model):
    """产品-科技节点需求。product / techNode 任一删除均级联删除本关联行。"""

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="tech_requirements",
    )
    tech_node = models.ForeignKey(
        "tech_tree.TechNode",
        on_delete=models.CASCADE,
        related_name="product_requirements",
    )

    class Meta:
        db_table = "product_tech_requirements"
        unique_together = (("product", "tech_node"),)

    def __str__(self):
        return f"{self.product_id}-{self.tech_node_id}"
