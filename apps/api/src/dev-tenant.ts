/**
 * Phase 4（平台服务层）会带来真正的认证/租户管理；在那之前，本子系统固定用这一个开发租户，
 * 把"租户校验路径真的在跑"（Scheduler.enqueueResume 的 tenant 匹配检查）和"租户身份来源"
 * 解耦——接入真实认证时，只需要把这个常量换成"从请求里解析出的真实身份"。
 */
export const DEV_TENANT_ID = "dev-tenant";
