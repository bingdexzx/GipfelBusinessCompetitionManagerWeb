# 分页显示修复

## 问题描述

合同管理界面只能选择每页显示几个，无法选择页数，也就是只能显示前100个合同。用户希望：
1. 每页显示100个合同
2. 能够显示页数，让用户可以翻页查看所有合同

## 根本原因

在分页组件中，使用了`v-if="totalContracts > pageSize"`条件，只有当总记录数大于每页显示数量时才显示分页组件。这导致当总记录数小于等于每页显示数量时，分页组件不显示，用户无法翻页。

## 解决方案

修改分页组件的显示条件，从`v-if="totalContracts > pageSize"`改为`v-if="totalContracts > 0"`，确保只要有记录就显示分页组件。

## 修复的文件

1. `frontend/src/views/data-management/ContractManageView.vue`：第162行
2. `frontend/src/views/account-management/AccountManagementView.vue`：第71行和第143行

## 验证

修复后，用户可以在合同管理界面和账户管理界面：
1. 每页显示100个合同/账户
2. 看到分页组件，可以翻页查看所有合同/账户
3. 看到总记录数和当前页码

## 技术细节

### 分页组件显示条件

```html
<!-- 修复前 -->
<el-pagination
  v-if="totalContracts > pageSize"
  ...
/>

<!-- 修复后 -->
<el-pagination
  v-if="totalContracts > 0"
  ...
/>
```

### 分页选项

```javascript
// 分页选项
const pageSizeOptions = [10, 20, 50, 100, 200];
```

## 预防措施

1. **用户体验**：确保分页组件始终显示，让用户知道有更多记录
2. **一致性**：所有分页组件使用相同的显示条件
3. **测试覆盖**：确保有测试覆盖分页功能，包括边界情况

## 相关文档

- Element Plus文档：[Pagination](https://element-plus.org/en-US/component/pagination.html)
- 项目中的其他分页实现：检查是否有类似问题