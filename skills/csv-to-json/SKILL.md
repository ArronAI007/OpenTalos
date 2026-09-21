# csv-to-json

将 CSV 格式的文本转换为 JSON 数组。第一行作为字段名，后续每一行转换成一个 JSON 对象。

## 使用方法

调用 `run-script` 接口，`script_relative_path` 设为 `convert.py`，把要转换的 CSV 内容放进 `input_text`。

示例输入：
```
name,age
Alice,30
Bob,25
```

示例输出：
```json
[{"name": "Alice", "age": "30"}, {"name": "Bob", "age": "25"}]
```
