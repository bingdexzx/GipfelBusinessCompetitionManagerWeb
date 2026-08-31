/**
 * Vue 全局属性类型声明。
 *
 * main.ts 中通过 app.config.globalProperties.$formatTime 注册全局格式化函数，
 * 此处补充类型声明，使模板中 $formatTime(...) 调用通过 vue-tsc 类型检查。
 */
import "vue";

declare module "vue" {
  interface ComponentCustomProperties {
    $formatTime: (value: string | number | Date | null | undefined) => string;
  }
}
