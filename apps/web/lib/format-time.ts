// 回复时间格式化：行内常显 HH:MM，hover 黑气泡显完整日期。
// 输入统一为 epoch ms（来源：历史行 Date.parse(created_at)——服务端写库时为无时区后缀的
// 本地 ISO（db.py _now()），new Date() 对其按本地时区解析，与生成端同机时一致；
// live 回复定稿时为客户端 Date.now()）。
export function formatHM(ms: number): string {
  const d = new Date(ms);
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  return `${hh}:${mm}`;
}

export function formatDateTimeCN(ms: number): string {
  const d = new Date(ms);
  return `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日 ${formatHM(ms)}`;
}

// 用户消息时间（Manus 式相对日）：今天 → 「今天 HH:MM」；昨天 → 「昨天 HH:MM」；
// 今年更早 → 「M月D日 HH:MM」；跨年 → 「YYYY年M月D日 HH:MM」。
// 比较全用本地年月日字段，now 可注入保证测试确定性。
function isSameDay(a: Date, b: Date): boolean {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

export function formatRelativeDay(ms: number, now = new Date()): string {
  const d = new Date(ms);
  const hm = formatHM(ms);
  if (isSameDay(d, now)) return `今天 ${hm}`;
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (isSameDay(d, yesterday)) return `昨天 ${hm}`;
  if (d.getFullYear() === now.getFullYear()) return `${d.getMonth() + 1}月${d.getDate()}日 ${hm}`;
  return formatDateTimeCN(ms);
}
