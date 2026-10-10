// 页面级加载骨架：客户端页面在数据到达前用它占位，避免整屏空白闪烁。
export function PageSkeleton() {
  return (
    <div role="status" aria-label="加载中" className="mx-auto w-full max-w-3xl animate-pulse space-y-3 p-6">
      <div className="h-6 w-40 rounded bg-sidebar" />
      <div className="h-28 rounded-xl bg-sidebar" />
      <div className="h-28 rounded-xl bg-sidebar" />
    </div>
  );
}
