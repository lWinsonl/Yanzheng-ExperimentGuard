# 可重复的系统测试与评测工具

该目录提供离线执行工具和公开合成开发集。完整方案见 [评测协议](../docs/evaluation/plan.md)，当前实测见 [2026-11-02报告](reports/2026-11-02/summary.md)。

## 安装与执行

在仓库根目录：

```text
python -m pip install -r backend/requirements-dev.txt
npm --prefix frontend ci
python -m evaluation.run
```

运行器显式清空子进程中的模型配置，使用临时数据目录。它不改 `.env`、不调用生产站点、不调用模型服务。不要绕过这些设置来运行带真实DATA_DIR的测试。

默认结果放到 `evaluation/runs/时间/`，此目录被Git忽略。输出包括 `summary.md`、`results.json`、JUnit、日志、盲化输入包与评分自检。**默认退出码0只表示执行阶段成功；已知缺陷与能力空白仍在报告中。**

```text
python -m evaluation.run --release-gate
```

门槛模式在存在已知未修缺陷时返回2。当前结果为120通过、5严格XFAIL；单独的 `known-defects-audit` 使用 `--runxfail` 真实暴露5个断言失败，退出码1为已发现缺陷，不是通过。修复后要移除相应失败标记并更新报告。

如果已验证前端构建，只想复跑后端与能力诊断：

```text
python -m evaluation.run --skip-frontend
```

Windows 下 TestClient 需要初始化本地事件循环；若运行环境限制本地连接，需在允许本机测试连接的环境执行。不要把环境初始化失败标成产品通过。

## 合成集的边界

`cases.json` 包含24个开发者预设标签的能力探针，不是教师独立标注的留出集。运行器测试的是“规则提取 → 脚本确认事实 → 规则审查 → 证据图”的流程，**不包含真实模型、真实用户确认或界面交互**。实体隔离仅核对提供的编号；比较和稳定性案例只要求对限定表中数值作描述，不要求证明总体显著性。

来源必须按 `project_id/family_id` 分组。开发者已见过的公开案例不能再当未知测试集。自动确认事实是理想化输入条件，不等于学生确认准确率。

## 其他条件的输出评分

先导出不带金标的输入：

```text
python -m evaluation.prepare --dataset evaluation/cases.json --output evaluation/runs/input-pack
```

只把 `blind-inputs.json` 的一条案例发给模型。`gold-do-not-send.csv` 是评分金标，不能发给模型。原始输出应单独保留，由不知道条件名称的评阅者归一化，不能补写模型没有给出的判断。

规范化预测文件：

```json
{
  "condition": "预算匹配迭代问答",
  "run_id": "r1",
  "dataset_sha256": "替换为导出时的数据集哈希",
  "predictions": [
    {"case_id": "S01", "prediction": "supported"}
  ]
}
```

标签只有 supported / contradicted / insufficient / error。每次运行单独一个文件，不能把重复运行当独立项目。缺失输出计error，重复ID、未知ID或哈希不符直接拒绝。

```text
python -m evaluation.score --dataset evaluation/cases.json --predictions evaluation/runs/predictions.json --output evaluation/runs/scored.json
```

评分器不自动调用模型；真实模型对比需要先冻结协议、教师标签与调用预算。模板中的“始终信息不足”是评分程序自检，**不是智谱结果**。

## 指标与工件

- `metrics.py`：三态混淆矩阵、宏F1、判断覆盖率、确定判断正确率、κ、Wilson与项目配对bootstrap。无分母返回null；合成案例默认不生成总体置信区间。
- `templates/`：材料与教师标注CSV、漏洞匹配、追问事件、匿名学生评分、基线提示词和冻结记录。
- `reports/2026-11-02/`：经过检查的合成测试结果。这里只发布无真实材料的结果。

真实材料、学生身份、模型密钥与供应商原始敏感响应不得提交公开仓库。供应商实际429、超时、模型语义判断、浏览器验收与教学效果尚未由本轮离线结果验证。
