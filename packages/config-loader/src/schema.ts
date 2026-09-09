import { load as loadYaml } from "js-yaml";
import { z } from "zod";

const edgeSchema = z.object({
  from: z.string(),
  to: z.union([z.string(), z.array(z.string())]),
  joinTo: z.string().optional(),
  when: z.string().optional(),
});

const nodeRefSchema = z.object({
  use: z.string(),
  params: z.record(z.string(), z.unknown()).optional(),
});

const graphConfigSchema = z.object({
  id: z.string(),
  entryNode: z.string(),
  nodes: z.record(z.string(), nodeRefSchema),
  edges: z.array(edgeSchema),
});

export type GraphConfig = z.infer<typeof graphConfigSchema>;
export type NodeRefConfig = z.infer<typeof nodeRefSchema>;
export type EdgeConfig = z.infer<typeof edgeSchema>;

export function loadGraphConfig(yamlOrJson: string): GraphConfig {
  const trimmed = yamlOrJson.trim();
  const raw = trimmed.startsWith("{") ? JSON.parse(trimmed) : loadYaml(trimmed);
  return graphConfigSchema.parse(raw);
}
