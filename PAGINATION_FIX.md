# 分页翻页功能修复

## 问题描述

合同管理界面无法正常翻页，点击页码或下一页按钮没有反应。

## 根本原因

分页组件的`@current-change`事件处理函数没有正确接收和处理页码参数。

1. **合同管理页面**：`handlePageChange`函数没有接收页码参数
2. **账户管理页面**：`loadSystemUsers`和`loadCompetitionUsers`函数没有接收页码参数

## 解决方案

修改分页事件处理函数，使其能够接收和处理页码参数。

## 修复的文件

1. `frontend/src/views/data-management/ContractManageView.vue`
2. `frontend/src/views/account-management/AccountManagementView.vue`

## 具体修改

### 1. 合同管理页面

```javascript
// 修复前
function handlePageChange() {
  loadContracts();
}

// 修复后
function handlePageChange(page: number) {
  currentPage.value = page;
  loadContracts();
}
```

### 2. 账户管理页面

```javascript
// 修复前
async function loadSystemUsers() {
  // ...
}

async function loadCompetitionUsers() {
  // ...
}

// 修复后
async function loadSystemUsers(page?: number) {
  if (page !== undefined) {
    systemPage.value = page;
  }
  // ...
}

async function loadCompetitionUsers(page?: number) {
  if (page !== undefined) {
    competitionPage.value = page;
  }
  // ...
}
```

## 验证

修复后，用户可以：
1. 点击页码跳转到指定页
2. 点击上一页/下一页按钮翻页
3. 每页显示100个合同/账户
4. 看到总记录数和当前页码

## 技术细节

### Element Plus分页组件事件

Element Plus的`el-pagination`组件提供以下事件：
- `current-change`：页码改变时触发，参数为新的页码
- `size-change`：每页条数改变时触发，参数为新的每页条数

### 事件处理函数参数

当使用`@current-change="handlePageChange"`时，Element Plus会自动将新的页码作为参数传递给`handlePageChange`函数。

## 预防措施

1. **事件处理函数参数**：确保事件处理函数能够正确接收和处理参数
2. **测试覆盖**：确保有测试覆盖分页功能，包括翻页操作
3. **代码审查**：在代码审查时检查事件处理函数的参数处理

## 相关文档

- Element Plus文档：[Pagination](https://element-plus.org/en-US/component/pagination.html)
- 项目中的其他分页实现：检查是否有类似问题