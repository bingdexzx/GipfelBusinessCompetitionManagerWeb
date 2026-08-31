"""股票系统视图：对应原 NestJS StockController / StockService。

权限：view=stock:view，edit=stock:edit，manage=stock:manage。
路由由 backend.urls 以 path("api/", include("apps.stock.urls")) 引入。

前端契约（与 stockApi 对齐）：
- GET    /stocks                          列表（分页/增量）
- GET    /stocks/pb-sources               PE 联动数据源
- GET    /stocks/:id                      详情
- GET    /stocks/:id/candles              K 线
- POST   /stocks                          创建
- PATCH  /stocks/:id                      更新
- DELETE /stocks/:id                      删除
- GET    /stocks/accounts/list            资金账户列表
- GET    /stocks/accounts/overview        账户总览（超管）
- GET    /stocks/accounts/:id             账户详情
- GET    /stocks/accounts/:id/holdings    账户持仓
- POST   /stocks/accounts                 创建账户
- PATCH  /stocks/accounts/:id             更新账户
- DELETE /stocks/accounts/:id             删除账户
- GET    /stocks/orders/list              订单列表
- POST   /stocks/orders                   下单
- DELETE /stocks/orders/:id               撤单
- GET    /stocks/holdings/list            持仓列表
- POST   /stocks/advance-round           推进轮次
"""
from __future__ import annotations

import math

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.exceptions import BusinessError
from apps.common.guards import (
    PermissionsPermission,
    apply_competition_scope,
    require_permissions,
)
from apps.common.pagination import paginated_response, parse_pagination
from apps.common.permissions import has_permission
from apps.common.scope import assert_same_competition
from apps.common.sync import apply_updated_after, build_incremental_result
from apps.realtime.emit import emit_resource_changed

from .models import Stock, StockCandle, StockFundsAccount, StockHolding, StockOrder
from .serializers import (
    AdvanceRoundSerializer,
    CreateOrderSerializer,
    StockFundsAccountSerializer,
    StockSerializer,
)

_VIEW_PERM = "stock:view"
_EDIT_PERM = "stock:edit"
_MANAGE_PERM = "stock:manage"
_PERM_CLASSES = (IsAuthenticated, PermissionsPermission)


# ==================== 工具函数 ====================
def _is_super(user) -> bool:
    return getattr(user, "role", None) == "SUPER_ADMIN"


def _can(user, perm: str) -> bool:
    if _is_super(user):
        return True
    perms = user.permissions_list if hasattr(user, "permissions_list") else []
    return has_permission(getattr(user, "role", None), perms, perm)


def _is_high_manager(user) -> bool:
    """高级管理：可见全部账户、增删股票、推进轮次。"""
    return _is_super(user) or _can(user, _MANAGE_PERM)


def _effective_competition_id(request) -> int | None:
    """解析当前请求的比赛上下文。"""
    raw = request.query_params.get("competitionId")
    cid = None
    if raw:
        try:
            cid = int(raw)
        except (TypeError, ValueError):
            cid = None
    if _is_super(request.user):
        return cid
    return cid or getattr(request.user, "competition_id", None)


def _parse_previous_ids(raw) -> list | None:
    if not raw:
        return None
    ids: list[int] = []
    for part in str(raw).split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ids.append(int(part))
        except ValueError:
            pass
    return ids or None


def _truthy(value) -> bool:
    if value is None:
        return False
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _resolve_field_value_or_default(company_id: int, industry_field_id: int):
    from .engine import resolve_field_value_or_default

    return resolve_field_value_or_default(company_id, industry_field_id)


def _get_operable_account_ids(user, competition_id: int) -> list[int] | None:
    """解析当前用户可操作的资金账户 id 集合。

    - 超管/高级管理：返回 None（全部账户）
    - stock:edit：自己名下用户账户 + stockCompanyScopes 内公司账户
    - stock:view：仅自己名下用户账户
    """
    if _is_high_manager(user):
        return None
    scopes = user.stock_company_scopes_list if hasattr(user, "stock_company_scopes_list") else []
    qs = StockFundsAccount.objects.filter(competition_id=competition_id)
    if _can(user, _EDIT_PERM):
        from django.db.models import Q

        qs = qs.filter(
            Q(owner_type="USER", user_id=user.id)
            | Q(owner_type="COMPANY", company_id__in=scopes)
        )
    else:
        qs = qs.filter(owner_type="USER", user_id=user.id)
    return list(qs.values_list("pk", flat=True))


def _assert_account_operable(account: StockFundsAccount, user) -> None:
    if _is_high_manager(user):
        return
    scopes = user.stock_company_scopes_list if hasattr(user, "stock_company_scopes_list") else []
    own = (
        (account.owner_type == "USER" and account.user_id == user.id)
        or (
            account.owner_type == "COMPANY"
            and account.company_id is not None
            and account.company_id in scopes
        )
    )
    if not own:
        raise BusinessError("无权操作该资金账户", code=403, status_code=403)


def _serialize_stock(stock, field_map: dict | None = None, pb_map: dict | None = None) -> dict:
    """序列化股票并附加有效碳排/幸福度/行业碳排均值/有效 PE。"""
    from .engine import (
        effective_carbon,
        effective_happiness,
        effective_industry_avg_carbon,
    )

    fm = field_map or {}
    pb = pb_map.get(stock.id, stock.industry_pe) if pb_map else stock.industry_pe
    return {
        "id": stock.id,
        "code": stock.code,
        "name": stock.name,
        "totalShares": stock.total_shares,
        "initNetProfit": stock.init_net_profit,
        "industryPE": stock.industry_pe,
        "currentCarbon": stock.current_carbon,
        "industryAvgCarbon": stock.industry_avg_carbon,
        "happiness": stock.happiness,
        "carbonFieldRef": stock.carbon_field_ref,
        "happinessFieldRef": stock.happiness_field_ref,
        "industryAvgCarbonRefs": stock.industry_avg_carbon_refs,
        "pbCompanyId": stock.pb_company_id,
        "pbFieldId": stock.pb_field_id,
        "pbRandom": stock.pb_random,
        "companyId": stock.company_id,
        "competitionId": stock.competition_id,
        "initPrice": stock.init_price,
        "currentPrice": stock.current_price,
        "round": stock.round,
        "createdAt": stock.created_at,
        "updatedAt": stock.updated_at,
        "effectiveCurrentCarbon": effective_carbon(stock, fm),
        "effectiveHappiness": effective_happiness(stock, fm),
        "effectiveIndustryAvgCarbon": effective_industry_avg_carbon(stock, fm),
        "effectivePb": pb,
        "pbMode": "linked" if (stock.pb_company_id and stock.pb_field_id) else "random",
    }


def _serialize_account(account, with_field_balance: bool = False) -> dict:
    data = StockFundsAccountSerializer(account).data
    if with_field_balance:
        if account.bind_field_id and account.company_id:
            v = _resolve_field_value_or_default(account.company_id, account.bind_field_id)
            data["fieldBalance"] = v
        else:
            data["fieldBalance"] = None
    return data


# ==================== 股票 ====================
class CollectionView(APIView):
    """GET /stocks 列表 + POST /stocks 创建。"""

    permission_classes = _PERM_CLASSES

    @require_permissions(_VIEW_PERM)
    def get(self, request):
        cid = _effective_competition_id(request)
        qs = apply_competition_scope(Stock.objects.all(), request.user, request.query_params.get("competitionId"))

        # 增量同步
        updated_after = request.query_params.get("updatedAfter")
        where, incremental, _ = apply_updated_after({}, updated_after)
        from .engine import resolve_effective_pbs, resolve_field_value_map

        field_map = resolve_field_value_map(cid) if cid else {}

        if incremental:
            updated_qs = qs.filter(**where).order_by("code")
            items = [_serialize_stock(s, field_map, resolve_effective_pbs(list(updated_qs))) for s in updated_qs]
            all_current_ids = list(qs.values_list("pk", flat=True))
            previous_ids = _parse_previous_ids(request.query_params.get("previousIds"))
            if _truthy(request.query_params.get("requireExistingIds")):
                previous_ids = None
            return Response(
                build_incremental_result(items, all_current_ids, previous_ids, total=len(items))
            )

        page, page_size, skip = parse_pagination(request.query_params)
        page_qs = qs.order_by("code")[skip : skip + page_size]
        pb_map = resolve_effective_pbs(list(page_qs))
        items = [_serialize_stock(s, field_map, pb_map) for s in page_qs]
        total = qs.count()
        return Response(paginated_response(items, total, page, page_size))

    @require_permissions(_MANAGE_PERM)
    def post(self, request):
        cid = request.data.get("competitionId") or getattr(request.user, "competition_id", None)
        if not cid:
            raise BusinessError("缺少比赛上下文", code=400, status_code=400)
        data = dict(request.data)
        data["competitionId"] = cid
        serializer = StockSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        stock = serializer.create(serializer.validated_data)
        emit_resource_changed("stocks", stock.id, stock.competition_id, "created")
        return Response(_serialize_stock(stock))


class PbSourcesView(APIView):
    """GET /stocks/pb-sources — PE 联动数据源（公司+字段 + 区域卡片）。"""

    permission_classes = _PERM_CLASSES

    @require_permissions(_VIEW_PERM)
    def get(self, request):
        cid = _effective_competition_id(request)
        if not cid:
            return Response({"companies": [], "regionCards": []})

        from apps.companies.models import Company
        from apps.industry_types.models import IndustryField

        companies_qs = Company.objects.filter(competition_id=cid).order_by("name")
        type_ids = list(
            {c.industry_type_id for c in companies_qs if c.industry_type_id is not None}
        )
        fields_by_type: dict[int, list] = {}
        if type_ids:
            for f in IndustryField.objects.filter(
                industry_type_id__in=type_ids, field_type="NUMBER"
            ).order_by("sort_order"):
                fields_by_type.setdefault(f.industry_type_id, []).append({
                    "id": f.id,
                    "name": f.name,
                    "fieldKey": f.field_key,
                })

        companies = []
        for c in companies_qs:
            fields = fields_by_type.get(c.industry_type_id, []) if c.industry_type_id else []
            companies.append({
                "id": c.id,
                "name": c.name,
                "industryTypeId": c.industry_type_id,
                "fields": fields,
            })

        # 区域卡片（碳排/幸福度绑定）
        region_cards: list = []
        try:
            from apps.regions.views import _get_map_overview

            overview = _get_map_overview(cid)
            for r in overview:
                for card in r.get("cards", []):
                    region_cards.append({
                        "region": r.get("region"),
                        "cardId": card.get("id"),
                        "displayName": card.get("displayName"),
                    })
        except Exception:  # noqa: BLE001
            pass

        return Response({"companies": companies, "regionCards": region_cards})


class ItemView(APIView):
    """GET /stocks/:id 详情 + PATCH 更新 + DELETE 删除。"""

    permission_classes = _PERM_CLASSES

    def _get_stock(self, pk, request) -> Stock:
        try:
            stock = Stock.objects.get(pk=pk)
        except Stock.DoesNotExist:
            raise BusinessError("股票不存在", code=404, status_code=404)
        if not _is_super(request.user):
            if stock.competition_id != getattr(request.user, "competition_id", None):
                raise BusinessError("股票不存在", code=404, status_code=404)
        return stock

    @require_permissions(_VIEW_PERM)
    def get(self, request, pk):
        stock = self._get_stock(pk, request)
        from .engine import resolve_effective_pbs

        pb_map = resolve_effective_pbs([stock])
        return Response(_serialize_stock(stock, {}, pb_map))

    @require_permissions(_MANAGE_PERM)
    def patch(self, request, pk):
        stock = self._get_stock(pk, request)
        serializer = StockSerializer(stock, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.update(stock, serializer.validated_data)
        emit_resource_changed("stocks", stock.id, stock.competition_id, "updated")
        return Response(_serialize_stock(stock))

    @require_permissions(_MANAGE_PERM)
    def delete(self, request, pk):
        stock = self._get_stock(pk, request)
        raw = request.query_params.get("competitionId")
        try:
            competition_id = int(raw) if raw else None
        except (TypeError, ValueError):
            competition_id = None
        assert_same_competition(stock.competition_id, competition_id)
        if StockOrder.objects.filter(stock_id=pk).exists() or StockHolding.objects.filter(stock_id=pk).exists():
            raise BusinessError("该股票仍有挂单或持仓，无法删除", code=400, status_code=400)
        comp_id = stock.competition_id
        stock.delete()
        emit_resource_changed("stocks", pk, comp_id, "deleted")
        return Response({"message": "已删除"})


class CandlesView(APIView):
    """GET /stocks/:id/candles — K 线列表。"""

    permission_classes = _PERM_CLASSES

    @require_permissions(_VIEW_PERM)
    def get(self, request, pk):
        try:
            stock = Stock.objects.get(pk=pk)
        except Stock.DoesNotExist:
            raise BusinessError("股票不存在", code=404, status_code=404)
        candles = StockCandle.objects.filter(stock_id=pk, competition_id=stock.competition_id).order_by("round")
        result = [
            {
                "id": c.id,
                "stockId": c.stock_id,
                "round": c.round,
                "open": c.open,
                "high": c.high,
                "low": c.low,
                "close": c.close,
                "changePct": c.change_pct,
                "competitionId": c.competition_id,
                "createdAt": c.created_at,
                "updatedAt": c.updated_at,
            }
            for c in candles
        ]
        return Response({"stock": _serialize_stock(stock), "candles": result})


# ==================== 资金账户 ====================
class AccountListView(APIView):
    """GET /stocks/accounts/list — 资金账户列表。"""

    permission_classes = _PERM_CLASSES

    @require_permissions(_VIEW_PERM)
    def get(self, request):
        cid = _effective_competition_id(request)
        if not cid:
            return Response([])
        operable = _get_operable_account_ids(request.user, cid)
        qs = StockFundsAccount.objects.filter(competition_id=cid).exclude(name="AI做市商")
        if operable is not None:
            qs = qs.filter(pk__in=operable)
        accounts = list(qs.order_by("name"))
        return Response([_serialize_account(a, with_field_balance=True) for a in accounts])


class AccountOverviewView(APIView):
    """GET /stocks/accounts/overview — 账户总览（仅超管）。"""

    permission_classes = _PERM_CLASSES

    @require_permissions(_VIEW_PERM)
    def get(self, request):
        if not _is_super(request.user):
            raise BusinessError("仅超级管理员可查看账户总览", code=403, status_code=403)
        cid = _effective_competition_id(request)
        if not cid:
            return Response([])
        accounts = list(
            StockFundsAccount.objects.filter(competition_id=cid).exclude(name="AI做市商").order_by("name")
        )
        account_ids = [a.id for a in accounts]
        holdings = list(
            StockHolding.objects.select_related("stock").filter(
                funds_account_id__in=account_ids, competition_id=cid
            )
        )

        holdings_by_account: dict[int, list] = {}
        for h in holdings:
            arr = holdings_by_account.setdefault(h.funds_account_id, [])
            market_value = round(h.shares * h.stock.current_price * 100) / 100
            cost_basis = round(h.shares * h.cost_price * 100) / 100
            profit = round((market_value - cost_basis) * 100) / 100
            profit_pct = round((profit / cost_basis) * 10000) / 100 if cost_basis > 0 else 0
            arr.append({
                "stockCode": h.stock.code,
                "stockName": h.stock.name,
                "shares": h.shares,
                "costPrice": h.cost_price,
                "currentPrice": h.stock.current_price,
                "marketValue": market_value,
                "costBasis": cost_basis,
                "profit": profit,
                "profitPct": profit_pct,
            })

        # 公司名映射
        from apps.companies.models import Company

        company_ids = [a.company_id for a in accounts if a.company_id]
        company_name_map: dict[int, str] = {}
        if company_ids:
            for c in Company.objects.filter(pk__in=company_ids):
                company_name_map[c.id] = c.name

        result = []
        for acc in accounts:
            eff_cash = acc.cash_balance
            if acc.bind_field_id and acc.company_id:
                v = _resolve_field_value_or_default(acc.company_id, acc.bind_field_id)
                if v is not None:
                    eff_cash = v
            eff_cash = round(eff_cash * 100) / 100
            hs = holdings_by_account.get(acc.id, [])
            holdings_market_value = round(sum(h["marketValue"] for h in hs) * 100) / 100
            cost_basis = round(sum(h["costBasis"] for h in hs) * 100) / 100
            total_assets = round((eff_cash + holdings_market_value) * 100) / 100
            total_profit = round((holdings_market_value - cost_basis) * 100) / 100
            total_profit_pct = round((total_profit / cost_basis) * 10000) / 100 if cost_basis > 0 else 0
            result.append({
                "id": acc.id,
                "name": acc.name,
                "ownerType": acc.owner_type,
                "ownerLabel": "个人" if acc.owner_type == "USER" else "公司",
                "companyId": acc.company_id,
                "companyName": company_name_map.get(acc.company_id) if acc.company_id else None,
                "userId": acc.user_id,
                "cashBalance": eff_cash,
                "holdings": hs,
                "holdingsMarketValue": holdings_market_value,
                "costBasis": cost_basis,
                "totalAssets": total_assets,
                "totalProfit": total_profit,
                "totalProfitPct": total_profit_pct,
            })
        return Response(result)


class AccountCollectionView(APIView):
    """POST /stocks/accounts — 创建资金账户。"""

    permission_classes = _PERM_CLASSES

    @require_permissions(_EDIT_PERM)
    def post(self, request):
        cid = request.data.get("competitionId") or getattr(request.user, "competition_id", None)
        if not cid:
            raise BusinessError("缺少比赛上下文", code=400, status_code=400)
        name = (request.data.get("name") or "").strip()
        if not name:
            raise BusinessError("账户名不能为空", code=400, status_code=400)
        if StockFundsAccount.objects.filter(competition_id=cid, name=name).exists():
            raise BusinessError("资金账户名已存在", code=409, status_code=409)

        owner_type = request.data.get("ownerType")
        company_id = request.data.get("companyId")
        user_id = request.data.get("userId")
        bind_field_id = request.data.get("bindFieldId")
        cash_balance = request.data.get("cashBalance", 1_000_000)

        if owner_type == "USER":
            user_id = user_id or request.user.id
            company_id = None
            bind_field_id = None
            cash_balance = 1_000_000  # 个人账户固定 100 万
            if not _is_high_manager(request.user) and user_id != request.user.id:
                raise BusinessError("只能为自己创建用户资金账户", code=403, status_code=403)
        else:
            # 公司账户需 stock:manage
            if not _can(request.user, _MANAGE_PERM):
                raise BusinessError("公司账户需高级管理权限", code=403, status_code=403)
            if not company_id:
                raise BusinessError("公司账户必须指定 companyId", code=400, status_code=400)
            if not _is_high_manager(request.user):
                scopes = request.user.stock_company_scopes_list if hasattr(request.user, "stock_company_scopes_list") else []
                if company_id not in scopes:
                    raise BusinessError("只能为权限范围内的公司创建资金账户", code=403, status_code=403)
            if bind_field_id:
                v = _resolve_field_value_or_default(company_id, bind_field_id)
                if v is not None:
                    cash_balance = v

        account = StockFundsAccount.objects.create(
            name=name,
            owner_type=owner_type,
            company_id=company_id,
            user_id=user_id,
            cash_balance=cash_balance,
            bind_field_id=bind_field_id,
            competition_id=cid,
        )
        return Response(_serialize_account(account, with_field_balance=True))


class AccountItemView(APIView):
    """GET/PATCH/DELETE /stocks/accounts/:id。"""

    permission_classes = _PERM_CLASSES

    def _get_account(self, pk, request) -> StockFundsAccount:
        try:
            account = StockFundsAccount.objects.get(pk=pk)
        except StockFundsAccount.DoesNotExist:
            raise BusinessError("资金账户不存在", code=404, status_code=404)
        if not _is_super(request.user):
            if account.competition_id != getattr(request.user, "competition_id", None):
                raise BusinessError("资金账户不存在", code=404, status_code=404)
        return account

    @require_permissions(_VIEW_PERM)
    def get(self, request, pk):
        account = self._get_account(pk, request)
        if not _is_high_manager(request.user):
            _assert_account_operable(account, request.user)
        return Response(_serialize_account(account, with_field_balance=True))

    @require_permissions(_EDIT_PERM)
    def patch(self, request, pk):
        account = self._get_account(pk, request)
        if account.name == "AI做市商":
            raise BusinessError("做市商账户不可修改", code=400, status_code=400)
        _assert_account_operable(account, request.user)
        data = request.data
        if "name" in data:
            account.name = data["name"]
        if "cashBalance" in data:
            account.cash_balance = data["cashBalance"]
        if "companyId" in data:
            account.company_id = data["companyId"]
        if "userId" in data:
            account.user_id = data["userId"]
        if "bindFieldId" in data:
            account.bind_field_id = data["bindFieldId"]
            if data["bindFieldId"] and account.company_id:
                v = _resolve_field_value_or_default(account.company_id, data["bindFieldId"])
                if v is not None:
                    account.cash_balance = v
        account.save()
        return Response(_serialize_account(account, with_field_balance=True))

    @require_permissions(_MANAGE_PERM)
    def delete(self, request, pk):
        account = self._get_account(pk, request)
        _assert_account_operable(account, request.user)
        if StockHolding.objects.filter(funds_account_id=pk).exists():
            raise BusinessError("该账户仍有持仓，无法删除", code=400, status_code=400)
        if StockOrder.objects.filter(funds_account_id=pk, status="PENDING").exists():
            raise BusinessError("该账户仍有挂单，无法删除", code=400, status_code=400)
        account.delete()
        return Response({"message": "已删除"})


class AccountHoldingsView(APIView):
    """GET /stocks/accounts/:id/holdings — 账户持仓。"""

    permission_classes = _PERM_CLASSES

    @require_permissions(_VIEW_PERM)
    def get(self, request, pk):
        try:
            account = StockFundsAccount.objects.get(pk=pk)
        except StockFundsAccount.DoesNotExist:
            raise BusinessError("资金账户不存在", code=404, status_code=404)
        if not _is_high_manager(request.user):
            _assert_account_operable(account, request.user)
        holdings = StockHolding.objects.select_related("stock").filter(
            funds_account_id=pk, competition_id=account.competition_id
        )[:500]
        result = []
        for h in holdings:
            result.append({
                "id": h.id,
                "fundsAccountId": h.funds_account_id,
                "stockId": h.stock_id,
                "stockCode": h.stock.code,
                "stockName": h.stock.name,
                "currentPrice": h.stock.current_price,
                "shares": h.shares,
                "costPrice": h.cost_price,
                "marketValue": round(h.shares * h.stock.current_price * 100) / 100,
                "competitionId": h.competition_id,
                "createdAt": h.created_at,
                "updatedAt": h.updated_at,
            })
        return Response(result)


# ==================== 订单 ====================
class OrderListView(APIView):
    """GET /stocks/orders/list — 订单列表。"""

    permission_classes = _PERM_CLASSES

    @require_permissions(_VIEW_PERM)
    def get(self, request):
        cid = _effective_competition_id(request)
        if not cid:
            return Response([])
        stock_id = request.query_params.get("stockId")
        funds_account_id = request.query_params.get("fundsAccountId")

        qs = StockOrder.objects.select_related("stock").filter(competition_id=cid)
        if stock_id:
            try:
                qs = qs.filter(stock_id=int(stock_id))
            except (TypeError, ValueError):
                pass
        if funds_account_id:
            try:
                qs = qs.filter(funds_account_id=int(funds_account_id))
            except (TypeError, ValueError):
                pass
        else:
            # 按用户可操作账户范围过滤
            operable = _get_operable_account_ids(request.user, cid)
            if operable is not None:
                qs = qs.filter(funds_account_id__in=operable)

        orders = list(qs.order_by("-created_at")[:500])
        result = [
            {
                "id": o.id,
                "stockId": o.stock_id,
                "stockCode": o.stock.code,
                "stockName": o.stock.name,
                "fundsAccountId": o.funds_account_id,
                "side": o.side,
                "price": o.price,
                "quantity": o.quantity,
                "amount": o.amount,
                "status": o.status,
                "round": o.round,
                "competitionId": o.competition_id,
                "createdAt": o.created_at,
                "updatedAt": o.updated_at,
            }
            for o in orders
        ]
        return Response(result)


class OrderCollectionView(APIView):
    """POST /stocks/orders — 下单。"""

    permission_classes = _PERM_CLASSES

    @require_permissions(_EDIT_PERM)
    def post(self, request):
        serializer = CreateOrderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            stock = Stock.objects.get(pk=data["stockId"])
        except Stock.DoesNotExist:
            raise BusinessError("股票不存在", code=404, status_code=404)
        competition_id = stock.competition_id
        try:
            account = StockFundsAccount.objects.get(pk=data["fundsAccountId"])
        except StockFundsAccount.DoesNotExist:
            raise BusinessError("资金账户不存在", code=404, status_code=404)
        if account.competition_id != competition_id:
            raise BusinessError("资金账户不存在", code=404, status_code=404)

        if not _is_high_manager(request.user):
            _assert_account_operable(account, request.user)

        # 委托价限制：不得超过当前价 ±10%
        price_limit = stock.current_price * 0.1
        upper_limit = round((stock.current_price + price_limit) * 100) / 100
        lower_limit = round((stock.current_price - price_limit) * 100) / 100
        if data["price"] > upper_limit + 0.001:
            raise BusinessError(
                f"委托价不能超过 ¥{upper_limit}（当前价 ¥{stock.current_price} 的 +10%）",
                code=400, status_code=400,
            )
        if data["price"] < lower_limit - 0.001:
            raise BusinessError(
                f"委托价不能低于 ¥{lower_limit}（当前价 ¥{stock.current_price} 的 -10%）",
                code=400, status_code=400,
            )

        # 获取账户可用余额
        available_balance = account.cash_balance
        if account.bind_field_id and account.company_id:
            v = _resolve_field_value_or_default(account.company_id, account.bind_field_id)
            if v is not None:
                available_balance = v

        if data["side"] == "BUY":
            need = data["price"] * data["quantity"]
            if available_balance < need - 1e-6:
                raise BusinessError("现金余额不足", code=400, status_code=400)
        else:
            holding = StockHolding.objects.filter(
                funds_account_id=account.id, stock_id=stock.id
            ).first()
            available_shares = holding.shares if holding else 0
            if available_shares < data["quantity"] - 1e-9:
                raise BusinessError("持仓不足", code=400, status_code=400)

        order = StockOrder.objects.create(
            stock_id=stock.id,
            funds_account_id=account.id,
            side=data["side"],
            price=data["price"],
            quantity=data["quantity"],
            amount=round(data["price"] * data["quantity"] * 100) / 100,
            status="PENDING",
            round=stock.round,
            competition_id=competition_id,
        )
        emit_resource_changed("stock-orders", order.id, competition_id, "created")
        return Response({
            "id": order.id,
            "stockId": order.stock_id,
            "fundsAccountId": order.funds_account_id,
            "side": order.side,
            "price": order.price,
            "quantity": order.quantity,
            "amount": order.amount,
            "status": order.status,
            "round": order.round,
            "competitionId": order.competition_id,
            "createdAt": order.created_at,
            "updatedAt": order.updated_at,
        })


class OrderItemView(APIView):
    """DELETE /stocks/orders/:id — 撤单。"""

    permission_classes = _PERM_CLASSES

    @require_permissions(_EDIT_PERM)
    def delete(self, request, pk):
        try:
            order = StockOrder.objects.get(pk=pk)
        except StockOrder.DoesNotExist:
            raise BusinessError("订单不存在", code=404, status_code=404)
        try:
            account = StockFundsAccount.objects.get(pk=order.funds_account_id)
        except StockFundsAccount.DoesNotExist:
            raise BusinessError("资金账户不存在", code=404, status_code=404)
        if not _is_high_manager(request.user):
            _assert_account_operable(account, request.user)
        if order.status != "PENDING":
            raise BusinessError("仅可撤销挂单", code=400, status_code=400)
        order.status = "CANCELLED"
        order.save(update_fields=["status"])
        return Response({
            "id": order.id,
            "status": order.status,
        })


# ==================== 持仓 ====================
class HoldingListView(APIView):
    """GET /stocks/holdings/list — 持仓列表。"""

    permission_classes = _PERM_CLASSES

    @require_permissions(_VIEW_PERM)
    def get(self, request):
        cid = _effective_competition_id(request)
        if not cid:
            return Response([])
        account_id = request.query_params.get("accountId")
        qs = StockHolding.objects.select_related("stock").filter(competition_id=cid)
        if account_id:
            try:
                qs = qs.filter(funds_account_id=int(account_id))
            except (TypeError, ValueError):
                pass
        else:
            operable = _get_operable_account_ids(request.user, cid)
            if operable is not None:
                qs = qs.filter(funds_account_id__in=operable)

        holdings = list(qs[:500])
        result = [
            {
                "id": h.id,
                "fundsAccountId": h.funds_account_id,
                "stockId": h.stock_id,
                "stockCode": h.stock.code,
                "stockName": h.stock.name,
                "currentPrice": h.stock.current_price,
                "shares": h.shares,
                "costPrice": h.cost_price,
                "marketValue": round(h.shares * h.stock.current_price * 100) / 100,
                "competitionId": h.competition_id,
                "createdAt": h.created_at,
                "updatedAt": h.updated_at,
            }
            for h in holdings
        ]
        return Response(result)


# ==================== 推进轮次 ====================
class AdvanceRoundView(APIView):
    """POST /stocks/advance-round — 推进轮次（高级管理）。"""

    permission_classes = _PERM_CLASSES

    @require_permissions(_MANAGE_PERM)
    def post(self, request):
        # 非超管：强制使用令牌归属比赛；超管可指定
        raw_cid = request.query_params.get("competitionId")
        if _is_super(request.user):
            cid = int(raw_cid) if raw_cid else getattr(request.user, "competition_id", None)
        else:
            cid = getattr(request.user, "competition_id", None)
        if cid is None:
            raise BusinessError("缺少比赛上下文", code=400, status_code=400)

        serializer = AdvanceRoundSerializer(data=request.data or {})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        from .engine import advance_round

        result = advance_round(
            competition_id=cid,
            stock_ids=data.get("stockIds"),
            market_maker=data.get("marketMaker"),
            stock_config=data.get("stockConfig"),
        )
        # 单次 bulk 广播已在 engine.advance_round 内发出
        # 额外广播 stock:round-advanced 事件
        try:
            from apps.realtime.gateway import sio

            import asyncio

            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(
                        sio.emit(
                            "stock:round-advanced",
                            {"competitionId": cid, **result},
                            room=f"comp-{cid}",
                        )
                    )
                else:
                    loop.run_until_complete(
                        sio.emit(
                            "stock:round-advanced",
                            {"competitionId": cid, **result},
                            room=f"comp-{cid}",
                        )
                    )
            except RuntimeError:
                pass
        except Exception:  # noqa: BLE001
            pass
        return Response(result)
