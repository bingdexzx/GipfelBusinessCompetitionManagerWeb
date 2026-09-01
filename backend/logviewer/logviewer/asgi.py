import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "logviewer.settings")

# 生产由 daphne 拉起（与主线后端一致）：daphne logviewer.asgi:application
application = get_asgi_application()
