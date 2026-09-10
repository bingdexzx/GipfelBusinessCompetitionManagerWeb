/// <reference types="vite/client" />

declare module "*.vue" {
  import type { DefineComponent } from "vue";
  // eslint-disable-next-line @typescript-eslint/ban-types
  const component: DefineComponent<{}, {}, any>;
  export default component;
}

declare global {
  // Vite define 注入的全局常量（构建时从 VERSION.json 读取）
  const __APP_VERSION__: string;
  interface Window {
    electronAPI?: {
      getConfig: (key: string) => Promise<any>;
      setConfig: (key: string, value: any) => Promise<void>;
      getAllConfig: () => Promise<Record<string, any>>;
    };
  }
}
