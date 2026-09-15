---
name: date
description: 获取当前日期和星期几（使用中国时区 Asia/Shanghai）。当用户询问"今天几号""今天星期几""现在是什么日期"等需要知道当前日期的问题时使用。
---

# date

Call `run_skill_script` with:
- `skillName`: `"date"`
- `scriptRelativePath`: `"scripts/main.py"`
- `args`: not needed (omit or pass an empty array)
- `input`: not needed

The script prints the current date in China Standard Time (Asia/Shanghai, UTC+8) as a single line,
e.g. `2026年09月15日 星期二` — return that output to the user as-is, or naturally incorporate it into
your reply.
