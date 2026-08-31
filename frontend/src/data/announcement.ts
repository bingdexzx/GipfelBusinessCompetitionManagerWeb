/**
 * 更新公告数据源（历史化）。
 *
 * 设计：
 *  - `announcements` 为按版本倒序的数组（最新在前）。每次发版：在数组【最前面】插入一条新公告，
 *    旧版本保留于此，以便「系统设置 - 关于 - 查看更新记录」中查看历史更新记录。
 *  - `currentAnnouncement` 指向数组首条（最新），作为客户端「是否已读」锚点：
 *    用户首次打开某版本时自动弹出；点击「不再显示」后标记已读，下次启动不再弹，
 *    直到出现更高版本（新公告）才再次弹出。
 *  - content 通过 v-html 渲染，仅由开发者维护、属于受信任内容，
 *    切勿渲染任何来自用户或服务端不可信的 HTML，避免 XSS。
 */
export interface Announcement {
  /** 公告版本号，作为"是否已读"的锚点。发版须随变更递增。 */
  version: string;
  /** 弹窗标题 */
  title: string;
  /** 发布日期（展示用，YYYY-MM-DD） */
  date: string;
  /** 公告正文，支持受信任的 HTML 片段（v-html 渲染）。 */
  content: string;
}

export const announcements: Announcement[] = [
  {
    version: "1.3.18",
    title: "更新公告 v1.3.18",
    date: "2026-08-30",
    content: `
      <ul>
        <li>系统完成 <b>Vue + Django Web 化重构</b>：界面与功能保持不变，由原 Electron 桌面端改造为纯 Web 网站。</li>
        <li>服务端由 NestJS + Prisma 迁移至 <b>Django + DRF + SQLite</b>，REST 路由、响应格式、Socket.IO 实时协议完全保持兼容。</li>
        <li>前端剥离 Electron，保留 Vue 3 + Element Plus + Pinia + vue-konva 全部依赖与交互。</li>
        <li>版本硬封锁来源从 Electron <code>app.getVersion()</code> 改为前端常量与 <code>/api/version</code> 比对。</li>
      </ul>
    `,
  },
  {
    version: "1.3.17",
    title: "更新公告 v1.3.17",
    date: "2026-08-20",
    content: `
      <ul>
        <li>合同类型管理与产业字段管理的可视化编辑器：画布支持滚轮缩放、空白处拖拽平移、适应/重置视图，可自由缩放与移动节点图。</li>
        <li>修复仪表盘圆形格点背景下方未铺满的问题（画布现在可撑满整块可视区域）。</li>
        <li>修复断线重连后客户端对服务器发起大量并发对账请求，以及 401 鉴权失败写入审计日志导致的日志刷屏与数据库压力。</li>
      </ul>
    `,
  },
  {
    version: "1.3.16",
    title: "更新公告 v1.3.16",
    date: "2026-08-16",
    content: `
      <ul>
        <li>修复本地缓存污染导致的数据显示错误</li>
        <li>修复「比赛管理」权限问题导致的无法选择比赛</li>
        <li>修复「权限管理」问题导致的页面渲染错误</li>
        <li>修复「更新公告」不显示的问题</li>
        <li>修复权限管理已知问题</li>
        <li>修复本地存储已知问题</li>
        <li>修复仪表盘权限获取的显示问题</li>
        <li>修复「合同管理」创建合同时，地图节点列表显示错误的问题</li>
        <li>修复「合同引擎」因数据类型错误导致的无法设定所在地的问题</li>
        <li>新增地图背景设置，可以给地图添加不同的背景图片</li>
        <li>新增地图图例，便于区分节点与路径</li>
        <li>新增路径距离显示，便于观察</li>
        <li>优化UI</li>
        <li>优化「权限管理」系统</li>
        <li>优化同步机制</li>
        <li>新增「消息中心」，用于消息的发布与接收</li>
        <li>新增「股票系统」</li>
        <li>新增字段定时器，使得计算字段可以定时按照特定规则修改</li>
        <li>更新客户端依赖</li>
      </ul>
    `,
  },
  {
    version: "1.0.1",
    title: "更新公告 v1.0.1",
    date: "2026-08-14",
    content: `
      <ul>
      <li>更新客户端包依赖</li>
      </ul>
    `,
  },
  {
    version: "1.0.0",
    title: "更新公告",
    date: "2026-08-14",
    content: `
      <p>欢迎使用 Gipfel 商赛系统！近期更新已包含以下改进：</p>
      <ul>
        <li>服务器地址支持手动选择协议（<b>http / https</b>），可正常连接到启用 HTTPS 的服务器（如 frp 内网穿透地址）。</li>
        <li>修复使用自签名证书（如 SakuraFrp 自动 TLS）时无法建立连接的问题。</li>
        <li>修复「系统设置 - 测试连接」误报"连接正常"的问题，现改用真实健康检查端点。</li>
        <li>新增「版本更新提示」：当服务端版本高于本机安装版本时，提示联系管理员获取最新安装包。</li>
      </ul>
      <p>点击「不再显示」后本次公告不再自动弹出；若想再次查看历史更新记录，可在「系统设置 - 关于」中点击「查看更新记录」。</p>
      <p>如使用过程中遇到问题，请联系赛事技术支持。</p>
    `,
  },
];

/** 当前（最新）公告：首启自动弹出与「已读」锚点的依据。 */
export const currentAnnouncement: Announcement = announcements[0];

/** 简短公告文本（兼容旧引用）。 */
export const ANNOUNCEMENT = currentAnnouncement.content;
