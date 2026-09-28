"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { getSkillDetail, suggestSkillUsage, type SkillSummary } from "@/lib/api";
import { stashHomeDraft } from "@/lib/pending-message";
import { CheckIcon, MessageCircleIcon } from "@/components/ui/icons";
import { LogoMark } from "@/components/sidebar/Logo";

interface SkillDetailModalProps {
  open: boolean;
  onClose: () => void;
  skill: SkillSummary;
  onToggleAdded: (name: string, currentlyAdded: boolean) => void | Promise<void>;
}

export function SkillDetailModal({ open, onClose, skill, onToggleAdded }: SkillDetailModalProps) {
  const router = useRouter();
  const [content, setContent] = useState<string | null>(null);
  const [updatedAt, setUpdatedAt] = useState<string | null>(null);
  const [examples, setExamples] = useState<string[] | null>(null);
  const requestedForRef = useRef<string | null>(null);

  useEffect(() => {
    if (!open) return;
    if (requestedForRef.current === skill.name) return;
    requestedForRef.current = skill.name;
    setContent(null);
    setUpdatedAt(null);
    setExamples(null);

    getSkillDetail(skill.name)
      .then((detail) => {
        setContent(detail.content);
        setUpdatedAt(detail.updated_at);
      })
      .catch(() => {
        setContent("（加载失败，请稍后重试。）");
      });

    // 和内容请求并行发起，不等 content 回来——推荐用法只需要 description，latency 上不互相拖累。
    suggestSkillUsage(skill.name, skill.description)
      .then(setExamples)
      .catch(() => setExamples([]));
  }, [open, skill.name, skill.description]);

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

  const handlePickExample = (text: string) => {
    stashHomeDraft(text);
    onClose();
    router.push("/");
  };

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto px-4">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} aria-hidden="true" />
      <div
        role="dialog"
        aria-modal="true"
        aria-label={skill.name}
        className="relative z-10 mt-[8vh] w-full max-w-2xl rounded-2xl bg-white p-6 shadow-2xl"
      >
        <button
          type="button"
          aria-label="关闭"
          onClick={onClose}
          className="absolute right-4 top-4 text-text-secondary hover:text-text"
        >
          ✕
        </button>

        {skill.tags.length > 0 && (
          <div className="mb-3 flex flex-wrap gap-1.5">
            {skill.tags.map((tag) => (
              <span key={tag} className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-text-secondary">
                {tag}
              </span>
            ))}
          </div>
        )}

        <h2 className="text-lg font-semibold">{skill.name}</h2>
        <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-text-secondary">
          <span className="flex items-center gap-1">
            <LogoMark size={12} />
            OpenTalos
          </span>
          {updatedAt && <span>更新于 {updatedAt.slice(0, 10)}</span>}
          <span>已使用 {skill.usage_count} 次</span>
        </div>

        <button
          type="button"
          onClick={() => void onToggleAdded(skill.name, skill.added)}
          className="mt-4 flex items-center gap-1.5 rounded-lg bg-text px-3 py-1.5 text-sm font-medium text-white"
        >
          {skill.added ? <CheckIcon width={14} height={14} /> : "+"}
          {skill.added ? "已添加到我的技能" : "添加到我的技能"}
        </button>

        <p className="mt-4 text-sm text-text-secondary">{skill.description}</p>

        <div className="mt-4 border-t border-border pt-4">
          {content === null ? (
            <p className="text-sm text-text-secondary">加载中…</p>
          ) : (
            <div className="md">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
            </div>
          )}
        </div>

        {examples === null ? null : examples.length === 0 ? null : (
          <div className="mt-4 space-y-2">
            <p className="text-xs font-medium text-text-secondary">推荐用法</p>
            {examples.map((example) => (
              <button
                key={example}
                type="button"
                onClick={() => handlePickExample(example)}
                className="flex w-full items-start gap-2 rounded-xl border border-border px-3 py-2 text-left text-sm hover:bg-gray-50"
              >
                <MessageCircleIcon width={16} height={16} className="mt-0.5 shrink-0 text-text-secondary" />
                {example}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
