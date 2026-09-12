"""`manage.py build_contract_types` —— 用代码脚本创建/更新合同类型。

四种用途（可组合）：

    # 1) 静态体检（纯只读；不写库、不跑引擎）
    python manage.py build_contract_types contracts_src/ --competition 7 --check

    # 2) 试算验证（复用合同引擎，事务整体回滚，不落任何数据）
    python manage.py build_contract_types contracts_src/ --competition 7 --trial

    # 3) 预演导入（只打印将要写入的四份 JSON 差异）
    python manage.py build_contract_types contracts_src/ --competition 7 --dry-run

    # 4) 真正导入（复用 ContractTypeSerializer，与前端保存走同一条路径）
    python manage.py build_contract_types contracts_src/ --competition 7 --import

    # 5) 导出：把已有合同类型反解成具名效果，打印出来对照（不写任何东西）
    python manage.py build_contract_types --export steel-sale
    python manage.py build_contract_types --export --all

脚本约定
--------
脚本是一个普通 Python 文件，包含下列任意一种即可（按顺序查找）：

    def build():   return ct | [ct, ct2] | {"key": ct, ...}     # 推荐
    CONTRACTS = [ct, ct2]                                       # 模块级列表
    LAST_TYPES                                                  # 兜底：脚本里创建过的全部

脚本用绝对导入：`from apps.contracts.builder import ContractType, snapshot`

退出码：0 成功；1 体检有阻断项 / 试算失败；2 参数或脚本错误。
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.contracts.builder import (
    AGGREGATE_INPUT_TYPES,
    ERROR,
    ContractType,
    Report,
    check as static_check,
    snapshot,
)
from apps.contracts.builder.errors import BuildError, ContractBuilderError
from apps.contracts.builder.effects import Effect, effects_from_specs
from apps.contracts.models import ContractType as ContractTypeModel


class Command(BaseCommand):
    help = "用 Python 脚本创建/更新合同类型（含静态体检与试算验证）"

    def add_arguments(self, parser) -> None:
        parser.add_argument("source", nargs="?", help="合同类型脚本（.py）或包含脚本的目录")
        parser.add_argument("--competition", type=int, default=None, help="比赛 id（体检/试算需要）")
        parser.add_argument("--check", action="store_true", help="只做静态体检（默认：没有其它动作时就是体检）")
        parser.add_argument("--trial", action="store_true", help="对真实公司逐个试算（事务回滚，不落库）")
        parser.add_argument("--dry-run", action="store_true", help="预演导入：打印将写入的内容，不落库")
        parser.add_argument(
            "--import", dest="do_import", action="store_true", help="真正写入数据库（新增或按 key 更新）"
        )
        parser.add_argument("--export", nargs="?", const="", default=None, metavar="KEY",
                            help="导出已有合同类型的具名效果（不给 key 时需配合 --all）")
        parser.add_argument("--all", action="store_true", help="配合 --export：导出全部合同类型")
        parser.add_argument("--json", action="store_true", help="以 JSON 输出（便于接入 CI）")
        parser.add_argument("--strict-types", action="store_true",
                            help="体检时对「效果 × 字段类型」采用严格判定（各产业类型字段类型必须完全一致）")
        parser.add_argument("--verbose", action="store_true", help="打印更多细节（含生成的四份 JSON）")

    # ==================== 入口 ====================

    def handle(self, *args, **options) -> None:
        if options["export"] is not None:
            self._export(options)
            return

        source = options["source"]
        if not source:
            raise CommandError(
                "请给出脚本路径；或使用 --export <key> 导出已有合同类型"
            )
        path = Path(source).expanduser()
        if not path.exists():
            raise CommandError(f"路径不存在：{path}")

        types = self._load_types(path)
        if not types:
            raise CommandError(f"{path} 里没有产出任何合同类型")

        snap = snapshot(options["competition"]) if options["competition"] else None
        self.stdout.write(f"共 {len(types)} 个合同类型" + (f"，比赛 #{options['competition']}" if snap else ""))

        reports: list[Report] = []
        for ct in types:
            reports.append(static_check(ct, snap=snap, strict_effect_types=bool(options["strict_types"])))

        if options["json"]:
            self.stdout.write(json.dumps([r.to_dict() for r in reports], ensure_ascii=False, indent=2))
        else:
            for r in reports:
                self.stdout.write("")
                self.stdout.write(r.render())

        blocked = [r for r in reports if not r.ok]
        if options["verbose"]:
            for ct in types:
                self.stdout.write("")
                self.stdout.write(self.style.HTTP_INFO(f"=== {ct.key} 编译产物 ==="))
                self.stdout.write(ct.to_json())

        do_trial = options["trial"]
        do_dry = options["dry_run"]
        do_import = options["do_import"]
        if not (do_trial or do_dry or do_import):
            # 只体检
            if blocked:
                raise CommandError(f"{len(blocked)} 个合同类型存在阻断项，请先修复")
            return

        if do_trial:
            if snap is None:
                raise CommandError("--trial 需要 --competition")
            trial_failed = self._trial_all(types, snap, verbose=options["verbose"])
            if trial_failed:
                raise CommandError(f"{len(trial_failed)} 个合同类型的试算未全部通过")

        if blocked:
            raise CommandError(f"{len(blocked)} 个合同类型存在阻断项，已中止写入")

        if do_dry or do_import:
            self._write_all(types, dry_run=do_dry)

    # ==================== 脚本加载 ====================

    def _load_types(self, path: Path) -> list[ContractType]:
        files = self._script_files(path)
        out: list[ContractType] = []
        seen: dict[str, Path] = {}
        for f in files:
            for ct in self._run_script(f):
                if ct.key in seen:
                    raise CommandError(
                        f"合同类型 key「{ct.key}」重复定义：{seen[ct.key]} 与 {f}"
                    )
                seen[ct.key] = f
                out.append(ct)
        return out

    @staticmethod
    def _script_files(path: Path) -> list[Path]:
        if path.is_dir():
            files = sorted(p for p in path.rglob("*.py") if not p.name.startswith("_"))
            if not files:
                raise CommandError(f"目录里没有 .py 脚本：{path}")
            return files
        if path.suffix.lower() != ".py":
            raise CommandError(f"脚本必须是 .py 文件：{path}")
        return [path]

    def _run_script(self, path: Path) -> list[ContractType]:
        import apps.contracts.builder as pkg

        spec = importlib.util.spec_from_file_location(f"_ct_script_{path.stem}", path)
        if spec is None or spec.loader is None:
            raise CommandError(f"无法加载脚本：{path}")
        module = importlib.util.module_from_spec(spec)

        # 兜底：记录脚本里创建过的全部合同类型（脚本只写表达式也能取到）
        registry: list[ContractType] = []
        original_init = pkg.ContractType.__init__

        def patched_init(self, *a, **kw):  # type: ignore[no-untyped-def]
            original_init(self, *a, **kw)
            registry.append(self)

        pkg.ContractType.__init__ = patched_init  # type: ignore[assignment]
        try:
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
        except ContractBuilderError as e:
            raise CommandError(f"{path.name}：{e}")
        except Exception as e:  # noqa: BLE001 - 脚本错误直接暴露
            import traceback

            self.stderr.write(traceback.format_exc())
            raise CommandError(f"{path.name} 执行失败：{type(e).__name__}: {e}")
        finally:
            pkg.ContractType.__init__ = original_init  # type: ignore[assignment]

        produced = getattr(module, "CONTRACTS", None)
        build_fn = getattr(module, "build", None)
        if callable(build_fn):
            produced = build_fn()
        elif produced is None:
            produced = registry or None

        return self._coerce_types(produced, path)

    @staticmethod
    def _coerce_types(produced, path: Path) -> list[ContractType]:
        if produced is None:
            raise CommandError(
                f"{path.name} 没有产出合同类型：请定义 build() 函数或模块级 CONTRACTS"
            )
        if isinstance(produced, ContractType):
            return [produced]
        if isinstance(produced, dict):
            out = []
            for k, v in produced.items():
                if not isinstance(v, ContractType):
                    raise CommandError(f"{path.name}：build() 字典里的「{k}」不是 ContractType")
                out.append(v)
            return out
        if isinstance(produced, (list, tuple)):
            out = []
            for i, v in enumerate(produced):
                if not isinstance(v, ContractType):
                    raise CommandError(
                        f"{path.name}：build() 返回的列表第 {i} 项不是 ContractType（是 {type(v).__name__}）"
                    )
                out.append(v)
            return out
        raise CommandError(
            f"{path.name}：build() 必须返回 ContractType / 列表 / 字典，实际是 {type(produced).__name__}"
        )

    # ==================== 试算 ====================

    def _trial_all(self, types: list[ContractType], snap, *, verbose: bool) -> list[str]:
        """对每家公司各跑一次（逐公司，而不是「一家公司顶所有参与方」）。"""
        from apps.contracts.engine import ContractEngine

        companies = snap.companies()
        if not companies:
            raise CommandError("该比赛没有任何公司，无法试算")

        engine = ContractEngine()
        failed: list[str] = []
        for ct in types:
            payload = ct.build()
            host_roles = {p["role"] for p in payload["partyRoles"] if p.get("isHost")}
            selectable = [p["role"] for p in payload["partyRoles"] if not p.get("isHost")]
            if not selectable:
                failed.append(ct.key)
                self.stdout.write(self.style.ERROR(f"  {ct.key}：只有主办方，无法试算"))
                continue
            ok_count = 0
            for company in companies:
                parties = [
                    {
                        "role": p["role"],
                        "label": p.get("label") or p["role"],
                        "isHost": bool(p.get("isHost")),
                        "companyId": None if p.get("isHost") else company["id"],
                    }
                    for p in payload["partyRoles"]
                ]
                # 引擎不会套用 inputSchema 的 default（那是调用方责任），
                # 这里用 default_inputs() 补齐，否则未提供的输入项会被 to_number(None)
                # 变成 0，表现为「乘费率的效果恒为 0」这类静默错误。
                inputs = ct.default_inputs()

                engine_dict = {
                    "id": None,
                    "competition_id": snap.competition_id,
                    "parties": json.dumps(parties, ensure_ascii=False),
                    "inputs": json.dumps(inputs, ensure_ascii=False),
                    "contract_type": {
                        "id": None,
                        "effects": json.dumps(payload["effects"], ensure_ascii=False),
                        "conditions": json.dumps(payload["conditions"], ensure_ascii=False),
                        "inputSchema": json.dumps(payload["inputSchema"], ensure_ascii=False),
                    },
                }
                try:
                    with transaction.atomic():
                        result = engine.execute(engine_dict, throw_on_fail=False)
                        checks = (result.get("result") or {}).get("checks") or []
                        transaction.set_rollback(True)
                except Exception as e:  # noqa: BLE001 - 试算失败要收集而不是中断
                    failed.append(f"{ct.key}@{company['name']}")
                    self.stdout.write(
                        self.style.ERROR(f"  {ct.key} × {company['name']}：引擎报错 {type(e).__name__}: {e}")
                    )
                    continue
                bad = [c for c in checks if not c.get("passed")]
                if bad:
                    failed.append(f"{ct.key}@{company['name']}")
                    for c in bad:
                        detail = c.get("errorMessage") or c.get("detail") or ""
                        self.stdout.write(
                            self.style.WARNING(
                                f"  {ct.key} × {company['name']}：检查未通过 —— {c.get('label') or c.get('kind')}：{detail}"
                            )
                        )
                else:
                    ok_count += 1
            if verbose or ok_count:
                self.stdout.write(f"  {ct.key}：{ok_count}/{len(companies)} 家公司试算通过")
        return failed

    # ==================== 写入 ====================

    def _write_all(self, types: list[ContractType], *, dry_run: bool) -> None:
        from apps.contracts.serializers import ContractTypeSerializer

        created = updated = unchanged = 0
        for ct in types:
            body = ct.payload()
            body.pop("graph", None)  # graph 单独处理：不覆盖已有画布
            existing = ContractTypeModel.objects.filter(key=ct.key).first()
            if existing is None:
                if dry_run:
                    self.stdout.write(f"  [新增] {ct.key}（{ct.name}）")
                    created += 1
                    continue
                serializer = ContractTypeSerializer(data=body)
                serializer.is_valid(raise_exception=True)
                serializer.save()
                self.stdout.write(self.style.SUCCESS(f"  [新增] {ct.key}（{ct.name}）"))
                created += 1
                continue

            # 已存在：按字段比较，避免无谓写入（也就不会触发无谓广播）
            changes = _diff(existing, body)
            if not changes:
                self.stdout.write(f"  [相同] {ct.key}（无需更新）")
                unchanged += 1
                continue
            if dry_run:
                self.stdout.write(f"  [更新] {ct.key}：{'、'.join(changes)}")
                updated += 1
                continue
            # graph 不覆盖：把已有的 graph 一并提交，保持画布可用
            body["graph"] = json.loads(existing.graph) if existing.graph else None
            serializer = ContractTypeSerializer(existing, data=body, partial=True)
            serializer.is_valid(raise_exception=True)
            serializer.save()
            self.stdout.write(self.style.SUCCESS(f"  [更新] {ct.key}：{'、'.join(changes)}"))
            updated += 1

        head = "预演结果" if dry_run else "导入结果"
        self.stdout.write(
            f"{head}：新增 {created}、更新 {updated}、未变化 {unchanged}"
            + ("（未写库）" if dry_run else "")
        )

    # ==================== 导出（反解既有合同类型） ====================

    def _export(self, options: dict) -> None:
        key = options["export"] or ""
        if not key and not options["all"]:
            raise CommandError("--export 需要合同类型 key，或加 --all 导出全部")
        qs = ContractTypeModel.objects.all().order_by("id")
        if key and not options["all"]:
            qs = qs.filter(key=key)
        rows = list(qs)
        if not rows:
            raise CommandError("没有找到匹配的合同类型")

        out: list[dict] = []
        for ct in rows:
            effects = _parse_json(ct.effects, [])
            declared = None
            if options["competition"]:
                snap = snapshot(options["competition"])
                declared = None
                for role, tid in _role_industry_of(ct, snap).items():
                    if tid is not None:
                        declared = declared or {}
                        declared[tid] = snap.industry_field_types().get(tid, {})
            named = effects_from_specs(
                effects, declared_types=_declared_types_for(ct, declared)
            )
            entry = {
                "key": ct.key,
                "name": ct.name,
                "partyRoles": _parse_json(ct.party_roles, []),
                "inputSchema": _parse_json(ct.input_schema, []),
                "effects": effects,
                "namedEffects": [
                    {"kind": e.kind, "describe": e.describe, "spec": e.to_spec()} for e in named
                ],
                "namedCoverage": f"{len(named)}/{len(effects)}",
                "conditions": _parse_json(ct.conditions, []),
            }
            out.append(entry)

        if options["json"]:
            self.stdout.write(json.dumps(out, ensure_ascii=False, indent=2))
            return
        for entry in out:
            self.stdout.write("")
            self.stdout.write(f"=== {entry['name']}（{entry['key']}）===")
            self.stdout.write(f"具名效果反解覆盖率：{entry['namedCoverage']}")
            for item in entry["namedEffects"]:
                self.stdout.write(f"  · {item['kind']:<16} {item['describe']}")
            missed = len(entry["effects"]) - len(entry["namedEffects"])
            if missed:
                self.stdout.write(
                    self.style.WARNING(f"  （{missed} 条效果无法反解成具名效果，原样保留）")
                )


# ==================== 辅助 ====================


def _diff(existing, body: dict) -> list[str]:
    """比较既有记录与将要写入的字段，返回变化字段名列表。"""
    changes: list[str] = []
    for field, db_field in (
        ("name", "name"),
        ("description", "description"),
        ("effects", "effects"),
        ("conditions", "conditions"),
        ("inputSchema", "input_schema"),
        ("partyRoles", "party_roles"),
        ("enabled", "enabled"),
    ):
        current = getattr(existing, db_field, None)
        new = body.get(field)
        if db_field in ("effects", "conditions", "input_schema", "party_roles"):
            if _parse_json(current, None) != new:
                changes.append(field)
        elif current != new:
            changes.append(field)
    return changes


def _parse_json(raw, fallback):
    if raw in (None, ""):
        return fallback
    if isinstance(raw, (list, dict)):
        return raw
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return fallback


def _role_industry_of(ct, snap) -> dict:
    out = {}
    for p in _parse_json(ct.party_roles, []):
        if isinstance(p, dict) and p.get("role"):
            tid = p.get("industryTypeId")
            out[str(p["role"])] = int(tid) if tid not in (None, "") else None
    return out


def _declared_types_for(ct, declared) -> dict[str, str]:
    """构造 `{"角色.字段": 字段类型}`，供反解时选更精确的效果名。"""
    if not declared:
        return {}
    out: dict[str, str] = {}
    for p in _parse_json(ct.party_roles, []):
        if not isinstance(p, dict):
            continue
        role = str(p.get("role") or "")
        tid = p.get("industryTypeId")
        if not role or tid in (None, ""):
            continue
        for field_key, ftype in (declared.get(int(tid)) or {}).items():
            out[f"{role}.{field_key}"] = ftype
    return out
