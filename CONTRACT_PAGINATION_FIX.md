# 合同管理界面分页修复

## 问题描述

合同管理界面只能选择每页显示几个，无法选择页数，也就是只能显示前100个合同。

## 根本原因

在合同管理界面中，`pageSizeOptions`被定义为`[10, 20, 50, 100]`，最大值是100。后端支持最大200的分页大小（`MAX_PAGE_SIZE = 200`），但前端只提供了最大100的选项。

## 解决方案

将`pageSizeOptions`中的最大值从100改为200：

```javascript
// 修复前
const pageSizeOptions = [10, 20, 50, 100];

// 修复后
const pageSizeOptions = [10, 20, 50, 100, 200];
```

## 修复的文件

1. `frontend/src/views/data-management/ContractManageView.vue`：第770行
2. `frontend/src/views/account-management/AccountManagementView.vue`：第264行

## 验证

修复后，用户可以在合同管理界面和账户管理界面选择每页显示200条记录，从而查看所有合同。

## 技术细节

### 后端分页限制

在`backend/apps/common/pagination.py`中，`MAX_PAGE_SIZE`被设置为200：

```python
MAX_PAGE_SIZE = 200
DEFAULT_PAGE = 1
DEFAULT_PAGE_SIZE = 50
```

### 前端分页选项

前端的分页选项应该与后端的限制保持一致，以提供最佳的用户体验。

## 预防措施

1. **前后端一致性**：确保前端的分页选项与后端的限制保持一致
2. **文档更新**：在文档中明确分页大小的限制
3. **测试覆盖**：确保有测试覆盖分页功能

## 相关文档

- Django REST Framework文档：[Pagination](https://www.django-rest-framework.org/api-guide/pagination/)
- Element Plus文档：[Pagination](https://element-plus.org/en-US/component/pagination.html)
- 项目中的其他分页实现：检查是否有类似问题