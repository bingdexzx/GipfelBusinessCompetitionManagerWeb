from django.urls import path

from . import views

app_name = "audit"

urlpatterns = [
    path("audit-logs", views.AuditLogListView.as_view(), name="audit-log-list"),
]
