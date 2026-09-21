# text-to-table

把用分隔符隔开的文本（比如逗号分隔）重新排版成 Markdown 表格。第一行作为表头。

## 使用方法

调用 `run-script` 接口，`script_relative_path` 设为 `format.js`，把要转换的文本放进 `input_text`。`args` 的第一个元素是分隔符，不传默认是英文逗号 `,`。

示例输入（`input_text`）：
```
name,age
Alice,30
Bob,25
```

示例输出：
```
| name | age |
| --- | --- |
| Alice | 30 |
| Bob | 25 |
```
