import type { CheckpointStore, EventBus, ToolRegistry } from "@opentalos/core-types";
import { GraphEngine, shallowMergeReducer, type EdgeDefinition, type GraphDefinition, type NodeFn } from "@opentalos/core-graph";
import { InMemoryCheckpointStore } from "@opentalos/checkpoint";
import { InMemoryEventBus } from "@opentalos/tracing";
import { InMemoryToolRegistry } from "@opentalos/tool-registry";

export interface DefineGraphOptions<TState> {
  id: string;
  entryNode: string;
  nodes: Record<string, NodeFn<TState>>;
  edges: EdgeDefinition<TState>[];
  reducer?: (state: TState, partial: Partial<TState>) => TState;
}

export function defineGraph<TState extends object>(options: DefineGraphOptions<TState>): GraphDefinition<TState> {
  return {
    id: options.id,
    entryNode: options.entryNode,
    nodes: options.nodes,
    edges: options.edges,
    reducer: options.reducer ?? shallowMergeReducer,
  };
}

export interface CreateEngineOptions {
  toolRegistry?: ToolRegistry;
  eventBus?: EventBus;
  checkpointStore?: CheckpointStore;
}

export function createEngine<TState>(graph: GraphDefinition<TState>, deps: CreateEngineOptions = {}): GraphEngine<TState> {
  return new GraphEngine(graph, {
    toolRegistry: deps.toolRegistry ?? new InMemoryToolRegistry(),
    eventBus: deps.eventBus ?? new InMemoryEventBus(),
    checkpointStore: deps.checkpointStore ?? new InMemoryCheckpointStore(),
  });
}

export { GraphEngine, shallowMergeReducer } from "@opentalos/core-graph";
export type { EdgeDefinition, GraphDefinition, NodeContext, NodeFn, NodeGenerator, NodeResumeValue, NodeYield } from "@opentalos/core-graph";
