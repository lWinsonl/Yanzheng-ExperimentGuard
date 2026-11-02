# 可重复的系统测试与评测工具

该目录提供离线工具和公开合成开发集。当前见[196项测试与12项浏览器回归](reports/2026-11-02-grounded/summary.md)、[真实模型回放](reports/grounded-case-replay-2026-11-02/summary.md)；历史基线和第一次修复报告保持原样。

## 安装与执行

在仓库根目录：

```text
python -m pip install -r backend/requirements-dev.txt
npm --prefix frontend ci
python -m evaluation.run
```

运行器显式清空子进程中的模型配置，使用临时数据目录。它不改 `.env`、不调用生产站点、不调用模型服务。不要绕过这些设置来运行带真实DATA_DIR的测试。

默认结果放到 `evaluation/runs/时间/`，此目录被Git忽略。输出包括 `summary.md`、`results.json`、JUnit、日志、盲化输入包与评分自检。默认退出码0表示执行阶段成功；不能代替真实材料和教学效果验收。

```text
python -m evaluation.run --release-gate
```

门槛模式在执行失败、已知缺陷回归失败或评分自检失败时返回2。原5项缺陷已移除 XFAIL 并转为普通断言；`known-defects-audit` 额外要求这些断言正常通过，不再将失败当作预期结果。

附加真实浏览器检查（先构建前端，运行器默认会构建）：

```text
python -m evaluation.run --release-gate --browser
```

安装开发依赖后，Windows 自动寻找本机 Chrome/Edge；也可设置 `YANZHENG_TEST_BROWSER` 为浏览器可执行文件。其他环境可在 frontend 目录运行 `npx playwright install chromium`。测试用独立上下文与临时后端，三种宽度共12项；其中待核实区界面用例模拟复核响应，后端拒绝机制另有系统测试。原始截图、追踪默认忽略，发布无敏感材料的摘要。

如果已验证前端构建，只想复跑后端与能力诊断：

```text
python -m evaluation.run --skip-frontend
```

Windows 下 TestClient 需要初始化本地事件循环；若运行环境限制本地连接，需在允许本机测试连接的环境执行。不要把环境初始化失败标成产品通过。

## 合成集的边界

`real_case_pilot.py`是显式选择`--live`才调用供应商的真实材料工具，与默认离线运行器分开。它要求事先准备输入、协议与源码指纹，已有结果禁止覆盖。本地原始材料和请求保存在被忽略的runs目录；公开报告保留两次实现修订、所有失败和人工复核，不把已见材料当留出集。具体边界见各自协议与[最新回放](reports/grounded-case-replay-2026-11-02/summary.md)。

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
- `reports/2026-11-02/`：原始失败基线；`reports/2026-11-02-fixed/`：修复后结果。这里只发布合成材料的结果，不改写旧报告。

真实材料、学生身份、模型密钥与供应商敏感响应不得提交公开仓库。本地浏览器覆盖范围见摘要；供应商实际429、超时、模型语义判断、线上冷启动、完整人工浏览器验收与教学效果仍待验证。
