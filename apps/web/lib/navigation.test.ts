import { describe, expect, test } from "vitest";

import {
  NAVIGATION_GROUPS,
  navigationItemForPath,
} from "./navigation";

describe("Magpie navigation", () => {
  test("covers all requested sidebar groups", () => {
    expect(NAVIGATION_GROUPS.map((group) => group.label)).toEqual([
      "使用",
      "模型",
      "观测",
      "扩展",
    ]);
    expect(
      NAVIGATION_GROUPS.flatMap((group) => group.items.map((item) => item.label))
    ).toEqual([
      "Agent",
      "会话",
      "资源库",
      "供应商",
      "路由",
      "路由组",
      "网关",
      "用量",
      "脱敏",
      "插件",
    ]);
  });

  test("resolves breadcrumb metadata for nested paths", () => {
    expect(navigationItemForPath("/routing-groups/demo")).toEqual({
      section: "模型",
      label: "路由组",
    });
    expect(navigationItemForPath("/skills/date")).toEqual({
      section: "高级功能",
      label: "Skills",
    });
  });
});
