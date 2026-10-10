"use client";

import { useEffect, useRef, useState } from "react";
import { uploadSkill } from "@/lib/api";
import { useFocusTrap } from "@/lib/focus-trap";

interface UploadSkillModalProps {
  open: boolean;
  onClose: () => void;
  onUploaded: () => void;
}

export function UploadSkillModal({ open, onClose, onUploaded }: UploadSkillModalProps) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setBusy(false);
    setError(null);
    setDragOver(false);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.isComposing) return;
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  const dialogRef = useRef<HTMLDivElement>(null);
  useFocusTrap(dialogRef, open);

  if (!open) return null;

  const handleFile = async (file: File) => {
    setBusy(true);
    setError(null);
    try {
      await uploadSkill(file);
      onUploaded();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "上传失败");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto px-4">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} aria-hidden="true" />
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label="上传技能"
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

        <h2 className="text-lg font-semibold">上传技能</h2>

        <label
          onDragOver={(e) => {
            e.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragOver(false);
            const file = e.dataTransfer.files[0];
            if (file) void handleFile(file);
          }}
          className={`mt-4 flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed px-4 py-10 text-center text-sm text-text-secondary ${
            dragOver ? "border-accent bg-sidebar" : "border-border"
          }`}
        >
          <input
            ref={fileInputRef}
            type="file"
            accept=".zip,.skill"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) void handleFile(file);
            }}
          />
          {busy ? "上传中…" : "拖放或点击以上传"}
        </label>

        {error && <p className="mt-2 text-xs text-red-500">{error}</p>}

        <div className="mt-4 text-xs text-text-secondary">
          <p className="font-medium text-text">文件要求</p>
          <ul className="mt-1 list-disc space-y-0.5 pl-4">
            <li>根目录下包含 SKILL.md 文件的 .zip 或 .skill 文件</li>
            <li>SKILL.md 包含以 YAML 格式编写的技能名称和描述</li>
          </ul>
        </div>
      </div>
    </div>
  );
}
