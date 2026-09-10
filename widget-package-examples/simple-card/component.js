// 数据卡片控件
// 简洁地展示一个标题 + 数值，适合仪表盘概览
export default {
  props: ["widget", "value", "totalValue"],
  computed: {
    config() {
      return (this.widget.config.custom || {});
    },
    title() {
      return this.config.title || "";
    },
    unit() {
      return this.config.unit || "";
    },
    color() {
      return this.config.color || "#1f2d3d";
    },
    bgColor() {
      return this.config.bgColor || "#f0f9ff";
    },
    displayValue() {
      if (this.value != null && this.value !== "") {
        var v = this.value;
        if (typeof v === "number") {
          v = v.toLocaleString();
        }
        return v + (this.unit ? " " + this.unit : "");
      }
      return this.config.defaultValue || "—";
    },
  },
  template: '\
    <div :style="{ width:\'100%\', height:\'100%\', display:\'flex\', flexDirection:\'column\', alignItems:\'center\', justifyContent:\'center\', padding:\'16px\', boxSizing:\'border-box\', background:bgColor, borderRadius:\'8px\' }">\
      <div style="font-size:12px;color:#909399;margin-bottom:8px;font-weight:500">{{ title }}</div>\
      <div :style="{ fontSize:\'28px\', fontWeight:\'700\', color:color }">{{ displayValue }}</div>\
    </div>\
  ',
};
