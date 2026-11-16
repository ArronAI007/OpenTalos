"use client";

import { useEffect, useMemo, useState } from "react";

import {
  createRoutingGroup,
  deleteRoutingGroup,
  listControlPlaneModels,
  listRoutingGroups,
  parseWeightedRoutingTargets,
  updateRoutingGroup,
  type ModelDescriptor,
  type RoutingGroup,
  type RoutingMode,
} from "@/lib/model-control-api";
import {
  EmptyState,
  ManagementPageHeader,
} from "@/components/ui/ManagementPage";
import { LayoutGridIcon, TrashIcon } from "@/components/ui/icons";
import { PageSkeleton } from "@/components/ui/PageSkeleton";

const MODES: RoutingMode[] = ["order", "rotate", "usage", "smart", "pace", "weight"];

const MODE_LABELS: Record<RoutingMode, string> = {
  order: "顺序故障转移",
  rotate: "轮转",
  usage: "最少用量",
  smart: "智能重置",
  pace: "配额节奏",
  weight: "加权",
};

export default function RoutingGroupsPage() {
  const [groups, setGroups] = useState<RoutingGroup[] | null>(null);
  const [models, setModels] = useState<ModelDescriptor[]>([]);
  const [name, setName] = useState("");
  const [mode, setMode] = useState<RoutingMode>("order");
  const [targets, setTargets] = useState("");
  const [sticky, setSticky] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([listRoutingGroups(), listControlPlaneModels()])
      .then(([nextGroups, nextModels]) => {
        setGroups(nextGroups);
        setModels(nextModels);
      })
      .catch((reason) =>
        setError(reason instanceof Error ? reason.message : "无法加载路由组")
      );
  }, []);

  const suggestions = useMemo(
    () =>
      Array.from(
        new Set(
          models.map(
            (model) =>
              `${model.provider}/${model.account_name}/${model.model_id}`
          )
        )
      ).slice(0, 8),
    [models]
  );

  if (groups === null) return <PageSkeleton />;

  const createGroup = async () => {
    const members = parseWeightedRoutingTargets(targets);
    if (!name.trim() || members.length === 0) return;
    setCreating(true);
    setError(null);
    try {
      const created = await createRoutingGroup({
        name: name.trim(),
        mode,
        members,
        sticky,
      });
      setGroups((current) => [created, ...(current ?? [])]);
      setName("");
      setTargets("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "创建路由组失败");
    } finally {
      setCreating(false);
    }
  };

  const changeMode = async (group: RoutingGroup, nextMode: RoutingMode) => {
    setBusyId(group.id);
    setError(null);
    try {
      const updated = await updateRoutingGroup(group.id, { mode: nextMode });
      setGroups((current) =>
        current?.map((item) => (item.id === group.id ? updated : item)) ?? []
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "更新路由组失败");
    } finally {
      setBusyId(null);
    }
  };

  const toggleSticky = async (group: RoutingGroup) => {
    setBusyId(group.id);
    try {
      const updated = await updateRoutingGroup(group.id, {
        sticky: !group.sticky,
      });
      setGroups((current) =>
        current?.map((item) => (item.id === group.id ? updated : item)) ?? []
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "更新路由组失败");
    } finally {
      setBusyId(null);
    }
  };

  const removeGroup = async (group: RoutingGroup) => {
    if (!window.confirm(`删除路由组 ${group.name}？`)) return;
    setBusyId(group.id);
    try {
      await deleteRoutingGroup(group.id);
      setGroups((current) =>
        current?.filter((item) => item.id !== group.id) ?? []
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "删除路由组失败");
    } finally {
      setBusyId(null);
    }
  };

  return (
    <section className="p-6">
      <ManagementPageHeader
        title="路由组"
        description="把多个模型和嵌套路由组合成一个稳定模型 ID。"
      />

      <div className="mb-5 rounded-lg border border-border bg-surface p-4">
        <div className="grid gap-2 md:grid-cols-[1fr_180px_auto]">
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="路由组名称"
            className="rounded-lg border border-border px-3 py-1.5 text-sm"
          />
          <select
            value={mode}
            onChange={(event) => setMode(event.target.value as RoutingMode)}
            className="rounded-lg border border-border px-3 py-1.5 text-sm"
          >
            {MODES.map((value) => (
              <option key={value} value={value}>
                {MODE_LABELS[value]}
              </option>
            ))}
          </select>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={sticky}
              onChange={(event) => setSticky(event.target.checked)}
            />
            会话粘性
          </label>
          <textarea
            value={targets}
            onChange={(event) => setTargets(event.target.value)}
            placeholder={
              "每行一个目标，可写权重：\nopenai/Primary/gpt-5 | 3\ngroup/fast-route @ 2"
            }
            className="min-h-28 rounded-lg border border-border px-3 py-2 font-mono text-xs md:col-span-3"
          />
          <button
            type="button"
            onClick={() => void createGroup()}
            disabled={
              creating ||
              !name.trim() ||
              parseWeightedRoutingTargets(targets).length === 0
            }
            className="rounded-lg bg-text px-3 py-1.5 text-sm text-white disabled:opacity-40 md:col-span-3"
          >
            {creating ? "创建中…" : "创建路由组"}
          </button>
        </div>
        {suggestions.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {suggestions.map((target) => (
              <button
                key={target}
                type="button"
                onClick={() =>
                  setTargets((current) =>
                    current.trim() ? `${current.trim()}\n${target}` : target
                  )
                }
                className="rounded-full border border-border px-2 py-0.5 font-mono text-[11px] text-text-secondary hover:bg-sidebar"
              >
                {target}
              </button>
            ))}
          </div>
        )}
      </div>

      {error && <p className="mb-3 text-sm text-red-500">{error}</p>}

      {groups.length === 0 ? (
        <EmptyState title="还没有路由组" description="创建一个路由组开始配置多模型选择。" />
      ) : (
        <div className="space-y-2">
          {groups.map((group) => (
            <div key={group.id} className="rounded-lg border border-border bg-surface">
              <div className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3">
                <LayoutGridIcon className="text-text-secondary" />
                <span className="text-sm font-medium">{group.name}</span>
                <code className="rounded bg-sidebar px-1.5 py-0.5 text-xs text-text-secondary">
                  group/{group.name}
                </code>
                <span className="flex-1" />
                <select
                  value={group.mode}
                  onChange={(event) =>
                    void changeMode(group, event.target.value as RoutingMode)
                  }
                  disabled={busyId === group.id}
                  className="rounded-lg border border-border px-2 py-1 text-xs"
                >
                  {MODES.map((value) => (
                    <option key={value} value={value}>
                      {value}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  onClick={() => void toggleSticky(group)}
                  disabled={busyId === group.id}
                  className={`rounded-lg border px-2 py-1 text-xs ${
                    group.sticky
                      ? "border-emerald-500/30 text-emerald-600"
                      : "border-border text-text-secondary"
                  }`}
                >
                  {group.sticky ? "sticky" : "turn"}
                </button>
                <button
                  type="button"
                  onClick={() => void removeGroup(group)}
                  disabled={busyId === group.id}
                  aria-label={`删除路由组 ${group.name}`}
                  className="rounded-lg p-1.5 text-text-secondary hover:bg-sidebar hover:text-red-500"
                >
                  <TrashIcon width={14} height={14} />
                </button>
              </div>
              <div className="space-y-1 px-4 py-3">
                {group.members.map((member, index) => (
                  <div
                    key={`${member.target}-${index}`}
                    className="flex items-center gap-2 text-xs"
                  >
                    <span className="w-5 text-text-secondary">{index + 1}</span>
                    <code className="min-w-0 flex-1 truncate">{member.target}</code>
                    <span className="text-text-secondary">× {member.weight}</span>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
