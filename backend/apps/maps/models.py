"""地图模型：对应原 Prisma MapNodeType / PathType / MapNode / MapEdge。

四个模型均为比赛级（competitionId 必填），删除比赛级联删除全部地图数据。
"""
from django.db import models


class MapNodeType(models.Model):
    name = models.CharField(max_length=128)
    description = models.TextField(null=True, blank=True)
    color = models.CharField(max_length=32, null=True, blank=True)
    competition = models.ForeignKey(
        "competitions.Competition",
        on_delete=models.CASCADE,
        related_name="map_node_types",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "map_node_types"
        unique_together = (("competition", "name"),)
        indexes = [models.Index(fields=["competition", "updated_at"])]

    def __str__(self):
        return self.name


class PathType(models.Model):
    name = models.CharField(max_length=128)
    description = models.TextField(null=True, blank=True)
    color = models.CharField(max_length=32, null=True, blank=True)
    competition = models.ForeignKey(
        "competitions.Competition",
        on_delete=models.CASCADE,
        related_name="path_types",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "path_types"
        unique_together = (("competition", "name"),)
        indexes = [models.Index(fields=["competition", "updated_at"])]

    def __str__(self):
        return self.name


class MapNode(models.Model):
    name = models.CharField(max_length=128)
    region = models.CharField(max_length=128, default="")
    node_type = models.ForeignKey(
        MapNodeType,
        on_delete=models.CASCADE,
        related_name="nodes",
    )
    x = models.FloatField(default=0)
    y = models.FloatField(default=0)
    competition = models.ForeignKey(
        "competitions.Competition",
        on_delete=models.CASCADE,
        related_name="map_nodes",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "map_nodes"
        unique_together = (("competition", "name"),)
        indexes = [models.Index(fields=["competition", "updated_at"])]

    def __str__(self):
        return self.name


class MapEdge(models.Model):
    from_node = models.ForeignKey(
        MapNode,
        on_delete=models.CASCADE,
        related_name="edges_from",
    )
    to_node = models.ForeignKey(
        MapNode,
        on_delete=models.CASCADE,
        related_name="edges_to",
    )
    distance = models.FloatField(default=0)
    path_type = models.ForeignKey(
        PathType,
        on_delete=models.CASCADE,
        related_name="edges",
    )
    competition = models.ForeignKey(
        "competitions.Competition",
        on_delete=models.CASCADE,
        related_name="map_edges",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "map_edges"
        unique_together = (("from_node", "to_node"),)
        indexes = [models.Index(fields=["competition", "updated_at"])]

    def __str__(self):
        return f"边#{self.id}"
