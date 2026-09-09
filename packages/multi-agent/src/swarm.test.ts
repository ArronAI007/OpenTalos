import { describe, expect, it } from "vitest";
import type { TenantContext } from "@opentalos/core-types";
import { GraphEngine } from "@opentalos/core-graph";
import { InMemoryCheckpointStore } from "@opentalos/checkpoint";
import { InMemoryEventBus } from "@opentalos/tracing";
import { InMemoryToolRegistry } from "@opentalos/tool-registry";
import { buildSwarmGraph } from "./swarm.js";
import type { NodeFn } from "@opentalos/core-graph";

interface SwarmState {
  votes: string[];
}

const tenant: TenantContext = { tenantId: "tenant-a", sessionId: "session-1" };

function makeDeps() {
  return {
    toolRegistry: new InMemoryToolRegistry(),
    eventBus: new InMemoryEventBus(),
    checkpointStore: new InMemoryCheckpointStore(),
  };
}

describe("buildSwarmGraph", () => {
  it("fans out to every agent in parallel and merges their partial state at the join", async () => {
    const optimist: NodeFn<SwarmState> = async function* (state) {
      return { votes: [...state.votes, "yes"] };
    };
    const skeptic: NodeFn<SwarmState> = async function* (state) {
      return { votes: [...state.votes, "no"] };
    };
    // reducer concatenates votes arrays instead of overwriting, since both branches read the same
    // starting state: each branch's partial only carries its own new vote(s) relative to the
    // pristine pre-fan-out state, so the merge must dedupe by content rather than by array length
    // (GraphEngine folds branch partials sequentially, so a length-based slice would silently drop
    // whichever branch is folded second).
    // This content-based dedup is only correct because "yes"/"no" are distinct test values —
    // it's a test-fixture convenience, not a pattern to copy into a real reducer: two agents
    // that legitimately produced the same value would have one silently dropped.
    const graph = buildSwarmGraph<SwarmState>({
      id: "swarm-agent",
      agents: { optimist, skeptic },
      reducer: (state, partial) => ({
        votes: [...state.votes, ...(partial.votes ?? []).filter((vote) => !state.votes.includes(vote))],
      }),
    });
    const engine = new GraphEngine(graph, makeDeps());
    let checkpoint = engine.start({ votes: [] }, tenant, "swarm-run-1");
    checkpoint = await engine.run(checkpoint);

    expect(checkpoint.status).toBe("done");
    expect(checkpoint.state.votes.sort()).toEqual(["no", "yes"]);
  });
});
