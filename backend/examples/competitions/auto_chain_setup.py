# -*- coding: utf-8 -*-
"""汽车产业链测试赛 · 建场比赛的准备与体检脚本（幂等，可反复执行）。

只做五件事，都不修改任何业务逻辑：

    1. 新建（或复用）比赛「2026 汽车产业链测试赛」，打印比赛 id；
    2. （可选）重算本场公司的「计算字段」（合同引擎不触发计算字段重算，见函数说明）；
    3. （可选）比赛内消息去重（重复导入建包脚本会多建一套消息）；
    4. （可选）给本场测试账号设置一个**已知密码**，方便直接登录测试；
    5. （可选）打印本场比赛的准备情况体检摘要（含「股票系统未被写入」的确认）。

用法
----

    cd backend

    # 1) 建比赛（已存在则复用），并打印后续导入命令
    .\\.venv\\Scripts\\python.exe examples/competitions/auto_chain_setup.py

    # 2) 导入完成后再跑一次，给测试账号设置已知密码（仅本地测试用！）
    .\\.venv\\Scripts\\python.exe examples/competitions/auto_chain_setup.py --passwords

    # 3) 查看准备情况体检摘要
    .\\.venv\\Scripts\\python.exe examples/competitions/auto_chain_setup.py --status

    # 4) 导入完成后的收尾：重算计算字段 + 消息去重 + 设置测试账号密码 + 打印体检摘要
    .\\.venv\\Scripts\\python.exe examples/competitions/auto_chain_setup.py --finish

> ⚠️ `--passwords` 会把 `auto_player_*` / `auto_referee` 这些**测试账号**的密码设成同一个
> 已知口令，并关闭「首次登录强制改密」。这是为了本地联调方便，**不要在生产比赛里这么做**。
"""
from __future__ import annotations

import os
import sys

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings")

import django  # noqa: E402

django.setup()

from apps.competitions.models import Competition  # noqa: E402

#: 比赛名（与建包脚本 `auto_chain_competition.py` 里的名字保持一致）
COMPETITION_NAME = "2026 汽车产业链测试赛"

#: 本场测试账号（由建包脚本的 users 资源创建）
TEST_USERNAMES = ("auto_player_a", "auto_player_b", "auto_player_c", "auto_referee")

#: 统一测试口令（仅本地测试；生产比赛请用「账号管理」里的重置密码）
TEST_PASSWORD = "Auto@Chain2026"


def main(argv: list[str]) -> int:
    finish = "--finish" in argv
    want_passwords = finish or "--passwords" in argv
    want_status = finish or "--status" in argv
    want_recompute = finish or "--recompute-calc" in argv
    want_dedupe = finish or "--dedupe-messages" in argv

    competition = ensure_competition()
    print(f"比赛：#{competition.id} 「{competition.name}」（状态 {competition.status}）")

    if want_recompute:
        recompute_calc_fields(competition)
    if want_dedupe:
        dedupe_messages(competition)
    if want_passwords:
        set_test_passwords(competition)
    if want_status:
        print_status(competition)
    if not (want_passwords or want_status or want_recompute or want_dedupe):
        print_next_steps(competition.id)
    return 0


def dedupe_messages(competition: Competition) -> None:
    """同一标题的比赛内消息只保留最早一条。

    导入引擎对「比赛内消息」不做幂等判重（每次导入都会新建一批），
    所以第二次跑建包脚本（例如为了回填总览卡片字段 id）会多出一整套消息，
    这里把它们清掉，保持比赛内容干净。
    """
    from apps.messages.models import Message

    seen: dict[str, int] = {}
    duplicates: list[int] = []
    for msg_id, title in Message.objects.filter(competition_id=competition.id).order_by("id").values_list("id", "title"):
        if title in seen:
            duplicates.append(msg_id)
        else:
            seen[title] = msg_id
    if duplicates:
        Message.objects.filter(id__in=duplicates).delete()
    print(f"  消息去重：删除重复 {len(duplicates)} 条，保留 {len(seen)} 条")


def recompute_calc_fields(competition: Competition) -> None:
    """重算本场比赛所有公司的「计算字段」（如 货币资金 = 现金 + 银行存款）。

    ⚠️ 既有语义：计算字段只在「通过接口写公司字段」与「财年开始定时器」时重算，
    合同引擎执行落账**不会**触发重算。所以导入后、以及每轮合同执行后，
    跑一次本函数可以让计算字段跟上最新值。
    """
    from apps.companies.models import Company
    from apps.company_fields.calc import recompute_calc_fields as recompute

    count = 0
    for company_id in Company.objects.filter(competition_id=competition.id).values_list("id", flat=True):
        recompute(company_id)
        count += 1
    print(f"  已重算 {count} 家公司的计算字段（货币资金 = 现金 + 银行存款）")


def ensure_competition() -> Competition:
    """新建比赛；同名比赛已存在时直接复用（不修改名字与状态）。"""
    competition = Competition.objects.filter(name=COMPETITION_NAME).first()
    if competition is not None:
        return competition
    return Competition.objects.create(name=COMPETITION_NAME, status="ACTIVE")


def set_test_passwords(competition: Competition) -> None:
    """给测试账号设置已知口令（仅本地测试用）。"""
    from apps.users.models import User

    found = 0
    for username in TEST_USERNAMES:
        user = User.objects.filter(username=username).first()
        if user is None:
            print(f"  · 账号 {username} 还不存在（先导入建包脚本的「参赛账号与范围」分组）")
            continue
        user.set_password(TEST_PASSWORD)
        user.must_change_password = False
        # 递增 token 版本，让此前签发的 token 立即失效（与改密逻辑一致）
        user.token_version = (user.token_version or 0) + 1
        user.competition = competition
        user.save(update_fields=["password_hash", "must_change_password", "token_version",
                                 "competition", "updated_at"])
        found += 1
    print(f"  已重置 {found}/{len(TEST_USERNAMES)} 个测试账号的密码为：{TEST_PASSWORD}")
    print("  ⚠️ 仅限本地测试环境；正式比赛请走「账号管理 → 重置密码」")


def print_status(competition: Competition) -> None:
    """打印本场比赛的准备情况体检摘要。"""
    from apps.companies.models import Company
    from apps.contracts.models import Contract, ContractType
    from apps.industry_types.models import IndustryField, IndustryType
    from apps.maps.models import MapEdge, MapNode
    from apps.materials.models import Material
    from apps.parts.models import Part, PartMaterial
    from apps.products.models import Product, ProductPart
    from apps.stock.models import Stock, StockFundsAccount
    from apps.users.models import User

    cid = competition.id
    companies = Company.objects.filter(competition_id=cid)
    industry_ids = list(companies.values_list("industry_type_id", flat=True).distinct())
    industry_ids = [i for i in industry_ids if i]
    print("\n=== 比赛准备体检 ===")
    print(f"  产业类型        {IndustryType.objects.filter(id__in=industry_ids).count()} 个"
          f"（{('、'.join(IndustryType.objects.filter(id__in=industry_ids).values_list('name', flat=True))) }）")
    print(f"  产业字段        {IndustryField.objects.filter(industry_type_id__in=industry_ids).count()} 条")
    print(f"  公司            {companies.count()} 家")
    role_counts: dict[str, int] = {}
    for name, it_id in companies.values_list("name", "industry_type_id"):
        it_name = IndustryType.objects.filter(id=it_id).values_list("name", flat=True).first() or "未绑定"
        role_counts[it_name] = role_counts.get(it_name, 0) + 1
    for it_name, count in role_counts.items():
        print(f"    - {it_name}：{count} 家")
    print(f"  地图            节点 {MapNode.objects.filter(competition_id=cid).count()} 个 / "
          f"连线 {MapEdge.objects.filter(competition_id=cid).count()} 条")
    print(f"  物资            原料 {Material.objects.filter(competition_id=cid).count()} / "
          f"零件 {Part.objects.filter(competition_id=cid).count()} "
          f"（配比 {PartMaterial.objects.filter(part__competition_id=cid).count()}）/ "
          f"产品 {Product.objects.filter(competition_id=cid).count()} "
          f"（配比 {ProductPart.objects.filter(product__competition_id=cid).count()}）")
    print(f"  合同类型（全局）  {ContractType.objects.count()} 个")
    for ct in ContractType.objects.order_by("key"):
        print(f"    - {ct.key}（{ct.name}）启用={ct.enabled}")
    print(f"  合同实例        {Contract.objects.filter(competition_id=cid).count()} 份")
    print(f"  参赛账号        {User.objects.filter(competition_id=cid).count()} 个")
    stocks = Stock.objects.filter(competition_id=cid).count()
    accounts = StockFundsAccount.objects.filter(competition_id=cid).count()
    print(f"  股票系统        股票 {stocks} 只 / 资金账户 {accounts} 个"
          f"{'（✅ 未被写入，符合「不动股票系统」要求）' if stocks == 0 and accounts == 0 else '（⚠️ 存在股票数据）'}")


def print_next_steps(cid: int) -> None:
    print("\n后续命令（在 backend 目录下执行）：")
    print("  1) 预演导入（事务回滚，不落库）")
    print(f"     .\\.venv\\Scripts\\python.exe manage.py build_competition "
          f"examples/competitions/auto_chain_competition.py --competition {cid} --dry-run")
    print("  2) 真正导入")
    print(f"     .\\.venv\\Scripts\\python.exe manage.py build_competition "
          f"examples/competitions/auto_chain_competition.py --competition {cid}")
    print("  3) 回填总览卡片字段 id（第二遍导入，覆盖模式）")
    print(f"     $env:AUTO_CHAIN_COMPETITION_ID='{cid}'")
    print(f"     .\\.venv\\Scripts\\python.exe manage.py build_competition "
          f"examples/competitions/auto_chain_competition.py --competition {cid} "
          f"--mode overwrite --allow-non-empty")
    print("  4) 合同类型体检 + 试算 + 导入")
    print(f"     .\\.venv\\Scripts\\python.exe manage.py build_contract_types "
          f"examples/contracts/auto_chain_contracts.py --competition {cid} --check --trial")
    print(f"     .\\.venv\\Scripts\\python.exe manage.py build_contract_types "
          f"examples/contracts/auto_chain_contracts.py --competition {cid} --import")
    print("  5) 冒烟：把三份预置合同喂给真实引擎跑一遍（事务回滚，不落库）")
    print("     .\\.venv\\Scripts\\python.exe examples/competitions/auto_chain_smoke.py --competition "
          f"{cid}")
    print("  6) 收尾：重算计算字段 + 测试账号密码 + 体检摘要")
    print("     .\\.venv\\Scripts\\python.exe examples/competitions/auto_chain_setup.py --finish")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
