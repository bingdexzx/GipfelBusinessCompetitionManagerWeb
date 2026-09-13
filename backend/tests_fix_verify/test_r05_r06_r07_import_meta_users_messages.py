# -*- coding: utf-8 -*-
"""R-05 / R-06 / R-07 验证：归档导入的状态、账号顺序与消息收件人。

R-05：`_imp_competition_meta` 的 docstring 写「只在目标比赛上补空缺」，实际却用归档里的 status
      覆盖目标比赛状态（归档常来自上一届 CLOSED 比赛 → 新建的 ACTIVE 比赛被静默改成已结束）。
R-06：`IMPORT_ORDER` 把 users 放在最后，而资金账户（ownerId）与消息收件人（targetUserIds）在它
      之前执行 → 用户引用永远解析不到：账户归属丢失、收件人被清空。
R-07：导入消息只写 Message 行，从不写 MessageRecipient；而收件箱/未读数只读 MessageRecipient
      → 导入的消息对任何角色都不可见，统计却显示「新增 N」。

用法（仓库根目录）：
    backend\\.venv\\Scripts\\python.exe backend\\manage.py test tests_fix_verify.test_r05_r06_r07_import_meta_users_messages -v 2
"""
from __future__ import annotations

import json

from django.test import TestCase

from apps.competitions.models import Competition
from apps.messages.models import Message, MessageRecipient
from apps.preparation import archive
from apps.stock.models import StockFundsAccount
from apps.users.models import User


class ImportMetaUsersMessagesTests(TestCase):
    def setUp(self):
        self.comp = Competition.objects.create(name="R05-目标比赛", status="ACTIVE")
        self.admin = User(
            username="r05-admin",
            role="SUPER_ADMIN",
            is_active=True,
            competition=self.comp,
            permissions=json.dumps([]),
        )
        self.admin.set_password("R05Pw!123")
        self.admin.save()

    def _import(self, payload, mode="append"):
        return archive.apply_import(
            payload,
            self.comp.id,
            dry_run=False,
            allow_non_empty=True,
            mode=mode,
            user=self.admin,
        )

    # ---------- R-05 ----------
    def test_source_status_does_not_overwrite_target(self):
        payload = {
            "resources": {
                "competitionMeta": {
                    "rows": [{"name": "R05-目标比赛", "status": "CLOSED"}]
                }
            }
        }
        result = self._import(payload)
        self.comp.refresh_from_db()

        self.assertEqual(
            self.comp.status, "ACTIVE",
            "归档里的 CLOSED 状态不得静默覆盖目标比赛的 ACTIVE（改前会被覆盖）",
        )
        notes = " ".join(result.get("notes") or [])
        self.assertIn("状态", notes, f"应给出未覆盖状态的提示：{result.get('notes')}")

    def test_background_still_filled_when_empty(self):
        """回归：背景图仍按「补空缺」逻辑写入。"""
        payload = {
            "resources": {
                "competitionMeta": {
                    "rows": [
                        {"name": "R05-目标比赛", "status": "ACTIVE",
                         "mapBackground": {"url": "/media/bg.png", "filename": "bg.png",
                                           "width": 100, "height": 50}}
                    ]
                }
            }
        }
        self._import(payload)
        self.comp.refresh_from_db()
        self.assertIn("bg.png", self.comp.map_background or "")

    # ---------- R-06 ----------
    def test_fund_account_owner_resolves_when_users_imported_together(self):
        player = User.objects.create(
            username="r06-player", role="PLAYER", is_active=True, competition=self.comp
        )
        payload = {
            "resources": {
                "users": {"rows": [{"_id": 1, "username": "r06-player", "role": "PLAYER"}]},
                "stockFundsAccounts": {
                    "rows": [
                        {
                            "_id": 1,
                            "name": "R06账户",
                            "ownerType": "USER",
                            "userId": 1,
                            "cashBalance": "1000",
                        }
                    ]
                },
            }
        }
        self._import(payload)

        account = StockFundsAccount.objects.filter(competition=self.comp, name="R06账户").first()
        self.assertIsNotNone(account, "资金账户应被导入")
        self.assertEqual(
            account.user_id, player.id,
            "ownerType=USER 的资金账户必须解析到目标比赛里的账号（改前 users 尚未导入 → user_id=None）",
        )

    # ---------- R-07 ----------
    def test_message_recipients_are_created_for_all_target(self):
        receiver = User.objects.create(
            username="r07-player", role="PLAYER", is_active=True, competition=self.comp
        )
        payload = {
            "resources": {
                "messages": {
                    "rows": [
                        {
                            "_id": 1,
                            "title": "R07全体消息",
                            "content": "正文",
                            "senderUsername": "r05-admin",
                            "targetsAll": True,
                            "targetUserIds": [],
                        }
                    ]
                }
            }
        }
        result = self._import(payload)

        message = Message.objects.filter(competition=self.comp, title="R07全体消息").first()
        self.assertIsNotNone(message, "消息应被导入")
        recipient_ids = set(
            MessageRecipient.objects.filter(message=message).values_list("user_id", flat=True)
        )
        self.assertIn(
            receiver.id, recipient_ids,
            "targetsAll 的消息必须写入 MessageRecipient，否则收件箱与未读数看不到（改前从不写）",
        )
        self.assertTrue(
            any("收件人" in n for n in (result.get("notes") or [])),
            f"应提示已写入收件人：{result.get('notes')}",
        )

    def test_message_recipients_are_created_for_named_targets(self):
        receiver = User.objects.create(
            username="r07-named", role="PLAYER", is_active=True, competition=self.comp
        )
        payload = {
            "resources": {
                "users": {"rows": [{"_id": 7, "username": "r07-named", "role": "PLAYER"}]},
                "messages": {
                    "rows": [
                        {
                            "_id": 1,
                            "title": "R07指定消息",
                            "content": "正文",
                            "senderUsername": "r05-admin",
                            "targetsAll": False,
                            "targetUserIds": [7],
                        }
                    ]
                },
            }
        }
        self._import(payload)
        message = Message.objects.get(competition=self.comp, title="R07指定消息")
        recipient_ids = set(
            MessageRecipient.objects.filter(message=message).values_list("user_id", flat=True)
        )
        self.assertEqual(recipient_ids, {receiver.id}, "指定收件人应被解析并写入收件人行")
