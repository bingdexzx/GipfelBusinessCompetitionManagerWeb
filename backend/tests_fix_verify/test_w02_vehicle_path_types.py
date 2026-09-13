# -*- coding: utf-8 -*-
"""W-02 验证（后端契约侧）：载具「可通过路径类型」只认 `vehiclePathTypes`。

缺陷（改前，前端侧）：`VehiclesManager.vue` 提交 `pathTypeIds`、回填也读 `pathTypeIds`，
而后端契约是 `vehiclePathTypes: [{ pathTypeId }]`（`VehicleSerializer` 声明字段 +
`views._replace_relations` 只在 `"vehiclePathTypes" in data` 时全量替换）。于是：
  - 勾选的路径类型一行都写不进 `vehicle_path_types` 表，接口照样返回成功；
  - 响应里没有 `pathTypeIds` → 编辑弹窗多选框永远为空、详情永远显示 `-`。

本文件把「前端改前发的请求体」与「改后发的请求体」都打给真实接口，锁定契约：
  - 改前形态 `{"pathTypeIds": [id]}` → 201 但关系表 0 行（静默丢弃，这就是缺陷）；
  - 改后形态 `{"vehiclePathTypes": [{"pathTypeId": id}]}` → 201 且关系表 1 行，
    响应体回传 `vehiclePathTypes[].pathTypeId`（前端据此回填）。
前端侧由 tests/fix_verify/frontend/test_w02_vehicle_path_types.mjs 断言
`toVehiclePathTypes([id])` 产出的正是上面第二种形态。
"""
from __future__ import annotations

import json

from django.test import Client, TestCase

from apps.auth.authentication import create_jwt
from apps.competitions.models import Competition
from apps.fuels.models import Fuel
from apps.maps.models import PathType
from apps.users.models import User
from apps.vehicles.models import Vehicle, VehiclePathType


class VehiclePathTypesContractTests(TestCase):
    def setUp(self):
        self.comp = Competition.objects.create(name="W02-比赛")
        self.fuel = Fuel.objects.create(
            name="W02-柴油", price_per_liter="7.5000", competition=self.comp
        )
        self.pt_a = PathType.objects.create(name="W02-公路", competition=self.comp)
        self.pt_b = PathType.objects.create(name="W02-铁路", competition=self.comp)

        self.editor = User(
            username="w02-editor",
            role="COMPETITION_ADMIN",
            is_active=True,
            competition=self.comp,
            permissions=json.dumps(["data:vehicle:view", "data:vehicle:edit"]),
        )
        self.editor.set_password("W02Pw!123")
        self.editor.save()

        self.client = Client()
        self.token = create_jwt(self.editor)
        self.url = "/api/vehicles"

    def _post(self, payload):
        return self.client.post(
            self.url,
            data=payload,
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.token}",
        )

    def _base_body(self, name):
        return {
            "competitionId": self.comp.id,
            "name": name,
            "fuelId": self.fuel.id,
            "fuelConsumptionPerKm": 0.35,
            "maxCargo": 100,
            "price": "260000.0000",
            "carbonEmission": 0.5,
        }

    # ---------- 缺陷形态：改前前端发的字段名 ----------
    def test_legacy_pathTypeIds_is_silently_dropped(self):
        """改前前端发 pathTypeIds：接口成功但关系表 0 行（缺陷本体，后端行为不变）。"""
        body = {**self._base_body("W02-改前形态"), "pathTypeIds": [self.pt_a.id]}
        resp = self._post(body)
        self.assertEqual(resp.status_code, 200, resp.content)  # 本项目创建接口成功返回 200（信封 code=0）
        vehicle = Vehicle.objects.get(name="W02-改前形态")
        self.assertEqual(
            VehiclePathType.objects.filter(vehicle=vehicle).count(),
            0,
            "pathTypeIds 不是后端契约字段，DRF 静默忽略 → 一行都不写",
        )
        self.assertEqual(
            resp.json()["data"]["vehiclePathTypes"],
            [],
            "响应里也不会有 pathTypeIds，前端据此回填只会得到空数组",
        )

    # ---------- 契约形态：改后前端发的字段名 ----------
    def test_contract_vehicle_path_types_is_persisted(self):
        """改后前端发 vehiclePathTypes：[{pathTypeId}]：关系表落库且响应可回填。"""
        body = {
            **self._base_body("W02-改后形态"),
            "vehiclePathTypes": [{"pathTypeId": self.pt_a.id}, {"pathTypeId": self.pt_b.id}],
        }
        resp = self._post(body)
        self.assertEqual(resp.status_code, 200, resp.content)  # 本项目创建接口成功返回 200（信封 code=0）
        vehicle = Vehicle.objects.get(name="W02-改后形态")
        self.assertEqual(
            sorted(
                VehiclePathType.objects.filter(vehicle=vehicle).values_list(
                    "path_type_id", flat=True
                )
            ),
            sorted([self.pt_a.id, self.pt_b.id]),
            "vehiclePathTypes 必须落库",
        )
        data = resp.json()["data"]
        self.assertEqual(
            sorted(item["pathTypeId"] for item in data["vehiclePathTypes"]),
            sorted([self.pt_a.id, self.pt_b.id]),
            "响应必须回传 pathTypeId，供前端回填多选框",
        )
        self.assertEqual(data["vehiclePathTypes"][0]["pathType"]["name"] in {"W02-公路", "W02-铁路"}, True)

    def test_empty_vehicle_path_types_clears_relations(self):
        """空数组 = 显式清空（后端按 'vehiclePathTypes' in data 全量替换）。"""
        vehicle = Vehicle.objects.create(
            name="W02-清空", fuel=self.fuel, fuel_consumption_per_km=0.3,
            max_cargo=10, price="100.0000", carbon_emission=0.1, competition=self.comp,
        )
        VehiclePathType.objects.create(vehicle=vehicle, path_type=self.pt_a)
        resp = self.client.patch(
            f"{self.url}/{vehicle.pk}",
            data={"vehiclePathTypes": []},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.token}",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(VehiclePathType.objects.filter(vehicle=vehicle).count(), 0)
        self.assertEqual(resp.json()["data"]["vehiclePathTypes"], [])
