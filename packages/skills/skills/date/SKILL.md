---
name: "date"
description: |
  日期查询技能：获取当前日期。
  
  触发条件：
  (1) 用户询问今天日期
  (2) 用户问"今天几号"
  (3) 用户需要知道今天的日期
  
  输出：当前日期（年-月-日 星期）
keywords: ["日期", "几号", "今天", "星期", "年月日", "今天几号", "星期几", "date"]
category: "utility"
scope: ["*"]
execution:
  scripts:
    main.py:
      sha256: "a46ea1ce0532665a9834f79b5e5bc60ccdf50c8230ec4f913e02d2fe353a5d6d"
      network: false
      env: []
---
# 日期查询技能
## 功能描述
获取当前的系统日期。

## 使用示例
用户："今天几号？"
系统：调用 get_current_date() 获取当前日期

## 输出格式
- `date`: 当前日期，格式为 "YYYY-MM-DD"
- `weekday`: 星期几
- `formatted`: 格式化后的日期字符串
