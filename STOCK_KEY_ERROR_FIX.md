# 股票创建KeyError修复

## 问题描述

在创建股票时，出现以下错误：
```
KeyError: 'code'
```

错误发生在`backend/apps/stock/serializers.py`的第152行：
```python
if Stock.objects.filter(competition_id=cid, code=validated_data["code"]).exists():
```

## 根本原因

在`StockSerializer`中，`code`字段被错误地设置为`read_only=True`：
```python
code = serializers.CharField(max_length=64, trim_whitespace=True, read_only=True)
```

在Django REST Framework中，`read_only=True`的字段不会被包含在`validated_data`中，因此在`create`方法中访问`validated_data["code"]`会引发`KeyError`。

## 解决方案

将`code`字段从`read_only=True`改为默认的`required=True`：
```python
# 修复前
code = serializers.CharField(max_length=64, trim_whitespace=True, read_only=True)

# 修复后
code = serializers.CharField(max_length=64, trim_whitespace=True)
```

## 修复的文件

- `backend/apps/stock/serializers.py`：第97行

## 验证

修复后，`code`字段将包含在`validated_data`中，`create`方法可以正常访问`validated_data["code"]`。

## 相关字段说明

在`StockSerializer`中，以下字段被正确地设置为`read_only=True`：
- `id`：数据库自动生成
- `initPrice`：由`compute_init_price`计算生成
- `currentPrice`：初始值等于`initPrice`
- `round`：初始值为0
- `createdAt`：数据库自动生成
- `updatedAt`：数据库自动生成

这些字段在创建时由后端自动生成，不应该由用户提供，因此设置为`read_only=True`是正确的。

## 测试

运行测试脚本验证修复：
```bash
cd backend
python test_stock_fix.py
```

测试结果显示：
- `StockSerializer`中`code`字段的`read_only`属性已设置为`False`
- 即使验证失败（如`competitionId`不存在），也不会出现`KeyError`

## 预防措施

1. **字段定义审查**：在定义serializer字段时，仔细考虑哪些字段应该是`read_only=True`
2. **测试覆盖**：确保有测试覆盖创建操作，包括字段验证
3. **代码审查**：在代码审查时检查`read_only`字段是否在`create`方法中被错误访问

## 相关文档

- Django REST Framework文档：[Serializer Fields](https://www.django-rest-framework.org/api-guide/fields/#read_only)
- 项目中的其他serializer：检查是否有类似问题