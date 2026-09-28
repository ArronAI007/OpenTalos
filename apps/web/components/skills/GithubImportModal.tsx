"use client";

import { useEffect, useState } from "react";
import {
  scanGithubSkills,
  importGithubSkills,
  type SkillCandidate,
  type GithubImportResult,
} from "@/lib/api";

interface GithubImportModalProps {
  open: boolean;
  onClose: () => void;
  onImported: () => void;
}

type Step =
  | { kind: "input" }
  | { kind: "select"; candidates: SkillCandidate[] }
  | { kind: "done"; result: GithubImportResult };

export function GithubImportModal({ open, onClose, onImported }: GithubImportModalProps) {
  const [url, setUrl] = useState("");
  const [step, setStep] = useState<Step>({ kind: "input" });
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 每次打开重置到第一步，避免上次导入的残留状态。
  useEffect(() => {
    if (!open) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setUrl("");
    setStep({ kind: "input" });
    setSelected(new Set());
    setBusy(false);
    setError(null);
  }, [open]);

  // Esc 关闭。
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.isComposing) return;
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  const runImport = async (repoUrl: string, relativePaths: string[]) => {
    setBusy(true);
    setError(null);
    try {
      const result = await importGithubSkills(repoUrl, relativePaths);
      setStep({ kind: "done", result });
      onImported();
    } catch (err) {
      setError(err instanceof Error ? err.message : "导入失败");
    } finally {
      setBusy(false);
    }
  };

  const handleScan = async () => {
    const trimmed = url.trim();
    if (trimmed === "") return;
    setBusy(true);
    setError(null);
    try {
      const candidates = await scanGithubSkills(trimmed);
      if (candidates.length === 0) {
        setError("未在该仓库找到技能（需要包含 SKILL.md 的目录）。");
        setBusy(false);
        return;
      }
      if (candidates.length === 1) {
        await runImport(trimmed, [candidates[0].relative_path]);
        return;
      }
      setSelected(new Set(candidates.map((c) => c.relative_path)));
      setStep({ kind: "select", candidates });
      setBusy(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "扫描失败");
      setBusy(false);
    }
  };

  const toggleSelected = (relativePath: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(relativePath)) next.delete(relativePath);
      else next.add(relativePath);
      return next;
    });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto px-4">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} aria-hidden="true" />
      <div
        role="dialog"
        aria-modal="true"
        aria-label="从 GitHub 导入"
        className="relative z-10 mt-[15vh] w-full max-w-md rounded-2xl bg-white p-6 shadow-2xl"
      >
        <button
          type="button"
          aria-label="关闭"
          onClick={onClose}
          className="absolute right-4 top-4 text-text-secondary hover:text-text"
        >
          ✕
        </button>

        {step.kind === "input" && (
          <>
            <h2 className="text-center text-lg font-semibold">从 GitHub 导入</h2>
            <p className="mt-1 text-center text-sm text-text-secondary">直接从公开的 GitHub 仓库中导入技能。</p>
            <label className="mt-4 block text-xs font-medium text-text-secondary">URL</label>
            <input
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://github.com/username/repo"
              aria-label="GitHub 仓库 URL"
              autoFocus
              className="mt-1 w-full rounded-lg border border-border bg-sidebar px-3 py-2 text-sm outline-none"
            />
            {error && <p className="mt-2 text-xs text-red-500">{error}</p>}
            <button
              type="button"
              onClick={() => void handleScan()}
              disabled={busy || url.trim() === ""}
              className="mt-4 w-full rounded-lg bg-text px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
            >
              {busy ? "导入中…" : "导入"}
            </button>
          </>
        )}

        {step.kind === "select" && (
          <>
            <h2 className="text-lg font-semibold">选择要导入的技能</h2>
            <ul className="mt-4 max-h-64 space-y-2 overflow-y-auto">
              {step.candidates.map((candidate) => (
                <li key={candidate.relative_path}>
                  <label className="flex items-start gap-2 rounded-lg border border-border p-2 text-sm">
                    <input
                      type="checkbox"
                      checked={selected.has(candidate.relative_path)}
                      onChange={() => toggleSelected(candidate.relative_path)}
                      className="mt-0.5"
                    />
                    <span>
                      <span className="block font-medium">{candidate.name}</span>
                      <span className="block text-xs text-text-secondary">{candidate.description}</span>
                    </span>
                  </label>
                </li>
              ))}
            </ul>
            {error && <p className="mt-2 text-xs text-red-500">{error}</p>}
            <button
              type="button"
              onClick={() => void runImport(url.trim(), [...selected])}
              disabled={busy || selected.size === 0}
              className="mt-4 w-full rounded-lg bg-text px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
            >
              {busy ? "导入中…" : `导入所选（${selected.size}）`}
            </button>
          </>
        )}

        {step.kind === "done" && (
          <>
            <h2 className="text-lg font-semibold">导入完成</h2>
            {step.result.imported.length > 0 && (
              <p className="mt-3 text-sm">已导入：{step.result.imported.join("、")}</p>
            )}
            {step.result.skipped.length > 0 && (
              <div className="mt-3 text-sm text-text-secondary">
                <p>以下技能被跳过：</p>
                <ul className="mt-1 list-disc pl-5">
                  {step.result.skipped.map((s) => (
                    <li key={s.name}>{s.name}：{s.reason}</li>
                  ))}
                </ul>
              </div>
            )}
            <button
              type="button"
              onClick={onClose}
              className="mt-4 w-full rounded-lg bg-text px-3 py-2 text-sm font-medium text-white"
            >
              完成
            </button>
          </>
        )}
      </div>
    </div>
  );
}
