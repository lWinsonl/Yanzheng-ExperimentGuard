# 研证离线系统测试与能力评测报告

执行时间：2026-11-02T10:15:20.521603+00:00（UTC）

源码基线：`57f458a0c5305ddcf84df7f2620321686bd0af97`；工作区包含本轮新增评测代码。
源码指纹：`78643b3302d1bbd7099ef850525e878896a3a0bc41db663ab314460355b10c89`

## 结论边界

本次没有读取真实会话、访问线上服务或调用智谱。模型故障测试使用桩；合成案例的候选事实由脚本确认。浏览器页面交互、生产冷启动、真实模型与学生效果没有在本次执行中验证。

## 测试与构建

测试 125 项：通过 120，失败 0，错误 0，已复现未修缺陷 XFAIL 5，其他跳过 0。XFAIL 不计为通过。

| 阶段 | 退出码 | 秒 | 日志 |
| --- | ---: | ---: | --- |
| backend-tests | 0 | 3.597 | [backend-tests.log](backend-tests.log) |
| known-defects-audit | 1 | 3.747 | [known-defects-audit.log](known-defects-audit.log) |
| frontend-build | 0 | 0.929 | [frontend-build.log](frontend-build.log) |
| frontend-lint | 0 | 0.422 | [frontend-lint.log](frontend-lint.log) |

## 已复现的未修缺陷

- EG-001 证据类别变化导致同一规则的旧问题被误标为已解决。复现：`test_same_unresolved_issue_is_not_resolved_when_evidence_category_changes`。
- EG-002 用旧发现引用代替完整旧事实快照，使未修改的指标被报告为新增且理由一致。复现：`test_unchanged_metric_does_not_validate_revision_claim`。
- EG-003 未实现DOCX解析却以普通文本成功接收，未报告解析缺口。复现：`test_unsupported_docx_is_explicitly_rejected_or_flagged`。
- EG-004 非法材料角色被静默改成plan，缺少输入枚举校验。复现：`test_invalid_material_role_is_not_silently_reclassified`。
- EG-005 代码注释中的示例均值标准差被当作实际重复运行结果。复现：`test_example_numbers_in_code_do_not_replace_observed_runs`。

本地回归发布门槛：**未通过**。该门槛不证明真实模型或教学效果。
`known-defects-audit` 使用 `--runxfail` 单独暴露未修断言；它的退出码1表示确有失败，不计为正常通过。

## 合成能力探针

这些案例是公开开发诊断集，标签由开发者预先设定，未经教师独立标注。下面数字仅描述本轮规则流程，不能作为真实科研准确率或获奖依据。

案例数 24；数据集指纹 `79fdf95c0504aa06b90b4c2d0db6f9f5d45ff995d049dd4247e3ff0582b073c2`。

| 指标 | 本次结果 | 含义 |
| --- | ---: | --- |
| 三态准确率 | 50.0% | 包含信息不足、错误输出，不删失败样本 |
| 宏平均 F1 | 0.500 | 同时考察支持、矛盾、信息不足 |
| 可判案例上的判断覆盖率 | 33.3% | 金标可判时实际作出支持/矛盾判断 |
| 可判案例上的保留判断率 | 66.7% | 缺能力也必须进入分母 |
| 已作确定判断的正确率 | 100.0% | 必须与覆盖率一起看 |
| 错误确定判断 | 0/6 | 非确定金标被过度断言也计错 |
| 引用锚点有效率 | 100.0% | 只检验原文位置，不证明推理成立 |

| 子任务 | 案例数 | 准确率 | 可判覆盖率 |
| --- | ---: | ---: | ---: |
| comparison | 8 | 25.0% | 0.0% |
| scope | 8 | 100.0% | 100.0% |
| stability | 8 | 25.0% | 0.0% |

评分自检（始终回答信息不足，非模型基线）：准确率 25.0%，宏F1 0.133，判断覆盖率 0.0%，确定判断正确率不适用。

未正确判断的案例：

- `C01`：金标 `supported`，输出 `insufficient`；同一指标与条件，按明确的指标方向比较表中点估计；不要求推断显著性。
- `C02`：金标 `supported`，输出 `insufficient`；同一指标与条件，按明确的指标方向比较表中点估计；不要求推断显著性。
- `C03`：金标 `supported`，输出 `insufficient`；同一指标与条件，按明确的指标方向比较表中点估计；不要求推断显著性。
- `C04`：金标 `contradicted`，输出 `insufficient`；同一指标与条件，按明确的指标方向比较表中点估计；不要求推断显著性。
- `C05`：金标 `contradicted`，输出 `insufficient`；同一指标与条件，按明确的指标方向比较表中点估计；不要求推断显著性。
- `C06`：金标 `contradicted`，输出 `insufficient`；同一指标与条件，按明确的指标方向比较表中点估计；不要求推断显著性。
- `T01`：金标 `supported`，输出 `insufficient`；仅比较已给出的同条件样本标准差；有限样本描述不等于总体稳定性证明。
- `T02`：金标 `supported`，输出 `insufficient`；仅比较已给出的同条件样本标准差；有限样本描述不等于总体稳定性证明。
- `T03`：金标 `supported`，输出 `insufficient`；仅比较已给出的同条件样本标准差；有限样本描述不等于总体稳定性证明。
- `T04`：金标 `contradicted`，输出 `insufficient`；仅比较已给出的同条件样本标准差；有限样本描述不等于总体稳定性证明。
- `T05`：金标 `contradicted`，输出 `insufficient`；仅比较已给出的同条件样本标准差；有限样本描述不等于总体稳定性证明。
- `T06`：金标 `contradicted`，输出 `insufficient`；仅比较已给出的同条件样本标准差；有限样本描述不等于总体稳定性证明。

本机串行中位耗时 6.0 ms；最近秩 P95 8.6 ms。含本地保存，不含模型、网络、渲染；不可当作线上 SLA。

## 后续工作

先复核并修复缺陷，之后冻结模型、提示词与数据集，再进行教师盲评和同模型基线比较。教学效果必须通过独立学生任务验证。完整协议见仓库 `docs/evaluation/plan.md`。
