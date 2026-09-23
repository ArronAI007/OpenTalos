// 聊天输入框按键语义：Enter 发送，Shift+Enter 换行。
// isComposing = IME 候选窗激活中，此时 Enter 仅用于选定候选词，不得发送
// （React 合成 KeyboardEvent 无 isComposing，调用方从 e.nativeEvent 取）。
export interface EnterKeyContext {
  key: string;
  shiftKey: boolean;
  isComposing: boolean;
}

export function shouldSubmitOnEnter({ key, shiftKey, isComposing }: EnterKeyContext): boolean {
  return key === "Enter" && !shiftKey && !isComposing;
}
