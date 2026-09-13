# contract_watcher 重测报告（后端更新后 · 2026-09-10）

- 被测对象：`contract_watcher/`（`contract_watcher.py` / `handlers.py` / `readable.py` 及文档）
- 后端版本：更新后的项目（HEAD `97e117e`；本次更新含 `widget_packages` 新 app 迁移、`contracts/engine.py` 节点名输出端口、前端合约图布局修复）
- 范围：**仅测试 watcher**，未测试 `shang.py` 相关（bookkeeping_example 未参与）
- 结论：**离线自测 11/11 通过；端到端全链路通过**；发现 3 处可改进点（见 §3），未改动任何代码

## 1. 离线自测（`selftest.py`，11/11 PASS）

| 项 | 结果 |
| --- | --- |
| 三个 py 文件语法编译 | ✅ |
| 新 key 自动生成默认函数 + 幂等 | ✅ |
| 文档字符串中的 `@register` 示例不被误判 | ✅ |
| 类型改名：更新标注行+函数名且**保留函数体** | ✅ |
| 注册表加载（按标注行解析 → 函数） | ✅ |
| `translate_contract` 四大块与中文转换（状态/公司/数量千分位/字段名/操作词） | ✅ |
| 自定义翻译器 `register_translator` 生效 | ✅ |
| `default_archive` 产出**原始 + 可读**两个文件 | ✅ |
| 分发：注册函数优先 | ✅ |
| 分发：未注册类型走默认存档 | ✅ |

## 2. 端到端（对更新后的后端实测）

环境：后端 `runserver 127.0.0.1:8123`（HEAD 代码，`migrate` 已应用新迁移），watcher `--interval 2`。

| 步骤 | 实测结果 |
| --- | --- |
| 启动与登录 | ✅ 登录成功、监听启动、建立基线 |
| 新建合同类型 `e2e_watcher_recheck` | ✅ 日志：`类型目录发现新 key=... → 已自动生成默认函数` |
| 合同通过（#3） | ✅ 日志：`已按类型处理 contract=#3 type=... handler=handle_e2e_watcher_recheck_passed` |
| 产出文件 | ✅ `records/<key>/contract_3_*.json` + `..._readable.json` |
| handlers.py 热加载 | ✅ 日志：`handlers.py 已变更，热加载完成` |
| **类型改名**（DB 中改为 `..._v2`） | ✅ 日志：`类型 key 改名 ... → ...（typeId=3）→ 已自动改名并保留函数体`；文件中标注行与函数名已同步为 `_v2` |
| 改名后再通过合同（#4） | ✅ 日志：`已按类型处理 contract=#4 type=..._v2 handler=handle_..._v2_passed`；文件落在新 key 目录 |
| 可读文件内容 | ✅ 中文结构正确（合同ID/状态/参与方/填写内容/前置检查/落账明细） |
| 收尾 | ✅ 测试数据已清理、watcher/handlers.py 已还原（SHA 恢复 `7F605C58`）、`data/` 状态已清 |

证据保留在 `test_run_recheck/`：`records/`（4 个结果文件）、`watcher.log`（完整运行日志）、
`handlers.before.py`（测试前模板）、`handlers.generated_after_test.py`（自动生成+改名后的文件）。

## 3. 发现的改进点（本次未修改代码）

| # | 现象 | 证据 | 建议 |
| --- | --- | --- | --- |
| ① | **时间显示未本地化**：接口返回 UTC（`2026-09-10T15:20:46.731818Z`），`readable.py` 直接截断前 19 字符展示为 `2026-09-10 15:20:46`，比北京时间早 **8 小时**，且无时区标注 | `contract_4_*_readable.json` 的 `执行时间` 对比原值 `executedAt` 与系统时间 23:20 | 在 `readable.py` 内解析 ISO 并转换为本地时区（或至少追加 `UTC` 标注）；`DATA_GUIDE.md` 可同步说明 |
| ② | **参与方"公司"兜底不一致**：`companyId` 无法解析时 `参与方.公司` 为 `null`，而 `落账明细.公司` 会兜底为 `公司#<id>` | 同上文件：参与方 `公司: null` vs 落账明细设计中的 `公司#id` | 统一兜底展示（如 `公司#1`），避免阅读时误以为无公司 |
| ③ | **改名后函数内 docstring 仍保留旧 key 文案**（仅标注行与函数名被替换） | `handlers.py`：`def handle_..._v2_passed` 内的 `"""e2e_watcher_recheck 类型…"""` | 改名时一并替换该 docstring 中的 key（属文档性瑕疵，不影响运行） |

## 4. 复跑方式

```powershell
# 离线自测（无需后端）
python contract_watcher/selftest.py

# 端到端（需后端；--out-dir 指向测试目录，避免污染正式 records/）
python contract_watcher/contract_watcher.py --server http://127.0.0.1:8000 `
    --username admin --password "口令" --interval 2 --verbose `
    --out-dir contract_watcher/test_run_recheck/records
```

> 注：watcher 运行依赖后端 `GET /api/contract-types`、`GET /api/contracts?status=EXECUTED`、`GET /api/contracts/:id`，
> 本次更新未改动这些接口，实测兼容。
