"""载具与通行路径类型模型：对应原 Prisma Vehicle / VehiclePathType。

Vehicle.fuel 使用 PROTECT（对应 Prisma onDelete: Restrict）：被引用的燃料不允许
直接删除。VehiclePathType 为复合主键关联表（Prisma @@id），沿用本仓库既定约定：
自增 id 作主键 + unique_together 表达复合唯一约束。

fuel / pathType 位于尚未创建的兄弟应用，使用字符串外键引用，于迁移/运行期解析。
"""
from django.db import models


class Vehicle(models.Model):
    """载具主数据。删除比赛时级联删除。"""

    name = models.CharField(max_length=128)
    fuel = models.ForeignKey(
        "fuels.Fuel",
        on_delete=models.PROTECT,
        related_name="vehicles",
    )
    fuel_consumption_per_km = models.FloatField()
    max_cargo = models.FloatField()
    price = models.FloatField()
    carbon_emission = models.FloatField()
    competition = models.ForeignKey(
        "competitions.Competition",
        on_delete=models.CASCADE,
        related_name="vehicles",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "vehicles"
        unique_together = (("competition", "name"),)
        indexes = [models.Index(fields=["competition", "updated_at"])]

    def __str__(self):
        return self.name


class VehiclePathType(models.Model):
    """载具-路径类型关联。vehicle / pathType 任一删除均级联删除本关联行。"""

    vehicle = models.ForeignKey(
        Vehicle,
        on_delete=models.CASCADE,
        related_name="vehicle_path_types",
    )
    path_type = models.ForeignKey(
        "maps.PathType",
        on_delete=models.CASCADE,
        related_name="vehicles",
    )

    class Meta:
        db_table = "vehicle_path_types"
        unique_together = (("vehicle", "path_type"),)

    def __str__(self):
        return f"{self.vehicle_id}-{self.path_type_id}"
