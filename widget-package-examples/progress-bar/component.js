// 进度条控件
// 通过 props.values.current 和 props.values.total 读取绑定字段值
window.__widget_module__ = {
  props: ["widget", "values"],
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
      var v = this.values.current;
      return v != null ? Number(v) : 0;
    },
    total() {
      var v = this.values.total;
      return v != null ? Number(v) : 100;
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
