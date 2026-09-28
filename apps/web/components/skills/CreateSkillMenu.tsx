"use client";

import { useEffect, useRef, useState } from "react";
import { ChevronDownIcon, GithubIcon, UploadIcon } from "@/components/ui/icons";
import { GithubImportModal } from "@/components/skills/GithubImportModal";
import { UploadSkillModal } from "@/components/skills/UploadSkillModal";

interface CreateSkillMenuProps {
  onImported: () => void;
  label?: string;
}

export function CreateSkillMenu({ onImported, label = "创建我的专属技能" }: CreateSkillMenuProps) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [githubOpen, setGithubOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  // 这个页面只有一个这样的下拉，不需要多菜单互斥协调——自己管 open 状态 + 点击外部关闭即可。
  useEffect(() => {
    if (!menuOpen) return;
    const onClickOutside = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(false);
    };
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, [menuOpen]);

  return (
    <div ref={menuRef} className="relative">
      <button
        type="button"
        onClick={() => setMenuOpen((v) => !v)}
        className="flex items-center gap-1.5 rounded-lg border border-border bg-white px-3 py-1.5 text-sm font-medium hover:bg-gray-50"
      >
        {label}
        <ChevronDownIcon width={14} height={14} />
      </button>

      {menuOpen && (
        <div
          role="menu"
          className="absolute right-0 z-20 mt-1 w-56 rounded-xl border border-border bg-white p-1.5 shadow-lg"
        >
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              setMenuOpen(false);
              setUploadOpen(true);
            }}
            className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm hover:bg-gray-50"
          >
            <UploadIcon width={16} height={16} />
            上传技能
          </button>
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              setMenuOpen(false);
              setGithubOpen(true);
            }}
            className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm hover:bg-gray-50"
          >
            <GithubIcon width={16} height={16} />
            从 GitHub 导入技能
          </button>
        </div>
      )}

      <UploadSkillModal open={uploadOpen} onClose={() => setUploadOpen(false)} onUploaded={onImported} />
      <GithubImportModal open={githubOpen} onClose={() => setGithubOpen(false)} onImported={onImported} />
    </div>
  );
}
