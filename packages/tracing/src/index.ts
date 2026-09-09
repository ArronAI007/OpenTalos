import type { EventBus, EventHandler, TraceEvent } from "@opentalos/core-types";

export class InMemoryEventBus implements EventBus {
  private readonly handlers = new Set<EventHandler>();
  private readonly log: TraceEvent[] = [];

  emit(event: TraceEvent): void {
    this.log.push(event);
    for (const handler of this.handlers) {
      handler(event);
    }
  }

  subscribe(handler: EventHandler): () => void {
    this.handlers.add(handler);
    return () => this.handlers.delete(handler);
  }

  getEvents(): TraceEvent[] {
    return [...this.log];
  }
}
