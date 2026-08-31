import { ComponentCustomProperties } from "vue";

declare module "vue" {
  interface ComponentCustomProperties {
    $formatTime: (val: string | Date | undefined | null) => string;
  }
}

declare global {
  interface Window {
    electronAPI?: {
      getConfig: (key: string) => Promise<any>;
      setConfig: (key: string, value: any) => Promise<void>;
      getAllConfig: () => Promise<Record<string, any>>;
    };
  }
}
