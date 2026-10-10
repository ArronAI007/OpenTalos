"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { getSkillDetail, suggestSkillUsage, type SkillFile, type SkillSummary } from "@/lib/api";
import { stashHomeDraft } from "@/lib/pending-message";
import { copyText } from "@/lib/clipboard";
import { CheckIcon, ChevronLeftIcon, CopyIcon, FileTextIcon, MessageCircleIcon } from "@/components/ui/icons";
import { LogoMark } from "@/components/sidebar/Logo";
import { useFocusTrap } from "@/lib/focus-trap";

interface SkillDetailModalProps {
  open: boolean;
  onClose: () => void;
  skill: SkillSummary;
  onToggleAdded: (name: string, currentlyAdded: boolean) => void | Promise<void>;
}

export function SkillDetailModal({ open, onClose, skill, onToggleAdded }: SkillDetailModalProps) {
  const router = useRouter();
  const [files, setFiles] = useState<SkillFile[] | null>(null);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [frontmatterYaml, setFrontmatterYaml] = useState<string | null>(null);
  const [updatedAt, setUpdatedAt] = useState<string | null>(null);
  const [examples, setExamples] = useState<string[] | null>(null);
  const [contentOpen, setContentOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const requestedForRef = useRef<string | null>(null);

  useEffect(() => {
    if (!open) return;
    if (requestedForRef.current === skill.name) return;
    requestedForRef.current = skill.name;
    setFiles(null);
    setSelectedPath(null);
    setFrontmatterYaml(null);
    setUpdatedAt(null);
    setExamples(null);
    setContentOpen(false);

    getSkillDetail(skill.name)
      .then((detail) => {
        setFiles(detail.files);
        setSelectedPath(detail.files.some((f) => f.path === "SKILL.md") ? "SKILL.md" : (detail.files[0]?.path ?? null));
        setFrontmatterYaml(detail.frontmatter_yaml);
        setUpdatedAt(detail.updated_at);
      })
      .catch(() => {
        setFiles([{ path: "SKILL.md", content: "（加载失败，请稍后重试。）" }]);
        setSelectedPath("SKILL.md");
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
      if (e.key !== "Escape") return;
      if (contentOpen) {
        setContentOpen(false);
      } else {
        onClose();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose, contentOpen]);

  const dialogRef = useRef<HTMLDivElement>(null);
  useFocusTrap(dialogRef, open);

  if (!open) return null;

  const handlePickExample = (text: string) => {
    stashHomeDraft(text);
    onClose();
    router.push("/");
  };

  const handleCopyFrontmatter = () => {
    if (!frontmatterYaml) return;
    void copyText(frontmatterYaml).then((ok) => {
      if (!ok) return;
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto px-4">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} aria-hidden="true" />
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label={skill.name}
        className="relative z-10 mt-[8vh] flex max-h-[80vh] w-full max-w-2xl flex-col rounded-2xl bg-white shadow-2xl"
      >
        {contentOpen ? (
          <>
            <div className="flex shrink-0 items-center justify-between border-b border-border p-4">
              <button
                type="button"
                onClick={() => setContentOpen(false)}
                className="flex items-center gap-1 text-sm font-semibold hover:text-text-secondary"
              >
                <ChevronLeftIcon width={18} height={18} />
                技能详情
              </button>
              <button type="button" aria-label="关闭" onClick={onClose} className="text-text-secondary hover:text-text">
                ✕
              </button>
            </div>

            <div className="flex flex-1 overflow-hidden">
              <div className="w-36 shrink-0 space-y-0.5 overflow-y-auto p-3">
                <p className="mb-2 px-1 text-xs font-medium text-text-secondary">文件</p>
                {files === null ? (
                  <p className="px-1 text-xs text-text-secondary">加载中…</p>
                ) : (
                  files.map((file) => (
                    <button
                      key={file.path}
                      type="button"
                      onClick={() => setSelectedPath(file.path)}
                      className={`flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm ${
                        file.path === selectedPath ? "bg-gray-100" : "hover:bg-gray-50"
                      }`}
                    >
                      <FileTextIcon width={14} height={14} className="shrink-0 text-text-secondary" />
                      <span className="truncate">{file.path}</span>
                    </button>
                  ))
                )}
              </div>

              <div className="flex-1 overflow-y-auto border-l border-border p-6">
                {(() => {
                  if (files === null) return <p className="text-sm text-text-secondary">加载中…</p>;
                  const selectedFile = files.find((f) => f.path === selectedPath);
                  if (!selectedFile) return null;
                  return (
                    <>
                      {selectedPath === "SKILL.md" && frontmatterYaml && (
                        <div className="mb-4 overflow-hidden rounded-lg border border-border">
                          <div className="flex items-center justify-between bg-gray-50 px-3 py-1.5 text-xs font-medium text-text-secondary">
                            YAML
                            <button
                              type="button"
                              aria-label="复制"
                              onClick={handleCopyFrontmatter}
                              className="text-text-secondary hover:text-text"
                            >
                              <CopyIcon width={14} height={14} />
                            </button>
                          </div>
                          <pre className="overflow-x-auto bg-gray-50 px-3 py-2 text-xs">
                            <code>{frontmatterYaml}</code>
                          </pre>
                          {copied && <p className="bg-gray-50 px-3 pb-2 text-xs text-text-secondary">已复制</p>}
                        </div>
                      )}

                      {selectedFile.content === null ? (
                        <p className="text-sm text-text-secondary">无法预览此文件。</p>
                      ) : selectedFile.path.toLowerCase().endsWith(".md") ? (
                        <div className="md">
                          <ReactMarkdown remarkPlugins={[remarkGfm]}>{selectedFile.content}</ReactMarkdown>
                        </div>
                      ) : (
                        <pre className="overflow-x-auto rounded-lg bg-gray-50 p-3 text-xs">
                          <code>{selectedFile.content}</code>
                        </pre>
                      )}
                    </>
                  );
                })()}
              </div>
            </div>
          </>
        ) : (
          <div className="flex-1 overflow-y-auto p-6">
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

            <div className="mt-4 flex items-center gap-2">
              <button
                type="button"
                onClick={() => void onToggleAdded(skill.name, skill.added)}
                className="flex items-center gap-1.5 rounded-lg bg-text px-3 py-1.5 text-sm font-medium text-white"
              >
                {skill.added ? <CheckIcon width={14} height={14} /> : "+"}
                {skill.added ? "已添加到我的技能" : "添加到我的技能"}
              </button>
              <button
                type="button"
                onClick={() => setContentOpen(true)}
                className="flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-sm font-medium hover:bg-gray-50"
              >
                <FileTextIcon width={16} height={16} />
                查看详情
              </button>
            </div>

            <p className="mt-4 border-t border-border pt-4 text-sm text-text-secondary">{skill.description}</p>

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
        )}
      </div>
    </div>
  );
}
