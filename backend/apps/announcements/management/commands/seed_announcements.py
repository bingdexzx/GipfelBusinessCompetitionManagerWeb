"""将硬编码的内置公告灌入数据库（按 version 去重，已存在则跳过）。

用法：python manage.py seed_announcements
"""
from django.core.management.base import BaseCommand

from apps.announcements.models import Announcement

SEED_DATA = [
    {
        "version": "1.4.0",
        "title": "更新公告 v1.4.0",
        "date": "2026-09-10",
        "content": (
            '<p>自 v1.3.18 以来，系统经历了<b>大规模功能扩展与安全加固</b>，涵盖以下主要更新：</p>\n'
            '<ul>\n'
            '  <li><b>股票系统全面上线</b>：支持股票创建、行情展示、K 线图、做市商自动撮合、资金账户管理、持仓与订单、推进轮次等完整功能。</li>\n'
            '  <li><b>安全加固（P0-P3 全量审计）</b>：修复租户隔离越权、乐观锁失效、登录限流绕过、CSRF/CORS 配置、密钥管理等 27 项安全问题。</li>\n'
            '  <li><b>移动端/平板适配</b>：全面响应式重构，手机端数据列表改为卡片布局，股票行情仿真实 App 设计，弹窗/表单自适应。</li>\n'
            '  <li><b>计算字段引擎（calcGraph）</b>：支持公式计算字段、跨字段依赖图、循环依赖检测、Excel 风格前导等号、Decimal 精确除法。</li>\n'
            '  <li><b>合同系统增强</b>：新增合同试算（dry-run）、单方合同自动待执行、公司管理权执行模型、字段引用同步。</li>\n'
            '  <li><b>全链路大数支持</b>：千万京（10^23）级金额精确处理，新增 BigNumberInput 组件，金融字段 FloatField 改为 DecimalField。</li>\n'
            '  <li><b>审计日志</b>：新增超管审计日志查看页，记录写操作与错误，支持过滤。</li>\n'
            '  <li><b>权限系统全量审计</b>：修复权限蕴含失效、PLAYER 角色权限、has_permission fail-closed 等问题。</li>\n'
            '  <li><b>改密无感续接</b>：后端直接签发新 token 返回，消除二次登录竞态与误报「账号已在其他设备登录」。</li>\n'
            '  <li><b>部署运维加固</b>：Linux 部署/升级脚本自愈化，日志查看器防直连网关，/admin 管理后台令牌网关。</li>\n'
            '  <li><b>更新公告在线管理</b>：超管可在系统设置中发布、编辑、删除更新公告。</li>\n'
            '  <li><b>仪表盘修复</b>：修复公司字段引用 ID 错误导致字段选择异常。</li>\n'
            '</ul>\n'
            '<p>建议所有用户更新至最新版本以获得完整功能与安全保障。</p>'
        ),
    },
    {
        "version": "1.3.18",
        "title": "更新公告 v1.3.18",
        "date": "2026-08-30",
        "content": (
            '<ul>\n'
            '  <li>系统完成 <b>Vue + Django Web 化重构</b>：界面与功能保持不变，由原 Electron 桌面端改造为纯 Web 网站。</li>\n'
            '  <li>服务端由 NestJS + Prisma 迁移至 <b>Django + DRF + SQLite</b>，REST 路由、响应格式、Socket.IO 实时协议完全保持兼容。</li>\n'
            '  <li>前端剥离 Electron，保留 Vue 3 + Element Plus + Pinia + vue-konva 全部依赖与交互。</li>\n'
            '  <li>版本硬封锁来源从 Electron <code>app.getVersion()</code> 改为前端常量与 <code>/api/version</code> 比对。</li>\n'
            '</ul>'
        ),
    },
    {
        "version": "1.3.17",
        "title": "更新公告 v1.3.17",
        "date": "2026-08-20",
        "content": (
            '<ul>\n'
            '  <li>合同类型管理与产业字段管理的可视化编辑器：画布支持滚轮缩放、空白处拖拽平移、适应/重置视图，可自由缩放与移动节点图。</li>\n'
            '  <li>修复仪表盘圆形格点背景下方未铺满的问题（画布现在可撑满整块可视区域）。</li>\n'
            '  <li>修复断线重连后客户端对服务器发起大量并发对账请求，以及 401 鉴权失败写入审计日志导致的日志刷屏与数据库压力。</li>\n'
            '</ul>'
        ),
    },
    {
        "version": "1.3.16",
        "title": "更新公告 v1.3.16",
        "date": "2026-08-16",
        "content": (
            '<ul>\n'
            '  <li>修复本地缓存污染导致的数据显示错误</li>\n'
            '  <li>修复「比赛管理」权限问题导致的无法选择比赛</li>\n'
            '  <li>修复「权限管理」问题导致的页面渲染错误</li>\n'
            '  <li>修复「更新公告」不显示的问题</li>\n'
            '  <li>修复权限管理已知问题</li>\n'
            '  <li>修复本地存储已知问题</li>\n'
            '  <li>修复仪表盘权限获取的显示问题</li>\n'
            '  <li>修复「合同管理」创建合同时，地图节点列表显示错误的问题</li>\n'
            '  <li>修复「合同引擎」因数据类型错误导致的无法设定所在地的问题</li>\n'
            '  <li>新增地图背景设置，可以给地图添加不同的背景图片</li>\n'
            '  <li>新增地图图例，便于区分节点与路径</li>\n'
            '  <li>新增路径距离显示，便于观察</li>\n'
            '  <li>优化UI</li>\n'
            '  <li>优化「权限管理」系统</li>\n'
            '  <li>优化同步机制</li>\n'
            '  <li>新增「消息中心」，用于消息的发布与接收</li>\n'
            '  <li>新增「股票系统」</li>\n'
            '  <li>新增字段定时器，使得计算字段可以定时按照特定规则修改</li>\n'
            '  <li>更新客户端依赖</li>\n'
            '</ul>'
        ),
    },
    {
        "version": "1.0.1",
        "title": "更新公告 v1.0.1",
        "date": "2026-08-14",
        "content": "<ul><li>更新客户端包依赖</li></ul>",
    },
    {
        "version": "1.0.0",
        "title": "更新公告",
        "date": "2026-08-14",
        "content": (
            '<p>欢迎使用 Gipfel 商赛系统！近期更新已包含以下改进：</p>\n'
            '<ul>\n'
            '  <li>服务器地址支持手动选择协议（<b>http / https</b>），可正常连接到启用 HTTPS 的服务器（如 frp 内网穿透地址）。</li>\n'
            '  <li>修复使用自签名证书（如 SakuraFrp 自动 TLS）时无法建立连接的问题。</li>\n'
            '  <li>修复「系统设置 - 测试连接」误报"连接正常"的问题，现改用真实健康检查端点。</li>\n'
            '  <li>新增「版本更新提示」：当服务端版本高于本机安装版本时，提示联系管理员获取最新安装包。</li>\n'
            '</ul>\n'
            '<p>点击「不再显示」后本次公告不再自动弹出；若想再次查看历史更新记录，可在「系统设置 - 关于」中点击「查看更新记录」。</p>\n'
            '<p>如使用过程中遇到问题，请联系赛事技术支持。</p>'
        ),
    },
]


class Command(BaseCommand):
    help = "将硬编码的内置公告灌入数据库（按 version 去重，已存在则跳过）"

    def handle(self, *args, **options):
        created = 0
        skipped = 0
        for item in SEED_DATA:
            _, was_created = Announcement.objects.get_or_create(
                version=item["version"],
                defaults={
                    "title": item["title"],
                    "date": item["date"],
                    "content": item["content"],
                    "is_active": True,
                },
            )
            if was_created:
                created += 1
                self.stdout.write(f"  + {item['version']} {item['title']}")
            else:
                skipped += 1
        self.stdout.write(self.style.SUCCESS(f"完成：新增 {created} 条，跳过 {skipped} 条（已存在）"))
