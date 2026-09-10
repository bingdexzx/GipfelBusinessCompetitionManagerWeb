// 进度条控件
// 组件接收三个 props：widget（完整配置）、value（绑定字段值）、totalValue（总量字段值）
window.__widget_module__ = {
  props: ["widget", "value", "totalValue"],
  computed: {
    config() {
      return (this.widget.config.custom || {});
    },
    color() {
      return this.config.color || "#409eff";
    },
    title() {
      return this.config.title || "";
    },
    current() {
      if (this.value != null) return Number(this.value);
      return Number(this.config.current || 0);
    },
    total() {
      if (this.totalValue != null) return Number(this.totalValue);
      return Number(this.config.total || 100);
    },
    pct() {
      if (!this.total || this.total <= 0) return 0;
      return Math.min(100, Math.max(0, Math.round((this.current / this.total) * 100)));
    },
    displayText() {
      return this.current + " / " + this.total + " (" + this.pct + "%)";
    },
  },
  template: '\
    <div style="width:100%;height:100%;display:flex;flex-direction:column;justify-content:center;padding:14px 16px;box-sizing:border-box;gap:8px">\
      <div v-if="title" style="font-size:12px;color:#909399;font-weight:500">{{ title }}</div>\
      <div style="height:12px;background:#ebeef5;border-radius:6px;overflow:hidden">\
        <div :style="{ width: pct + \'%\', background: color, height: \'100%\', borderRadius: \'6px\', transition: \'width 0.3s ease\' }"></div>\
      </div>\
      <div style="font-size:12px;color:#606266;text-align:right">{{ displayText }}</div>\
    </div>\
  ',
};
