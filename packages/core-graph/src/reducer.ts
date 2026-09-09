export function shallowMergeReducer<TState extends object>(state: TState, partial: Partial<TState>): TState {
  return { ...state, ...partial };
}
