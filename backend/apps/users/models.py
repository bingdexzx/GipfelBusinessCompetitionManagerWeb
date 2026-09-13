"""用户模型。

注意：Django 自带 auth.User 与本系统 User 字段差异较大（权限范围字段、role 枚举、
tokenVersion 等），故自定义 AbstractBaseUser 体系，避免与 contrib.auth.User 冲突。
"""
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager
from django.db import models


class UserManager(BaseUserManager):
    def create_user(self, username, password=None, **extra):
        if not username:
            raise ValueError("用户名必填")
        user = self.model(username=username, **extra)
        user.set_password(password or "")
        user.save(using=self._db)
        return user

    def create_superuser(self, username, password=None, **extra):
        extra.setdefault("role", "SUPER_ADMIN")
        return self.create_user(username, password, **extra)


class User(AbstractBaseUser):
    """用户模型。

    permissions/companyScopes 等 JSON 字段用 TextField 存原始 JSON 字符串。
    """

    ROLE_CHOICES = [
        ("SUPER_ADMIN", "SUPER_ADMIN"),
        ("COMPETITION_ADMIN", "COMPETITION_ADMIN"),
        ("PLAYER", "PLAYER"),
    ]

    username = models.CharField(max_length=128, unique=True)
    password_hash = models.CharField(max_length=255)  # bcrypt 哈希
    role = models.CharField(max_length=32, default="PLAYER", choices=ROLE_CHOICES)
    display_name = models.CharField(max_length=128, null=True, blank=True)
    competition = models.ForeignKey(
        "competitions.Competition",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="users",
    )
    # 细粒度权限 JSON 数组（null 表示按 role 继承）
    permissions = models.TextField(null=True, blank=True)
    company_scopes = models.TextField(null=True, blank=True)
    view_company_scopes = models.TextField(null=True, blank=True)
    contract_view_company_scopes = models.TextField(null=True, blank=True)
    stock_company_scopes = models.TextField(null=True, blank=True)
    must_change_password = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    token_version = models.IntegerField(default=0)
    permission_version = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    USERNAME_FIELD = "username"
    REQUIRED_FIELDS = []

    objects = UserManager()

    class Meta:
        db_table = "users"
        indexes = [
            models.Index(fields=["competition", "updated_at"]),
        ]

    # ---------- 兼容 Django auth ----------
    @property
    def is_authenticated(self):
        return True

    @property
    def is_anonymous(self):
        return False

    def set_password(self, raw_password):
        """用 bcrypt cost=12 哈希，与原 bcryptjs 兼容。"""
        import bcrypt

        salt = bcrypt.gensalt(rounds=12)
        self.password_hash = bcrypt.hashpw(
            raw_password.encode("utf-8"), salt
        ).decode("utf-8")

    def check_password(self, raw_password):
        import bcrypt

        try:
            return bcrypt.checkpw(
                raw_password.encode("utf-8"), self.password_hash.encode("utf-8")
            )
        except (ValueError, TypeError):
            return False

    # ---------- 权限范围解析（与原 parseCompanyScopes / parsePermissions 一致） ----------
    @property
    def permissions_list(self) -> list:
        """细粒度权限（`permissions=null` 表示**按 role 继承**）。

        改前对 null 直接返回 `[]`，与模型字段注释的契约不符 —— 结果是"未显式赋权"的
        账号变成零权限，连基础查看都做不了（审计 I-19）。
        现在 null → 角色模板的默认权限；显式空数组 `"[]"` 仍是"零权限"（可由
        授予接口传 `permissions: []` 表达），两者语义区分明确。
        """
        import json

        if not self.permissions:
            from apps.common.permissions import role_default_permissions

            return role_default_permissions(self.role)
        try:
            data = json.loads(self.permissions)
            return data if isinstance(data, list) else []
        except (ValueError, TypeError):
            return []

    @property
    def company_scopes_list(self) -> list:
        import json

        if not self.company_scopes:
            return []
        try:
            data = json.loads(self.company_scopes)
            return data if isinstance(data, list) else []
        except (ValueError, TypeError):
            return []

    @property
    def view_company_scopes_list(self) -> list:
        import json

        if not self.view_company_scopes:
            return []
        try:
            data = json.loads(self.view_company_scopes)
            return data if isinstance(data, list) else []
        except (ValueError, TypeError):
            return []

    @property
    def contract_view_company_scopes_list(self) -> list:
        import json

        if not self.contract_view_company_scopes:
            return []
        try:
            data = json.loads(self.contract_view_company_scopes)
            return data if isinstance(data, list) else []
        except (ValueError, TypeError):
            return []

    @property
    def stock_company_scopes_list(self) -> list:
        import json

        if not self.stock_company_scopes:
            return []
        try:
            data = json.loads(self.stock_company_scopes)
            return data if isinstance(data, list) else []
        except (ValueError, TypeError):
            return []

    def __str__(self):
        return self.username
