"""比赛准备总览、分组导出与分组导入视图。

路由（挂在 /api 前缀下）：
- GET  /api/preparations/plan?competitionId=<id>
        准备清单（统计 + 体检 + 明细，只读）
- GET  /api/preparations/plan/export?competitionId=<id>&format=markdown|json
        导出归档文件（附件下载；markdown 为人类可读报告，json 为可再导入的归档）
- GET  /api/preparations/scopes
        可选导出/导入分组（供前端渲染下拉）
- GET  /api/preparations/archive/export?competitionId=<id>&scope=all|<分组>
        按分组导出可再导入的 JSON 归档（附件下载）
- POST /api/preparations/archive/import?competitionId=<id>&scope=all|<分组>&dryRun=true|false
        导入归档（默认 dryRun=true 只预览不落库）；请求体即导出的 JSON 归档

权限：
- 全部需 competition:manage（超管专属）。准备总览会枚举参赛账号、公司范围等敏感配置，
  导出/导入涉及全量业务数据写入，故不向比赛管理员开放。
- 比赛域隔离与非超管可见性校验同 competitions 模块语义。

只读性：plan/export/scopes 三个 GET 完全不写库；import 是唯一的写入端点，
默认 dryRun=true（事务回滚，不留痕），且需显式 dryRun=false 才真正落库。
"""
from __future__ import annotations

import re
import urllib.parse

from django.http import HttpResponse
from rest_framework.negotiation import DefaultContentNegotiation
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.exceptions import BusinessError
from apps.common.guards import PermissionsPermission, require_permissions

from . import archive as archive_builder
from . import plan as plan_builder

_PERM_CLASSES = (IsAuthenticated, PermissionsPermission)

_MANAGE_PERM = "competition:manage"


class _IgnoreFormatParamNegotiation(DefaultContentNegotiation):
    """忽略 ?format= 查询参数的内容协商，并把它的原值留存给视图使用。

    DRF 默认把查询参数 format 当作响应格式后缀：本模块用 ?format=markdown|json
    选择「导出文件类型」，取值 markdown 在 DRF 渲染器里不存在，默认协商会直接抛
    404（NotAcceptable 被转成 NotFound），表现为「导出 Markdown 返回 404」。
    这里在协商前把该参数摘掉，并把原值暂存到 request._content_negotiation_format，
    导出类型完全由本模块自行判定。
    """

    def select_renderer(self, request, renderers, format_suffix=None):
        raw = getattr(request, "_request", None)
        if raw is not None and "format" in raw.GET:
            requested = raw.GET.get("format")
            cleaned = raw.GET.copy()
            del cleaned["format"]
            raw.GET = cleaned
            request._content_negotiation_format = requested
        return super().select_renderer(request, renderers, format_suffix)


def _requested_format(request, default: str = "markdown") -> str:
    """取导出格式：优先用协商阶段留存的 ?format= 原值。"""
    kept = getattr(request, "_content_negotiation_format", None)
    if kept:
        return str(kept)
    return str(request.query_params.get("format") or default)


# 导出支持的文件类型
_FORMATS = {
    "markdown": ("md", "text/markdown; charset=utf-8"),
    "json": ("json", "application/json; charset=utf-8"),
}

# 文件名安全字符：仅保留中日韩、字母数字、连字符与下划线
_UNSAFE_FILENAME = re.compile(r"[^\w\u4e00-\u9fff\-]+", re.UNICODE)


def _resolve_competition_id(request) -> int:
    """从 query 取 competitionId；缺省时回退当前登录用户所属比赛。"""
    raw = request.query_params.get("competitionId")
    if raw in (None, "", "null", "undefined"):
        cid = getattr(request.user, "competition_id", None)
        if not cid:
            raise BusinessError("缺少 competitionId", code=400, status_code=400)
        return int(cid)
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise BusinessError("competitionId 必须为整数", code=400, status_code=400)


def _assert_competition_visible(request, competition_id: int) -> str:
    """比赛域隔离 + 取比赛名（用于文件名）。越权视作不存在。"""
    from apps.competitions.models import Competition

    comp = Competition.objects.filter(pk=competition_id).first()
    if comp is None:
        raise BusinessError("请求的资源不存在", code=404, status_code=404)
    if getattr(request.user, "role", None) != "SUPER_ADMIN":
        if comp.id != getattr(request.user, "competition_id", None):
            raise BusinessError("请求的资源不存在", code=404, status_code=404)
    return comp.name


def _safe_filename(name: str, fallback: str = "competition") -> str:
    cleaned = _UNSAFE_FILENAME.sub("_", (name or "").strip()).strip("_")
    return cleaned or fallback


def _attachment_response(body: str, filename: str, content_type: str) -> HttpResponse:
    """构造附件下载响应（RFC 5987：同时给出 ASCII 回退名与 UTF-8 名）。"""
    resp = HttpResponse(body.encode("utf-8"), content_type=content_type)
    quoted = urllib.parse.quote(filename)
    resp["Content-Disposition"] = f"attachment; filename=\"{quoted}\"; filename*=UTF-8''{quoted}"
    resp["Cache-Control"] = "no-store"
    return resp


def _resolve_scope(request, *, default: str = "all") -> str:
    """取分组 key 并校验。"""
    scope = str(request.query_params.get("scope") or default).strip().lower()
    if not archive_builder.is_valid_scope(scope):
        valid = ", ".join([archive_builder.SCOPE_ALL] + list(archive_builder.SCOPES))
        raise BusinessError(f"不支持的导出分组：{scope}（可选 {valid}）", code=400, status_code=400)
    return scope


def _truthy(raw) -> bool:
    return str(raw or "").strip().lower() in ("1", "true", "yes", "on")


def _timestamp() -> str:
    import datetime

    return datetime.datetime.now().strftime("%Y%m%d-%H%M%S")


class PreparationPlanAPIView(APIView):
    """GET /api/preparations/plan —— 比赛准备清单（JSON，供前端展示）。"""

    permission_classes = _PERM_CLASSES
    content_negotiation_class = _IgnoreFormatParamNegotiation

    @require_permissions(_MANAGE_PERM)
    def get(self, request):
        cid = _resolve_competition_id(request)
        _assert_competition_visible(request, cid)
        return Response(plan_builder.collect(cid))


class PreparationScopesAPIView(APIView):
    """GET /api/preparations/scopes —— 可选导出/导入分组。"""

    permission_classes = _PERM_CLASSES

    @require_permissions(_MANAGE_PERM)
    def get(self, request):
        return Response({"scopes": archive_builder.scope_options()})


class PreparationExportAPIView(APIView):
    """GET /api/preparations/plan/export —— 导出准备归档文件（附件下载）。

    format=markdown：人类可读报告（总览 + 明细 + 体检提醒）
    format=json：可再导入的归档（等价于 scope=all 的 archive 导出）
    """

    permission_classes = _PERM_CLASSES
    content_negotiation_class = _IgnoreFormatParamNegotiation

    @require_permissions(_MANAGE_PERM)
    def get(self, request):
        cid = _resolve_competition_id(request)
        comp_name = _assert_competition_visible(request, cid)

        fmt = _requested_format(request, "markdown").strip().lower()
        if fmt not in _FORMATS:
            raise BusinessError(
                f"不支持的导出格式：{fmt}（可选 {'/'.join(_FORMATS)}）", code=400, status_code=400
            )
        ext, content_type = _FORMATS[fmt]

        if fmt == "markdown":
            plan = plan_builder.collect(cid)
            body = plan_builder.render_markdown(plan)
        else:
            body = json_dumps(archive_builder.build_export(cid, archive_builder.SCOPE_ALL))
        filename = f"比赛准备_{_safe_filename(comp_name)}_比赛{cid}_{_timestamp()}.{ext}"
        return _attachment_response(body, filename, content_type)


class PreparationArchiveExportAPIView(APIView):
    """GET /api/preparations/archive/export —— 按分组导出可再导入的 JSON 归档。"""

    permission_classes = _PERM_CLASSES

    @require_permissions(_MANAGE_PERM)
    def get(self, request):
        cid = _resolve_competition_id(request)
        comp_name = _assert_competition_visible(request, cid)
        scope = _resolve_scope(request)

        payload = archive_builder.build_export(cid, scope)
        body = json_dumps(payload)
        label = archive_builder.scope_label(scope)
        safe_label = _safe_filename(label, "all")
        filename = f"比赛准备_{_safe_filename(comp_name)}_比赛{cid}_{safe_label}_{_timestamp()}.json"
        return _attachment_response(body, filename, "application/json; charset=utf-8")


class PreparationArchiveImportAPIView(APIView):
    """POST /api/preparations/archive/import —— 导入归档（默认 dryRun 预览）。

    请求体（两种形态都支持）：
    1) 直接是归档 JSON（与导出的 JSON 完全一致）
    2) {"archive": {...归档...}, "config": {...导入配置...}}

    导入配置（可选，body.config 优先，其次 URL query，最后取默认值）：
    - mode: "append"（默认，已存在的保留不动）| "overwrite"（已存在的按归档更新）
    - resources: ["companies", ...] 只导入这些资源；缺省 = 归档里有什么就导什么
    - dryRun: true/false（默认 true，只预览不落库）
    - allowNonEmpty: true/false（默认 false；目标比赛已有数据时需显式开启）
    """

    permission_classes = _PERM_CLASSES

    @require_permissions(_MANAGE_PERM)
    def post(self, request):
        cid = _resolve_competition_id(request)
        _assert_competition_visible(request, cid)

        body = request.data if isinstance(request.data, dict) else {}
        config = body.get("config") if isinstance(body.get("config"), dict) else {}
        raw_archive = body.get("archive") if "archive" in body else body

        payload = validate_archive_payload(raw_archive)
        mode = _resolve_mode(config, request)
        only_resources = _resolve_resources(config, request)
        dry_run = _resolve_bool(config, request, "dryRun", default=True)
        allow_non_empty = _resolve_bool(config, request, "allowNonEmpty", default=False)
        # scope 仅用于提示：归档文件里带哪些资源就导哪些，不因前端选的分组而漏导
        requested_scope = str(request.query_params.get("scope") or "").strip().lower()

        try:
            result = archive_builder.apply_import(
                payload,
                cid,
                dry_run=dry_run,
                allow_non_empty=allow_non_empty,
                mode=mode,
                only_resources=only_resources,
                user=request.user,
            )
        except archive_builder.ArchiveError as e:
            raise BusinessError(str(e), code=400, status_code=400)

        # 归档范围与所选分组不一致时给出提示，避免用户误以为只导入了所选分组
        payload_scope = str(payload.get("scope") or "").strip().lower()
        if requested_scope and payload_scope and requested_scope != payload_scope:
            result.setdefault("problems", []).insert(
                0,
                f"所选分组为「{archive_builder.scope_label(requested_scope)}」，"
                f"但归档文件来自「{archive_builder.scope_label(payload_scope)}」分组；"
                "实际导入以归档文件内容为准。",
            )
            result["problemCount"] = len(result["problems"])
        return Response(result)


def _resolve_mode(config: dict, request) -> str:
    """取导入模式：body.config → query → 默认追加。"""
    raw = config.get("mode")
    if raw in (None, ""):
        raw = request.query_params.get("mode")
    mode = str(raw or archive_builder.MODE_APPEND).strip().lower()
    if mode not in archive_builder.IMPORT_MODES:
        raise BusinessError(
            f"不支持的导入方式：{mode}（可选 {'/'.join(archive_builder.IMPORT_MODES)}）",
            code=400,
            status_code=400,
        )
    return mode


def _resolve_resources(config: dict, request) -> set[str] | None:
    """取只导入的资源集合；未指定或为空 → None（表示全部）。"""
    raw = config.get("resources")
    if raw is None:
        raw = request.query_params.getlist("resources") or request.query_params.get("resources")
    if raw in (None, "", []):
        return None
    if isinstance(raw, str):
        items = [x.strip() for x in raw.split(",") if x.strip()]
    elif isinstance(raw, (list, tuple, set)):
        items = [str(x).strip() for x in raw if str(x).strip()]
    else:
        raise BusinessError("resources 必须是资源名数组", code=400, status_code=400)
    if not items:
        return None
    unknown = [r for r in items if r not in archive_builder.IMPORT_ORDER]
    if unknown:
        raise BusinessError(
            f"未知的资源名：{', '.join(unknown)}", code=400, status_code=400
        )
    return set(items)


def _resolve_bool(config: dict, request, key: str, *, default: bool) -> bool:
    """布尔开关取值：body.config → query；缺省用 default。"""
    if key in config:
        value = config.get(key)
        if isinstance(value, bool):
            return value
        return _truthy(value)
    if key in request.query_params:
        return _truthy(request.query_params.get(key))
    return default


def json_dumps(payload) -> str:
    import json

    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)


def validate_archive_payload(raw):
    """请求体可能是已解析对象，也可能是 JSON 字符串（multipart/raw 上传）。"""
    import json

    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            raise BusinessError("归档文件不是合法 JSON", code=400, status_code=400)
    try:
        return archive_builder.validate_archive(raw)
    except archive_builder.ArchiveError as e:
        raise BusinessError(str(e), code=400, status_code=400)

