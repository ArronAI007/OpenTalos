# date

计算相对于今天的日期。不传参数返回今天的日期；传一个整数参数返回今天加上这么多天之后（可以是负数，表示往前推）的日期。

## 使用方法

调用 `run-script` 接口，`script_relative_path` 设为 `scripts/main.py`。

示例：`args: ["7"]` 返回 7 天后的日期；`args: ["-3"]` 返回 3 天前的日期；`args: []` 返回今天的日期。输出格式为 `YYYY-MM-DD`。
