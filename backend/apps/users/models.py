"""用户模型：对应原 Prisma User。

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
        if password:
            user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, username, password=None, **extra):
        extra.setdefault("role", "SUPER_ADMIN")
        return self.create_user(username, password, **extra)


class User(AbstractBaseUser):
    """与原 Prisma User 字段 1:1 对应。

    permissions/companyScopes 等 JSON 字段用 TextField 存原始 JSON 字符串
    （与原 Prisma String? 存 JSON 一致，避免迁移期格式差异）。
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
        import json

        if not self.permissions:
            return []
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
