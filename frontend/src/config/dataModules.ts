interface FormField {
  prop: string;
  label: string;
  type?: string;
  inputType?: string;
  min?: number;
  rules?: any[];
}

interface Column {
  prop: string;
  label: string;
  width?: string | number;
  minWidth?: string | number;
  render?: string;
}

interface ModuleConfig {
  title: string;
  columns: Column[];
  formFields: FormField[];
  api: any;
  /** 管理（新建/编辑/删除）所需的权限键；缺省视为无需校验（始终可管理）。 */
  managePermission?: string;
}

export const moduleConfigs: Record<string, ModuleConfig> = {};
