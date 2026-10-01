# build_candle函数类型错误修复

## 问题描述

在股票轮次推进时，出现以下错误：
```
TypeError: unsupported operand type(s) for /: 'decimal.Decimal' and 'float'
```

错误发生在`backend/apps/stock/engine.py`的第283行：
```python
change_pct_abs = abs(close - open_) / price if price > 0 else 0
```

## 根本原因

在`build_candle`函数中，`open_`和`close`参数可能接收`decimal.Decimal`类型（来自数据库的`DecimalField`），而`price`变量被转换为`float`类型。当进行`abs(close - open_)`运算时，如果`close`和`open_`都是`Decimal`类型，结果也是`Decimal`类型，然后与`float`类型的`price`进行除法运算时引发`TypeError`。

## 解决方案

在`build_candle`函数开头，将`open_`和`close`参数显式转换为`float`类型：

```python
# 修复前
def build_candle(
    open_: float,
    close: float,
    round_: int,
    theoretical: float | None = None,
    limit_pct: float = 0.1,
    upper_pct: float | None = None,
    lower_pct: float | None = None,
    trade_high: float | None = None,
    trade_low: float | None = None,
) -> dict:
    """构建 K 线数据。

    内部保持 float 运算（影线是图形指标，精度足够），
    仅在最后用 round2 截断到 0.01。
    upper_pct / lower_pct：非对称限幅（防连板 S10），缺省回落 limit_pct。
    trade_high / trade_low：本轮实际成交价的最高/最低——真实挂单成交
    可能超出「body + 理论价 + 噪声影线」的合成范围（如买卖单挂价贴限价），
    K 线必须如实反映（仍夹在涨跌停限幅内）。
    """
    up_pct = upper_pct if upper_pct is not None else limit_pct
    dn_pct = lower_pct if lower_pct is not None else limit_pct
    upper = float(round2(Decimal(str(open_)) * (Decimal("1") + Decimal(str(up_pct)))))
    lower = float(round2(Decimal(str(open_)) * (Decimal("1") - Decimal(str(dn_pct)))))
    range_ = upper - lower

    # body_high/low 可能是 Decimal（来自 ORM/price["final"]），统一转 float 后再计算
    body_high = float(max(open_, close))
    body_low = float(min(open_, close))

# 修复后
def build_candle(
    open_: float,
    close: float,
    round_: int,
    theoretical: float | None = None,
    limit_pct: float = 0.1,
    upper_pct: float | None = None,
    lower_pct: float | None = None,
    trade_high: float | None = None,
    trade_low: float | None = None,
) -> dict:
    """构建 K 线数据。

    内部保持 float 运算（影线是图形指标，精度足够），
    仅在最后用 round2 截断到 0.01。
    upper_pct / lower_pct：非对称限幅（防连板 S10），缺省回落 limit_pct。
    trade_high / trade_low：本轮实际成交价的最高/最低——真实挂单成交
    可能超出「body + 理论价 + 噪声影线」的合成范围（如买卖单挂价贴限价），
    K 线必须如实反映（仍夹在涨跌停限幅内）。
    """
    # 确保 open_ 和 close 是 float 类型（避免 Decimal 和 float 混合运算）
    open_ = float(open_)
    close = float(close)
    
    up_pct = upper_pct if upper_pct is not None else limit_pct
    dn_pct = lower_pct if lower_pct is not None else limit_pct
    upper = float(round2(Decimal(str(open_)) * (Decimal("1") + Decimal(str(up_pct)))))
    lower = float(round2(Decimal(str(open_)) * (Decimal("1") - Decimal(str(dn_pct)))))
    range_ = upper - lower

    # body_high/low 可能是 Decimal（来自 ORM/price["final"]），统一转 float 后再计算
    body_high = float(max(open_, close))
    body_low = float(min(open_, close))
```

## 修复的文件

- `backend/apps/stock/engine.py`：第225-253行

## 影响范围

这个修复影响所有调用`build_candle`函数的地方：
1. `_advance_round_flat`函数（第1235-1236行）
2. `advance_one_stock`函数（第1649-1654行）

## 验证

修复后，`build_candle`函数可以正确处理以下类型组合：
- `open_`和`close`都是`float`类型
- `open_`和`close`都是`Decimal`类型
- `open_`是`Decimal`类型，`close`是`float`类型
- `open_`是`float`类型，`close`是`Decimal`类型

## 技术细节

### 为什么会出现类型不匹配？

1. **数据库模型定义**：`Stock.current_price`字段是`DecimalField`，从数据库读取时返回`Decimal`类型
2. **函数调用**：`build_candle`函数接收`open_`和`close`参数，这些参数可能来自：
   - `stock.current_price`（`Decimal`类型）
   - `price["final"]`（可能是`Decimal`类型）
   - 其他计算结果（可能是`float`类型）
3. **混合运算**：当`Decimal`和`float`类型混合运算时，Python会抛出`TypeError`

### 为什么选择转换为`float`而不是`Decimal`？

1. **函数设计**：`build_candle`函数内部使用`float`进行计算（影线是图形指标，精度足够）
2. **性能考虑**：`float`运算比`Decimal`运算更快
3. **兼容性**：函数内部已经有多处`float()`转换，保持一致性

## 预防措施

1. **类型提示**：使用类型提示明确参数类型
2. **参数验证**：在函数开头验证参数类型
3. **测试覆盖**：确保有测试覆盖不同类型的参数组合
4. **代码审查**：在代码审查时检查类型兼容性

## 相关文档

- Python文档：[decimal.Decimal](https://docs.python.org/3/library/decimal.html)
- Django文档：[DecimalField](https://docs.djangoproject.com/en/stable/ref/models/fields/#decimalfield)
- 项目中的其他类型转换：检查是否有类似问题