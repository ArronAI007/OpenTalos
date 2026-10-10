"use client";

// 路由级错误边界（Next App Router）：渲染期未捕获异常落到这里，提供重试（reset）。
export default function Error({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <section className="flex h-full flex-col items-center justify-center gap-3 p-6 text-center">
      <p className="text-base font-semibold">页面出错了</p>
      <p className="max-w-md text-xs break-words text-text-secondary">{error.message}</p>
      <button
        type="button"
        onClick={reset}
        className="rounded-lg bg-text px-4 py-2 text-sm font-medium text-white"
      >
        重试
      </button>
    </section>
  );
}
