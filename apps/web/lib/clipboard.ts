// 复制文本到剪贴板，返回是否成功；任何失败路径都返回 false，不向上抛异常。
// 首选异步 Clipboard API（需安全上下文，localhost/HTTPS 可用）；
// 不可用或抛错时回退临时 textarea + execCommand("copy")（兼容非安全上下文与老浏览器）。
export async function copyText(text: string): Promise<boolean> {
  if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      // 权限被拒等场景落回 execCommand
    }
  }
  if (typeof document === "undefined") return false;
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.style.position = "fixed"; // 离开视口布局流，避免挂载引起页面抖动
  textarea.style.opacity = "0";
  document.body.appendChild(textarea);
  textarea.select();
  try {
    return document.execCommand("copy");
  } catch {
    return false;
  } finally {
    document.body.removeChild(textarea); // 无论成败都清理临时元素
  }
}
