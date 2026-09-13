# 合同类型处理函数文件（由 contract_watcher.py 自动维护）。
# 自动生成的默认函数会按 ContractType.key 追加/改名；在函数体内修改即可定制。
# 程序只会调整「标注行与函数名」，不会覆盖你的函数体。
#
# 函数签名固定：
#     def handle_<key>_passed(contract: dict, ctx: dict) -> None:
#         # contract: 合同详情（含 contractType.key/parties/inputs/execution…）
#         # ctx: {'out_dir', 'typeKey', 'competitionId', 'default_archive'}
#
# 也可手动为某类型添加专属处理（函数名按 key 的拼音形态，如 key="A-B" → handle_a_b_passed）。
# 删除某个自动生成块并重启后，程序不会自动补回——若不想处理该类型，把函数体改为 pass。

# ===== [auto] ContractType.key = e2e_watcher_recheck_v2 =====
def handle_e2e_watcher_recheck_v2_passed(contract: dict, ctx: dict) -> None:
    """e2e_watcher_recheck 类型合同通过后的处理（自动生成的默认函数）。
    定制：删除下面这行 [auto-default] 注释后，替换为你自己的实现。
    可用：ctx['out_dir']（输出根目录）、ctx['typeKey']（当前合同类型 key）、
          ctx['default_archive'](contract, ctx)（通用存档）。"""
    # [auto-default]
    ctx["default_archive"](contract, ctx)

