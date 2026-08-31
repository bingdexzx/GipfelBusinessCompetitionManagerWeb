"""股票撮合 / 定价引擎：对应原 NestJS engine.ts + stock.service.ts 的推进轮次逻辑。

纯函数部分（compute_match / compute_price / build_candle / compute_init_price）
严格对齐原 engine.ts；advance_round 为 ORM 依赖的推进轮次编排器，对齐
stock.service.ts 的 advanceRound / advanceOneStock / generateMarketMakerOrders。

逻辑要点（与原 engine.ts 注释一致）：
- 撮合：最高买价=MAX(买入价)，最低卖价=MIN(卖出价)，成交价=(最高买+最低卖)/2，
  是否成交=最高买>=最低卖。
- 定价（消除一字板）：净买压力 pressure=(买量-卖量)/(买量+卖量+1)∈(-1,1)；
  趋势偏置 drift=happinessImpact*(幸福度-50)/50 + carbonImpact*clamp((均值-碳排)/均值,-1,1)；
  理论价=上轮收盘×(1+pressure*maxMovePct+drift*maxMovePct)；
  成交价参与定价 final=限幅(tradePriceWeight*tradePrice+(1-weight)*理论价, 上轮×(1±limitPct))；
  未成交(单边无对手盘)→平盘，价格不动。
- K线：开盘=上轮收盘；收盘=最终价；盘高/盘低叠加确定性盘中波动（上下影线）。
"""
from __future__ import annotations

import json
import logging
import math
import random
import threading
from typing import Any, Iterable

from django.db import transaction

from apps.common.exceptions import BusinessError

logger = logging.getLogger("gipfel")

EPS = 1e-9


# ==================== 基础数值工具 ====================
def round2(v: float) -> float:
    """保留 2 位小数（股价精度）。"""
    return round(v * 100) / 100


def clamp(v: float, lo: float, hi: float) -> float:
    """限幅辅助：把 v 截断到 [lo, hi]。"""
    return max(lo, min(hi, v))


def candle_noise(seed_a: float, seed_b: float) -> float:
    """确定性伪随机：由两个种子派生 [0,1) 的伪随机数（正弦哈希，可复现）。"""
    x = math.sin(seed_a * 127.1 + seed_b * 311.7) * 43758.5453
    return x - math.floor(x)


# ==================== 撮合（纯函数） ====================
def compute_match(orders: Iterable[dict]) -> dict:
    """撮合结果：最高买价、最低卖价、成交价等。

    orders: [{side:"BUY"|"SELL", price, quantity}, ...]
    返回 {highestBuy, lowestSell, totalBuyQty, totalSellQty,
          totalBuyAmount, totalSellAmount, matched, tradePrice}
    """
    orders = list(orders)
    buys = [o for o in orders if o["side"] == "BUY"]
    sells = [o for o in orders if o["side"] == "SELL"]

    highest_buy = max((o["price"] for o in buys), default=0)
    lowest_sell = min((o["price"] for o in sells), default=float("inf"))

    total_buy_qty = sum(o["quantity"] for o in buys)
    total_sell_qty = sum(o["quantity"] for o in sells)
    total_buy_amount = sum(o["price"] * o["quantity"] for o in buys)
    total_sell_amount = sum(o["price"] * o["quantity"] for o in sells)

    matched = len(buys) > 0 and len(sells) > 0 and highest_buy >= lowest_sell
    trade_price = (highest_buy + lowest_sell) / 2 if matched else None

    return {
        "highestBuy": highest_buy,
        "lowestSell": lowest_sell if lowest_sell != float("inf") else 0,
        "totalBuyQty": total_buy_qty,
        "totalSellQty": total_sell_qty,
        "totalBuyAmount": total_buy_amount,
        "totalSellAmount": total_sell_amount,
        "matched": matched,
        "tradePrice": trade_price,
    }


# ==================== 定价（纯函数） ====================
def compute_pressure(buy_qty: float, sell_qty: float) -> float:
    """净买压力：∈ (-1, 1)，分母 +1 防除零。"""
    denom = buy_qty + sell_qty + 1
    return (buy_qty - sell_qty) / denom


def compute_carbon_drift(
    current_carbon: float,
    industry_avg_carbon: float,
    carbon_saturate_ratio: float = 2,
) -> float:
    """碳排趋势偏置分量（对数压缩）。

    - 碳排=均值 → 0；碳排=R 倍均值 → -1；零碳排 → +1
    - 行业均值≤0 无法归一 → 0
    """
    if industry_avg_carbon <= 0:
        return 0
    if current_carbon <= 0:
        return 1
    r = current_carbon / industry_avg_carbon
    k = math.log(carbon_saturate_ratio if carbon_saturate_ratio > 1 else 2)
    return min(1, -math.log(r) / k)


def compute_drift(
    happiness: float,
    current_carbon: float,
    industry_avg_carbon: float,
    happiness_impact: float,
    carbon_impact: float,
    carbon_saturate_ratio: float = 2,
) -> float:
    """趋势偏置：幸福度/碳排压缩为长期趋势偏置。"""
    h = (happiness - 50) / 50
    c = compute_carbon_drift(current_carbon, industry_avg_carbon, carbon_saturate_ratio)
    return happiness_impact * h + carbon_impact * c


def compute_theoretical(
    last_close: float,
    pressure: float,
    drift: float,
    max_move_pct: float,
) -> float:
    """理论价：上轮收盘 × (1 + 压力×maxMovePct + 偏置×maxMovePct)。"""
    return last_close * (1 + pressure * max_move_pct + drift * max_move_pct)


def compute_price(factors: dict, config: dict) -> dict:
    """最终价（限幅后，2 位小数）。

    factors: {lastClose, buyQty, sellQty, matched, tradePrice, happiness,
              currentCarbon, industryAvgCarbon}
    config: StockConfig dict
    返回 {pressure, drift, theoretical, final, usedTradePrice}
    """
    pressure = compute_pressure(factors["buyQty"], factors["sellQty"])
    drift = compute_drift(
        factors["happiness"],
        factors["currentCarbon"],
        factors["industryAvgCarbon"],
        config["happinessImpact"],
        config["carbonImpact"],
        config["carbonSaturateRatio"],
    )
    theoretical = compute_theoretical(
        factors["lastClose"], pressure, drift, config["maxMovePct"]
    )

    upper = factors["lastClose"] * (1 + config["limitPct"])
    lower = factors["lastClose"] * (1 - config["limitPct"])

    trade_price = factors.get("tradePrice")
    if factors["matched"] and trade_price is not None and math.isfinite(trade_price):
        w = config["tradePriceWeight"]
        blended = w * trade_price + (1 - w) * theoretical
        final = clamp(blended, lower, upper)
        used_trade_price = True
    else:
        final = clamp(factors["lastClose"], lower, upper)
        used_trade_price = False

    final = round2(final)
    return {
        "pressure": pressure,
        "drift": drift,
        "theoretical": theoretical,
        "final": final,
        "usedTradePrice": used_trade_price,
    }


def build_candle(
    open_: float,
    close: float,
    round_: int,
    theoretical: float | None = None,
    limit_pct: float = 0.1,
) -> dict:
    """构建 K 线数据。"""
    upper = round2(open_ * (1 + limit_pct))
    lower = round2(open_ * (1 - limit_pct))
    range_ = upper - lower

    body_high = max(open_, close)
    body_low = min(open_, close)

    high = body_high
    low = body_low
    if theoretical is not None and math.isfinite(theoretical):
        t = min(max(theoretical, lower), upper)
        high = max(high, t)
        low = min(low, t)

    wick = range_ * 0.12
    up_wick = wick * candle_noise(round_, open_)
    down_wick = wick * candle_noise(round_ * 3 + 7, open_)
    high = round2(min(upper, high + up_wick))
    low = round2(max(lower, low - down_wick))

    change_pct = (
        round(((close - open_) / open_) * 100 * 100) / 100 if open_ != 0 else 0
    )
    return {
        "round": round_,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "changePct": change_pct,
    }


def compute_init_price(
    init_net_profit: float, total_shares: float, industry_pe: float
) -> float:
    """初始价公式：ROUND(initNetProfit*10000/totalShares/industryPE, 2)。"""
    if industry_pe <= 0 or total_shares <= 0:
        return 0
    return round((init_net_profit * 10000) / total_shares / industry_pe * 100) / 100


# ==================== StockConfig ====================
DEFAULT_STOCK_CONFIG: dict = {
    "limitPct": 0.1,
    "maxMovePct": 0.05,
    "happinessImpact": 0.2,
    "carbonImpact": 0.2,
    "mmDepthPct": 0.001,
    "mmMinQty": 1000,
    "mmMaxQty": 100000,
    "mmSpreadPct": 0.02,
    "interventionMode": "regression",
    "regressionPct": 0.02,
    "tradePriceWeight": 0.7,
    "carbonSaturateRatio": 2,
}


def resolve_stock_config(input_: dict | None) -> dict:
    """将未知/缺失字段合并回默认值，保证运行期类型完整。"""
    if not input_ or not isinstance(input_, dict):
        return dict(DEFAULT_STOCK_CONFIG)
    merged = dict(DEFAULT_STOCK_CONFIG)
    merged.update(input_)
    return merged


# ==================== 字段值解析（ORM 依赖） ====================
def resolve_field_value_or_default(
    company_id: int, industry_field_id: int
) -> float | None:
    """读取公司产业字段的当前值；无记录时回退字段 defaultValue。

    返回 number | None（无法解析则 None）。
    """
    from apps.companies.models import CompanyFieldValue
    from apps.industry_types.models import IndustryField

    fv = CompanyFieldValue.objects.filter(
        company_id=company_id, industry_field_id=industry_field_id
    ).first()
    if fv is not None and fv.value is not None:
        try:
            n = float(fv.value)
            if math.isfinite(n):
                return n
        except (ValueError, TypeError):
            pass
    try:
        field = IndustryField.objects.get(pk=industry_field_id)
    except IndustryField.DoesNotExist:
        return None
    if field.default_value is not None:
        try:
            n = float(field.default_value)
            if math.isfinite(n):
                return n
        except (ValueError, TypeError):
            pass
    return None


def resolve_field_value_map(competition_id: int) -> dict[str, float | None]:
    """构建「区域:卡片 -> 实时值」映射，供股票绑定字段实时引用。

    对应原 NestJS resolveFieldValueMap：调用 regionService.getMapOverview。
    """
    field_map: dict[str, float | None] = {}
    if not competition_id:
        return field_map
    try:
        from apps.regions.views import _get_map_overview

        overview = _get_map_overview(competition_id)
    except Exception:  # noqa: BLE001 - 区域服务不可用时回退空映射
        logger.debug("resolve_field_value_map 失败 comp=%s", competition_id, exc_info=True)
        return field_map
    for r in overview:
        for card in r.get("cards", []):
            key = f"{r.get('region')}:{card.get('id')}"
            val: float | None = None
            if card.get("valid") and card.get("value") is not None:
                try:
                    n = float(card["value"])
                    val = n if math.isfinite(n) else None
                except (ValueError, TypeError):
                    val = None
            field_map[key] = val
    return field_map


def _parse_field_ref(raw: str | None) -> dict | None:
    """解析绑定引用字符串（JSON {region, cardId}）。空/非法返回 None。"""
    if not raw:
        return None
    try:
        v = json.loads(raw)
        region = v.get("region") if isinstance(v, dict) else None
        card_id = v.get("cardId") if isinstance(v, dict) else None
        if isinstance(region, str) and (isinstance(card_id, str) or isinstance(card_id, int)):
            return {"region": region, "cardId": str(card_id)}
    except (ValueError, TypeError):
        pass
    return None


def _parse_field_refs(raw: str | None) -> list[dict]:
    """解析绑定引用数组字符串（JSON [{region, cardId}, ...]）。空/非法返回 []。"""
    if not raw:
        return []
    try:
        v = json.loads(raw)
        if not isinstance(v, list):
            return []
        result = []
        for x in v:
            if not isinstance(x, dict):
                continue
            region = x.get("region")
            card_id = x.get("cardId")
            if isinstance(region, str) and (isinstance(card_id, str) or isinstance(card_id, int)):
                result.append({"region": region, "cardId": str(card_id)})
        return result
    except (ValueError, TypeError):
        return []


def effective_carbon(stock, field_map: dict) -> float:
    ref = _parse_field_ref(getattr(stock, "carbon_field_ref", None))
    if ref:
        v = field_map.get(f"{ref['region']}:{ref['cardId']}")
        if isinstance(v, (int, float)):
            return v
    return stock.current_carbon


def effective_happiness(stock, field_map: dict) -> float:
    ref = _parse_field_ref(getattr(stock, "happiness_field_ref", None))
    if ref:
        v = field_map.get(f"{ref['region']}:{ref['cardId']}")
        if isinstance(v, (int, float)):
            return v
    return stock.happiness


def effective_industry_avg_carbon(stock, field_map: dict) -> float:
    refs = _parse_field_refs(getattr(stock, "industry_avg_carbon_refs", None))
    vals: list[float] = []
    for ref in refs:
        v = field_map.get(f"{ref['region']}:{ref['cardId']}")
        if isinstance(v, (int, float)):
            vals.append(v)
    if vals:
        avg = sum(vals) / len(vals)
        return round(avg * 100) / 100
    return stock.industry_avg_carbon


# ==================== PE 联动 / 随机 ====================
def random_pb() -> float:
    """生成一个 0~20 的随机 PE（保留两位小数）。"""
    return round(random.random() * 20 * 100) / 100


def clamp_pb(v: float) -> float:
    """将 PE 值钳制到 [0, 20] 并保留两位小数。"""
    if not math.isfinite(v):
        return random_pb()
    c = min(20, max(0, v))
    return round(c * 100) / 100


def resolve_effective_pb(stock) -> float:
    """计算单只股票的有效 PE：联动模式读实时字段值，随机模式用缓存 industryPE。"""
    pb_company_id = getattr(stock, "pb_company_id", None)
    pb_field_id = getattr(stock, "pb_field_id", None)
    if pb_company_id and pb_field_id:
        v = resolve_field_value_or_default(pb_company_id, pb_field_id)
        if v is not None and v > 0:
            return v
        return stock.industry_pe
    return stock.industry_pe


def resolve_effective_pbs(stocks: list) -> dict[int, float]:
    """批量计算股票的有效 PE。"""
    result: dict[int, float] = {}
    linked = [s for s in stocks if getattr(s, "pb_company_id", None) and getattr(s, "pb_field_id", None)]
    if linked:
        from apps.companies.models import CompanyFieldValue
        from apps.industry_types.models import IndustryField

        company_ids = list({s.pb_company_id for s in linked})
        field_ids = list({s.pb_field_id for s in linked})
        val_map: dict[tuple[int, int], float] = {}
        for fv in CompanyFieldValue.objects.filter(
            company_id__in=company_ids, industry_field_id__in=field_ids
        ):
            try:
                n = float(fv.value) if fv.value is not None else float("nan")
                if math.isfinite(n):
                    val_map[(fv.company_id, fv.industry_field_id)] = n
            except (ValueError, TypeError):
                pass
        default_map: dict[int, float] = {}
        for f in IndustryField.objects.filter(pk__in=field_ids):
            if f.default_value is not None:
                try:
                    n = float(f.default_value)
                    if math.isfinite(n):
                        default_map[f.id] = n
                except (ValueError, TypeError):
                    pass
        for s in linked:
            v = val_map.get((s.pb_company_id, s.pb_field_id))
            if v is None:
                v = default_map.get(s.pb_field_id)
            result[s.id] = v if v is not None else s.industry_pe
    for s in stocks:
        if s.id not in result:
            result[s.id] = s.industry_pe
    return result


def apply_pb_round(stock) -> None:
    """推进一轮时更新 PE 并据最新有效 PE 实时重算初始价。

    - 联动模式刷新实时字段值；
    - 随机模式做 ±2 随机游走并钳制到 [0,20]。
    两种模式下初始价均按 compute_init_price 实时重算。
    """
    pb_company_id = getattr(stock, "pb_company_id", None)
    pb_field_id = getattr(stock, "pb_field_id", None)
    pb_random = getattr(stock, "pb_random", None)
    if pb_company_id and pb_field_id:
        v = resolve_field_value_or_default(pb_company_id, pb_field_id)
        industry_pe = v if (v is not None and v > 0) else stock.industry_pe
        new_pb_random = None
    else:
        prev = pb_random if pb_random is not None else random_pb()
        step = random.random() * 4 - 2  # [-2, 2]
        nxt = clamp_pb(prev + step)
        industry_pe = nxt
        new_pb_random = nxt
    init_price = compute_init_price(stock.init_net_profit, stock.total_shares, industry_pe)
    stock.industry_pe = industry_pe
    stock.init_price = init_price
    if new_pb_random != pb_random:
        stock.pb_random = new_pb_random
    stock.save(update_fields=["industry_pe", "init_price", "pb_random"])


# ==================== 字段值写入（事务内） ====================
def write_field_value_in_tx(
    company_id: int, industry_field_id: int, value: str
) -> None:
    """事务内写入单个字段值（乐观锁语义，与 company_fields._write_field_value 一致）。"""
    from apps.companies.models import CompanyFieldValue

    fv = CompanyFieldValue.objects.filter(
        company_id=company_id, industry_field_id=industry_field_id
    ).first()
    if fv is None:
        CompanyFieldValue.objects.create(
            company_id=company_id,
            industry_field_id=industry_field_id,
            value=value,
            version=1,
        )
        return
    CompanyFieldValue.objects.filter(pk=fv.pk).update(
        value=value,
        version=fv.version + 1,
    )


# ==================== 做市商 ====================
def generate_market_maker_orders(
    stock,
    competition_id: int,
    stock_config: dict,
    mm_override: dict | None = None,
    consecutive_up: int = 0,
    consecutive_down: int = 0,
) -> tuple[int, bool]:
    """AI 做市商：为指定股票自动生成买卖挂单，提供流动性。

    返回 (生成订单数, 是否干预)。
    """
    from .models import StockFundsAccount, StockHolding, StockOrder

    enabled = (mm_override or {}).get("enabled", True)
    if not enabled:
        return 0, False

    spread_pct = ((mm_override or {}).get("spreadPct", stock_config["mmSpreadPct"] * 100)) / 100
    levels = (mm_override or {}).get("levels", 3)
    override_base = (mm_override or {}).get("baseQuantity")
    if override_base is not None:
        base_quantity = override_base
    else:
        base_quantity = max(
            stock_config["mmMinQty"],
            min(stock_config["mmMaxQty"], round((stock.total_shares or 0) * 10000 * stock_config["mmDepthPct"])),
        )

    base_price = stock.current_price
    if base_price <= 0:
        return 0, False

    # 查找或创建做市商资金账户
    mm_account, _ = StockFundsAccount.objects.get_or_create(
        competition_id=competition_id,
        name="AI做市商",
        defaults={"owner_type": "COMPANY", "cash_balance": 1_000_000_000},
    )

    # 取消上一轮未成交的做市商订单（仅当轮有效）
    StockOrder.objects.filter(
        stock_id=stock.id,
        competition_id=competition_id,
        status="PENDING",
        funds_account_id=mm_account.id,
    ).update(status="CANCELLED")

    # 回归锚干预（连续封板 ≥ 2 轮）
    need_intervene = (
        stock_config["interventionMode"] == "regression"
        and (consecutive_up >= 2 or consecutive_down >= 2)
    )
    intervention_qty = base_quantity * 3 if need_intervene else 0

    # 计算总卖量，确保持仓足够
    total_sell_qty = sum(base_quantity * i for i in range(1, levels + 1))
    total_sell_qty += intervention_qty

    mm_holding = StockHolding.objects.filter(
        funds_account_id=mm_account.id, stock_id=stock.id
    ).first()
    current_shares = mm_holding.shares if mm_holding else 0
    need_shares = total_sell_qty - current_shares

    orders: list[StockOrder] = []
    current_round = stock.round

    # 持仓不足则先建仓
    if need_shares > 0:
        orders.append(StockOrder(
            stock_id=stock.id,
            funds_account_id=mm_account.id,
            side="BUY",
            price=base_price,
            quantity=need_shares,
            amount=round2(base_price * need_shares),
            status="PENDING",
            round=current_round,
            competition_id=competition_id,
        ))
        # 直接写入持仓（保证本轮卖单有库存）
        if mm_holding is None:
            StockHolding.objects.create(
                funds_account_id=mm_account.id,
                stock_id=stock.id,
                shares=total_sell_qty,
                cost_price=base_price,
                competition_id=competition_id,
            )
        else:
            mm_holding.shares = mm_holding.shares + need_shares
            mm_holding.save(update_fields=["shares"])
        # 扣减做市商现金
        mm_account.cash_balance = mm_account.cash_balance - round2(base_price * need_shares)
        mm_account.save(update_fields=["cash_balance"])

    # 回归锚干预
    if need_intervene:
        is_up = consecutive_up >= 2
        intervention_price = round2(
            base_price * (1 + (stock_config["regressionPct"] if is_up else -stock_config["regressionPct"]))
        )
        orders.append(StockOrder(
            stock_id=stock.id,
            funds_account_id=mm_account.id,
            side="SELL" if is_up else "BUY",
            price=intervention_price,
            quantity=intervention_qty,
            amount=round2(intervention_price * intervention_qty),
            status="PENDING",
            round=current_round,
            competition_id=competition_id,
        ))

    for i in range(1, levels + 1):
        offset = spread_pct * i
        sell_price = round2(base_price * (1 + offset))
        sell_qty = base_quantity * i
        sell_amount = round2(sell_price * sell_qty)
        buy_price = round2(base_price * (1 - offset))
        buy_qty = round(sell_amount / buy_price * 1e6) / 1e6 if buy_price > 0 else 0
        if buy_price > 0 and buy_qty > 0:
            orders.append(StockOrder(
                stock_id=stock.id,
                funds_account_id=mm_account.id,
                side="BUY",
                price=buy_price,
                quantity=buy_qty,
                amount=round2(buy_price * buy_qty),
                status="PENDING",
                round=current_round,
                competition_id=competition_id,
            ))
        orders.append(StockOrder(
            stock_id=stock.id,
            funds_account_id=mm_account.id,
            side="SELL",
            price=sell_price,
            quantity=sell_qty,
            amount=sell_amount,
            status="PENDING",
            round=current_round,
            competition_id=competition_id,
        ))

    if orders:
        StockOrder.objects.bulk_create(orders)
    return len(orders), need_intervene


# ==================== 单只股票推进 ====================
def advance_one_stock(
    stock,
    competition_id: int,
    field_map: dict,
    stock_config: dict,
    consecutive_up: int = 0,
    consecutive_down: int = 0,
    mm_config: dict | None = None,
) -> dict | None:
    """推进单只股票一轮：撮合、定价、写持仓/现金/订单状态、生成 K 线。

    返回结果 dict（skipped=True 表示跳过）或 None。
    """
    from .models import StockCandle, StockFundsAccount, StockHolding, StockOrder

    with transaction.atomic():
        # 做市商挂单（建仓/扣款/挂单与撮合同一事务）
        mm_count, mm_intervened = generate_market_maker_orders(
            stock, competition_id, stock_config, mm_config, consecutive_up, consecutive_down
        )

        # 读取本事务内刚生成的 PENDING 订单
        orders = list(
            StockOrder.objects.select_related("funds_account").filter(
                stock_id=stock.id, competition_id=competition_id, status="PENDING"
            ).order_by("created_at")
        )
        # 无任何订单 → 不推进
        if not orders:
            return {
                "stockId": stock.id,
                "code": stock.code,
                "round": stock.round,
                "skipped": True,
            }

        # 撮合
        match = compute_match(
            [{"side": o.side, "price": o.price, "quantity": o.quantity} for o in orders]
        )

        # expand-limit 模式：连续封板 ≥ 2 轮时临时放宽限幅
        limit_pct = stock_config["limitPct"]
        if stock_config["interventionMode"] == "expand-limit":
            consec = max(consecutive_up, consecutive_down)
            if consec >= 2:
                limit_pct = min(0.2, stock_config["limitPct"] * (1 + 0.5 * (consec - 1)))
        cfg = dict(stock_config)
        cfg["limitPct"] = limit_pct

        price = compute_price(
            {
                "lastClose": stock.current_price,
                "buyQty": match["totalBuyQty"],
                "sellQty": match["totalSellQty"],
                "matched": match["matched"],
                "tradePrice": match["tradePrice"],
                "happiness": effective_happiness(stock, field_map),
                "currentCarbon": effective_carbon(stock, field_map),
                "industryAvgCarbon": effective_industry_avg_carbon(stock, field_map),
            },
            cfg,
        )

        # 撮合不成交 → 平盘，价格不动、不生成 K 线
        if not match["matched"]:
            return {
                "stockId": stock.id,
                "code": stock.code,
                "round": stock.round,
                "skipped": True,
                "matched": False,
                "pressure": price["pressure"],
                "drift": price["drift"],
                "theoretical": price["theoretical"],
                "buyQty": match["totalBuyQty"],
                "sellQty": match["totalSellQty"],
                "buyAmount": match["totalBuyAmount"],
                "sellAmount": match["totalSellAmount"],
            }

        # 账户现金 / 持仓运行时快照
        cash_map: dict[int, float] = {}
        account_objs: dict[int, StockFundsAccount] = {}
        for o in orders:
            if o.funds_account_id not in cash_map:
                acc = o.funds_account
                account_objs[o.funds_account_id] = acc
                if acc.bind_field_id and acc.company_id:
                    v = resolve_field_value_or_default(acc.company_id, acc.bind_field_id)
                    cash_map[o.funds_account_id] = v if v is not None else acc.cash_balance
                else:
                    cash_map[o.funds_account_id] = acc.cash_balance

        account_ids = list(cash_map.keys())
        holding_map: dict[int, dict] = {}
        for h in StockHolding.objects.filter(stock_id=stock.id, funds_account_id__in=account_ids):
            holding_map[h.funds_account_id] = {"shares": h.shares, "costPrice": h.cost_price}
        touched_accounts: set[int] = set()

        # 价格-时间优先撮合
        buys = sorted(
            [o for o in orders if o.side == "BUY"],
            key=lambda o: (-o.price, o.created_at),
        )
        sells = sorted(
            [o for o in orders if o.side == "SELL"],
            key=lambda o: (o.price, o.created_at),
        )
        buy_rem = {o.id: o.quantity for o in buys}
        sell_rem = {o.id: o.quantity for o in sells}
        filled: dict[int, float] = {}
        trade_price = match["tradePrice"]

        bi = 0
        si = 0
        while bi < len(buys) and si < len(sells):
            buy = buys[bi]
            sell = sells[si]
            if buy.price < sell.price:
                break
            qty = min(buy_rem[buy.id], sell_rem[sell.id])
            buy_cash = cash_map[buy.funds_account_id]
            if qty * trade_price > buy_cash + EPS:
                qty = buy_cash / trade_price
                if qty <= EPS:
                    buy_rem[buy.id] = 0
                    bi += 1
                    continue
            sell_hold = holding_map.get(sell.funds_account_id)
            sell_shares = sell_hold["shares"] if sell_hold else 0
            if qty > sell_shares + EPS:
                qty = sell_shares
                if qty <= EPS:
                    sell_rem[sell.id] = 0
                    si += 1
                    continue
            qty = round(qty * 1e6) / 1e6

            # 买入方：现金减少，持仓增加（加权成本）
            cash_map[buy.funds_account_id] = cash_map[buy.funds_account_id] - qty * trade_price
            bh = holding_map.get(buy.funds_account_id, {"shares": 0, "costPrice": 0})
            new_shares = bh["shares"] + qty
            new_cost = (
                (bh["shares"] * bh["costPrice"] + qty * trade_price) / new_shares
                if new_shares > 0
                else trade_price
            )
            holding_map[buy.funds_account_id] = {"shares": new_shares, "costPrice": new_cost}
            # 卖出方：现金增加，持仓减少
            cash_map[sell.funds_account_id] = cash_map[sell.funds_account_id] + qty * trade_price
            sh = holding_map.get(sell.funds_account_id, {"shares": 0, "costPrice": 0})
            holding_map[sell.funds_account_id] = {
                "shares": max(0, sh["shares"] - qty),
                "costPrice": sh["costPrice"],
            }

            touched_accounts.add(buy.funds_account_id)
            touched_accounts.add(sell.funds_account_id)
            filled[buy.id] = filled.get(buy.id, 0) + qty
            filled[sell.id] = filled.get(sell.id, 0) + qty

            buy_rem[buy.id] = buy_rem[buy.id] - qty
            sell_rem[sell.id] = sell_rem[sell.id] - qty
            if buy_rem[buy.id] <= EPS:
                bi += 1
            if sell_rem[sell.id] <= EPS:
                si += 1

        candle = build_candle(stock.current_price, price["final"], stock.round + 1, price["theoretical"], cfg["limitPct"])
        new_round = stock.round + 1

        # 现金（绑定字段的账户更新字段值，否则更新账户余额）
        for acc_id, cash in cash_map.items():
            acc = account_objs.get(acc_id)
            if acc is not None and acc.bind_field_id and acc.company_id:
                rounded_cash = round2(cash)
                write_field_value_in_tx(acc.company_id, acc.bind_field_id, str(rounded_cash))
            else:
                StockFundsAccount.objects.filter(pk=acc_id).update(cash_balance=round2(cash))

        # 持仓（仅被撮合涉及的账户）
        for acc_id in touched_accounts:
            h = holding_map.get(acc_id)
            if h is None:
                continue
            if h["shares"] > EPS:
                StockHolding.objects.update_or_create(
                    funds_account_id=acc_id,
                    stock_id=stock.id,
                    defaults={
                        "shares": h["shares"],
                        "cost_price": h["costPrice"],
                        "competition_id": competition_id,
                    },
                )
            else:
                StockHolding.objects.filter(funds_account_id=acc_id, stock_id=stock.id).delete()

        # 订单状态
        for o in orders:
            f = filled.get(o.id, 0)
            if f > EPS:
                remaining = o.quantity - f
                if remaining <= EPS:
                    StockOrder.objects.filter(pk=o.id).update(status="FILLED")
                else:
                    StockOrder.objects.filter(pk=o.id).update(
                        quantity=round(remaining * 1e6) / 1e6,
                        amount=round2(o.price * remaining),
                    )

        # K 线
        StockCandle.objects.create(
            stock_id=stock.id,
            competition_id=competition_id,
            **candle,
        )
        # 股票价 / 轮次
        Stock.objects.filter(pk=stock.id).update(current_price=price["final"], round=new_round)

        return {
            "stockId": stock.id,
            "code": stock.code,
            "round": new_round,
            "skipped": False,
            "matched": match["matched"],
            "tradePrice": trade_price,
            "finalPrice": price["final"],
            "theoretical": price["theoretical"],
            "pressure": price["pressure"],
            "drift": price["drift"],
            "usedTradePrice": price["usedTradePrice"],
            "buyQty": match["totalBuyQty"],
            "sellQty": match["totalSellQty"],
            "buyAmount": match["totalBuyAmount"],
            "sellAmount": match["totalSellAmount"],
            "mmIntervened": mm_intervened,
            "mmOrderCount": mm_count,
            "candle": candle,
        }


# ==================== 推进轮次（主入口） ====================
_advance_locks: dict[int, threading.Lock] = {}
_advance_locks_guard = threading.Lock()


def _try_acquire_advance_lock(competition_id: int) -> bool:
    """尝试获取推进锁（非阻塞），成功返回 True。"""
    with _advance_locks_guard:
        lock = _advance_locks.get(competition_id)
        if lock is None:
            lock = threading.Lock()
            _advance_locks[competition_id] = lock
        return lock.acquire(blocking=False)


def _release_advance_lock(competition_id: int) -> None:
    """释放推进锁。"""
    with _advance_locks_guard:
        lock = _advance_locks.get(competition_id)
        if lock is not None:
            try:
                lock.release()
            except RuntimeError:
                pass


def load_stock_config(competition_id: int) -> dict:
    """解析比赛级 stockConfig（Competition.stock_config），缺失回退默认值。"""
    from apps.competitions.models import Competition

    comp = Competition.objects.filter(pk=competition_id).first()
    raw = getattr(comp, "stock_config", None) if comp else None
    return resolve_stock_config(raw if isinstance(raw, dict) else None)


def advance_round(
    competition_id: int,
    stock_ids: list[int] | None = None,
    market_maker: dict | None = None,
    stock_config: dict | None = None,
) -> dict:
    """推进一轮：对比赛内（或指定）股票逐只撮合、定价、生成 K 线。

    返回 {advanced, skipped, results, marketMakerOrders}。
    """
    from .models import Stock, StockCandle

    if not _try_acquire_advance_lock(competition_id):
        raise BusinessError(
            "轮次推进正在进行中，请稍候", code=409, status_code=409
        )
    try:
        from apps.common.signals import suppress_signals

        qs = Stock.objects.filter(competition_id=competition_id)
        if stock_ids:
            qs = qs.filter(pk__in=stock_ids)
        stocks = list(qs.order_by("code"))
        field_map = resolve_field_value_map(competition_id)
        results: list = []

        base_config = load_stock_config(competition_id)
        if stock_config:
            cfg = dict(base_config)
            cfg.update(stock_config)
        else:
            cfg = base_config
        mm_config = market_maker

        total_mm_orders = 0

        # 屏蔽 per-row 信号：advance_one_stock 内对 Stock/Holding/Order/Candle/FundsAccount
        # 会有数十次 save，仅靠外层 bulk 广播一次即可；审计也在循环结束后统一写入。
        with suppress_signals():
            for stock in stocks:
                apply_pb_round(stock)
                recent = list(
                    StockCandle.objects.filter(
                        stock_id=stock.id, competition_id=competition_id
                    )
                    .order_by("-round")[:3]
                )
                up = 0
                down = 0
                for c in recent:
                    if c.change_pct >= 9.9:
                        up += 1
                        down = 0
                    elif c.change_pct <= -9.9:
                        down += 1
                        up = 0
                    else:
                        break
                r = advance_one_stock(
                    stock, competition_id, field_map, cfg, up, down, mm_config
                )
                if r:
                    results.append(r)
                    total_mm_orders += r.get("mmOrderCount", 0)

        advanced = sum(1 for x in results if not x.get("skipped"))
        # 单次 bulk 广播（替代每只股票逐条事件）
        if advanced > 0:
            from apps.realtime.emit import emit_resource_changed

            emit_resource_changed("stocks", None, competition_id, "bulk")

        return {
            "advanced": advanced,
            "skipped": len(results) - advanced,
            "results": results,
            "marketMakerOrders": total_mm_orders,
        }
    finally:
        _release_advance_lock(competition_id)
