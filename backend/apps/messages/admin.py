"""Django admin 注册：本 app 全部业务模型，便于后台临时排查/修数。
注意：后台直接写库会绕过业务校验（合同引擎/股票计算/权限派生等），仅用于临时修数。
"""
from django.contrib import admin

from .models import (
    Message,
    MessageRecipient,
)

admin.site.register(Message)
admin.site.register(MessageRecipient)
