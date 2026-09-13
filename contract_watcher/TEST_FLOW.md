# 端到端测试流程（文字版）

> 目的：验证「合同通过 → 监听程序自动处理 → 原始存档 + 可读翻译版」全链路，
> 以及自动生成/自动改名/热加载等自动化行为。全程**不修改任何代码**。

## 准备（第 0 步）

| 项 | 要求 |
| --- | --- |
| 后端 | 已启动，可访问（本流程用 `http://127.0.0.1:8123`） |
| 账号 | `admin` 且已改密；或任意拥有 contract:view / contractType:view 的账号 |
| 运行目录 | `contract_watcher/`（四个文件齐全：contract_watcher.py / handlers.py / readable.py / README.md） |

## 第 1 步：启动后端（如未启动）

```powershell
cd backend
$env:JWT_SECRET='test-only'
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8123 --noreload
# 另开窗口验证：Invoke-WebRequest http://127.0.0.1:8123/api/health → {"code":0,...}
```

## 第 2 步：先启动监听程序（注意：必须先于造数据）

```powershell
python contract_watcher.py --server http://127.0.0.1:8123 `
    --username admin --password "你的密码" --interval 2 --verbose
```

**预期**（启动瞬间）：
- 无报错退出（若退出：账号密码错 / admin 未改密 → 先去网页改密或用正确账号）；
- 日志出现 `监听启动 ... out=...records backfill=False`；
- 此刻程序已建立进度基线——**之后**新通过的合同才会被处理（这是第 3 步必须晚于本步的原因）。

## 第 3 步：造一条"已执行"测试合同

把 `contract_watcher/_make_test_data.py`（见文末附录）保存后运行：

```powershell
..\backend\.venv\Scripts\python.exe contract_watcher\_make_test_data.py
```

**预期**：输出 `created contract id: 1 type key: test_flow_probe`

## 第 4 步：观察监听程序自动处理（等待 ≤ 2 个轮询周期）

**预期** watcher 窗口依次出现（乱码不影响判断，看关键字即可）：
1. `类型目录发现新 key=test_flow_probe → 已自动生成默认函数`（自动生成 ✅）
2. `已按类型处理 contract=#1 type=test_flow_probe handler=handle_test_flow_probe_passed`（分发 ✅）
3. 若有日志行 `handlers.py 已变更，热加载完成`（热加载 ✅）

## 第 5 步：验证产出文件（核心验收）

检查 `contract_watcher/records/test_flow_probe/` 下应有两个文件：

| 文件 | 内容 |
| --- | --- |
| `contract_1_<时间戳>.json` | 原始全量：`parties`（含 companyName/contractNumber）、`inputs`、`contractType`、`executionLog`、`executionResult` |
| `contract_1_<时间戳>_readable.json` | 翻译可读版，应含：`合同名称=流程测试合同`、`状态=已执行`、`参与方[0].公司=测试公司A`、`填写内容`（label+值）、`落账明细[0]` 含 `字段名/操作/变动前/变动后` |

另确认：`contract_watcher/handlers.py` 末尾出现了自动生成块：

```
# ===== [auto] ContractType.key = test_flow_probe =====
def handle_test_flow_probe_passed(contract: dict, ctx: dict) -> None:
```

## 第 6 步：可选自动化用例

| 用例 | 操作 | 预期 |
| --- | --- | --- |
| 单实例锁 | 再开一个窗口运行同命令 | 第二个实例立即退出并提示端口被占 |
| 修改即生效 | 编辑 `handlers.py` 里 test_flow_probe 函数体（如加一行注释）保存 | 下个轮询日志出现"热加载完成"，原合同处理不受影响 |
| 类型改名自动改名 | 在数据库执行 `UPDATE contract_types SET key='test_flow_probe_v2' WHERE key='test_flow_probe'`（如无 Navicat 可用附录脚本第 2 模式） | 日志出现"类型 key 改名 … → 已自动改名并保留函数体"；handlers.py 标注行与函数名变为 v2 |
| 容错 | 停掉后端 10 秒 | watcher 不退出，日志记录失败；后端恢复后自动继续 |

## 第 7 步：清理（恢复初始状态）

```powershell
# 1) 停监听程序：Ctrl+C（前台）或 Kill 后台任务
# 2) 删除测试数据：运行附录脚本第 2 模式
..\backend\.venv\Scripts\python.exe contract_watcher\_make_test_data.py --clean
# 3) 删除测试产物（或保留当样例）：
Remove-Item -Recurse contract_watcher\records, contract_watcher\data
# 4) 恢复 handlers.py 为干净模板（删除 test_flow_probe 自动生成块即可）
```

## 附录：测试数据脚本 `_make_test_data.py`

```python
# -*- coding: utf-8 -*-
"""测试数据：--clean 删除，否则创建一条已执行测试合同（含一笔落账效果行）。"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings")
import django; django.setup()

from django.utils import timezone
from apps.competitions.models import Competition
from apps.contracts.models import Contract, ContractFieldEffect, ContractType

MARK = "__test_flow__"

def clean():
    ContractFieldEffect.objects.filter(contract__name="流程测试合同").delete()
    Contract.objects.filter(name="流程测试合同").delete()
    ContractType.objects.filter(key__in=["test_flow_probe", "test_flow_probe_v2"]).delete()
    Competition.objects.filter(name=MARK).delete()
    print("cleaned")

def create():
    comp = Competition.objects.create(name=MARK)
    ct = ContractType.objects.create(
        key="test_flow_probe", name="流程测试合同",
        party_roles='[{"role":"甲方","isHost":false,"label":"甲方"},'
                    '{"role":"主办方","isHost":true,"label":"主办方"}]',
        input_schema='[{"key":"amount","label":"采购数量","type":"NUMBER"}]')
    c = Contract.objects.create(
        competition=comp, contract_type=ct, name=ct.name, status="EXECUTED",
        parties='[{"role":"甲方","companyId":1,"contractNumber":"T-001"},'
                '{"role":"主办方","isHost":true}]',
        inputs='{"amount":1000000}',
        execution_log='[{"kind":"FIELD","companyId":1,"fieldKey":"cash",'
                      '"fieldName":"现金","op":"SUB","value":500000,'
                      '"before":1000000,"after":500000}]',
        execution_result='{"fields":{"1:cash":500000},"checks":['
                         '{"kind":"VALUE_COMPARE","label":"金额下限","passed":true,'
                         '"detail":"值1 ≥ 值2：通过"}]}',
        executed_at=timezone.now())
    ContractFieldEffect.objects.create(
        contract=c, company_id=1, industry_field_id=2, field_key="cash",
        field_name="现金", op="SUB",
        value_raw='"500000"', before_raw='"1000000"', after_raw='"500000"')
    print("created contract id:", c.id, "type key:", ct.key)

if __name__ == "__main__":
    (clean if "--clean" in sys.argv else create)()
```

> 提示：可读版文件中"公司名"取自已执行合同的 parties——脚本里 companyId=1 无真实公司时显示 `公司#1` 属正常；如需看公司名，先在系统里建公司并把 parties 的 companyId 换成真实 ID。
