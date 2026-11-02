# 可核对的数值材料

研证只核对所提供记录中的限定判断，不替用户运行实验，不验证第三方日志真伪，也不自动证明总体优势或显著性。

## 固定条件点估计

例如主张：“方法 Alpha 在本次固定测试中优于基线 Beta，仅指表中 RMSE 点估计。”上传实际结果 `results.json`，选择执行材料：

```json
{
  "comparison": {
    "main_method": "Alpha",
    "baseline_method": "Beta",
    "metric": "RMSE",
    "better": "lower",
    "main_value": 0.13,
    "baseline_value": 0.21,
    "test_split": {"main": "test-v4", "baseline": "test-v4"},
    "hardware": {"main": "CPU-v2", "baseline": "CPU-v2"},
    "preprocessing": {"main": "pipeline-v3", "baseline": "pipeline-v3"},
    "budget": {"main": "100 trials", "baseline": "100 trials"},
    "executed": true
  }
}
```

上例只说明格式。请用实际实验记录填写，不能将文档示例当测量结果上传。四个条件可写明确的主/基线相同字符串，也接受 `same` 等相同声明；系统未独立核实这些声明。不同值、缺失或未知条件不会给确定比较。

须确认包含完整记录的候选事实，仅确认孤立的“RMSE”名称不够。指标和方法对应方向须与主张一致；未限定的“总体更好”或多指标合并主张应先拆分澄清。

已登记方向：F1、accuracy、precision、recall、AUC/AUROC、throughput/QPS 等越高越好；RMSE、MSE、MAE、latency/latency_ms、runtime/runtime_ms、memory_mb、error 等越低越好。未登记指标保留未知。概率指标默认 0–1，百分数须注明 `"unit": "percent"`。数值必须有限且合法，布尔值不能充当数字。

## 所报告运行的波动

主张：“方法 Alpha 在所报告的这五次运行中比基线 Beta 更稳定，仅指这五次 F1 样本标准差较小。”

```json
{
  "stability": {
    "main_method": "Alpha",
    "baseline_method": "Beta",
    "metric": "F1",
    "conditions": "same",
    "runs": 5,
    "main_runs": [0.78, 0.79, 0.80, 0.81, 0.82],
    "baseline_runs": [0.70, 0.75, 0.80, 0.85, 0.90],
    "executed": true
  }
}
```

优先提供逐次结果，系统重算均值与样本标准差（分母 n−1）；也接受 `main_mean/main_std/baseline_mean/baseline_std` 汇总记录。若同时提供逐次数据和汇总，两者须一致。两方法次数须相同且至少 2 次，数值须有限、非负、符合指标范围。这里只比较这些样本的波动，不推断未来稳定性，不将小样本差异称为显著。

`executed:false`、`is_example:true`、计划状态、未执行说明、代码注释和追问回答均不能替代观测记录。摘要记录仍依赖上传者说明，不能证明所有运行均被如实保留。

## CSV 与 Office 表格

收集材料页的执行材料区域提供[比较模板](../frontend/public/templates/comparison.csv)与[重复运行模板](../frontend/public/templates/stability.csv)。模板故意留空观测值与条件；缺失值不会生成确定结论。第一列为 `task_type`，取 `comparison` 或 `stability`，其他列与 JSON 字段同名。CSV 数字列会转为数值；JSON 数字不得用字符串代替。

DOCX 表格和 XLSX 单元格按同样的明确列名读取。Office 图像、图表、外链与公式不能替代单元格测量值；部分解析会提示缺口，不使用不完整材料给数值确定判断。XLSX 公式不执行，缓存值也不当作新实验结果。

同一材料对相同主张同时提供支持与矛盾记录时保留未知，要求先澄清适用测试。反向数值冲突也会出现在规则报告中，便于从主报告进入原文核对。
