export interface ChatState {
  message: string;
  searchResult?: string;
  usedTool?: boolean;
  approved?: boolean;
  reply?: string;
}
