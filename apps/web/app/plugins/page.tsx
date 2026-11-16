import { SecurityCenter } from "@/components/security/SecurityCenter";

export default function PluginsPage() {
  return (
    <SecurityCenter
      initialTab="plugins"
      visibleTabs={["plugins"]}
      title="插件"
      description="安装、校验和启用 OpenTalos Provider、Middleware 与 UI 插件。"
    />
  );
}
