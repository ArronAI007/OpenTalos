import { SecurityCenter } from "@/components/security/SecurityCenter";

export default function PrivacyPage() {
  return (
    <SecurityCenter
      initialTab="privacy"
      visibleTabs={["privacy"]}
      title="脱敏"
      description="在请求离开本机前检测并替换敏感信息。"
    />
  );
}
