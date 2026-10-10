// 通用错误提示 + 可选重试按钮；配合各页面 catch 分支使用（失败不再静默）。
export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex flex-col items-center gap-3 p-6 text-center">
      <p className="text-sm text-red-500 break-words">{message}</p>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="rounded-lg bg-text px-4 py-2 text-sm font-medium text-white"
        >
          重试
        </button>
      )}
    </div>
  );
}
