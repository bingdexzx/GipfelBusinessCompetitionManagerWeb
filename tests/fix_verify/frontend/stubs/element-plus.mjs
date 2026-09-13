/** element-plus 桩：Node 侧无 DOM，只需 ElMessage / ElMessageBox 的空实现。 */
function noop() {}

export const ElMessage = Object.assign(
  (..._args) => noop(),
  { error: noop, success: noop, warning: noop, info: noop, closeAll: noop },
);

export const ElMessageBox = {
  confirm: async () => "confirm",
  alert: async () => "confirm",
  prompt: async () => ({ value: "" }),
};

export const ElNotification = Object.assign((..._args) => noop(), {
  error: noop,
  success: noop,
  warning: noop,
  info: noop,
});

export const ElLoading = { service: () => ({ close: noop }) };

export default { ElMessage, ElMessageBox, ElNotification, ElLoading };
