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
