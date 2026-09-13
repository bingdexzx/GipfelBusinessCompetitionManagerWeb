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
