# 研证离线系统测试与能力评测报告

执行时间：2026-11-02T12:32:23.823362+00:00（UTC）

源码基线：`330cc7553a8bc9fe906be809a8a72890eb759c57`；工作区包含本轮新增评测代码。
源码指纹：`9a15d107fa6198f5b8274e3575e2fd025b7e686a88543bd5887541c224acec40`

## 结论边界

本次没有读取真实会话、访问线上服务或调用智谱。模型故障测试使用桩；合成案例的候选事实由脚本确认。生产冷启动、真实模型与学生效果未验证。浏览器交互以独立浏览器阶段记录为准。

## 测试与构建

测试 171 项：通过 171，失败 0，错误 0，已复现未修缺陷 XFAIL 0，其他跳过 0。XFAIL 不计为通过。

| 阶段 | 退出码 | 秒 | 日志 |
| --- | ---: | ---: | --- |
| backend-tests | 0 | 4.11 | [backend-tests.log](backend-tests.log) |
| known-defects-audit | 0 | 3.595 | [known-defects-audit.log](known-defects-audit.log) |
| frontend-build | 0 | 1.128 | [frontend-build.log](frontend-build.log) |
| frontend-lint | 0 | 0.494 | [frontend-lint.log](frontend-lint.log) |
| browser-tests | 0 | 15.2 | [browser-tests.log](browser-tests.log) |

## 已复现的未修缺陷

本次没有预期失败标记；原5项缺陷已转为必须正常通过的回归测试。

本地回归发布门槛：**通过**。该门槛不证明真实模型或教学效果。
`known-defects-audit` 独立执行原5项缺陷用例；退出码0表示这些回归通过，退出码1仍代表真实失败。

## 真实浏览器回归

浏览器统计：{"startTime": "2026-11-02T12:32:34.093Z", "duration": 14292.723, "expected": 9, "skipped": 0, "unexpected": 0, "flaky": 0}。

| 项目 | 测试 | 结果 |
| --- | --- | --- |
| desktop | create, upload, confirm, answer, revise, practice and refresh | passed |
| desktop | invalid persisted step recovers to a usable page | passed |
| desktop | upload failure keeps existing materials and retry remains usable | passed |
| mobile | create, upload, confirm, answer, revise, practice and refresh | passed |
| mobile | invalid persisted step recovers to a usable page | passed |
| mobile | upload failure keeps existing materials and retry remains usable | passed |
| tablet | create, upload, confirm, answer, revise, practice and refresh | passed |
| tablet | invalid persisted step recovers to a usable page | passed |
| tablet | upload failure keeps existing materials and retry remains usable | passed |

浏览器仅访问隔离本机服务，使用临时浏览器上下文，不使用用户Chrome资料。覆盖上传与失败保留、事实确认、追问、复查、练习保存、刷新、非法本地状态恢复和390/768/1440宽度；不替代真实供应商或生产部署验收。

## 合成能力探针

这些案例是公开开发诊断集，标签由开发者预先设定，未经教师独立标注。下面数字仅描述本轮规则流程，不能作为真实科研准确率或获奖依据。

案例数 24；数据集指纹 `79fdf95c0504aa06b90b4c2d0db6f9f5d45ff995d049dd4247e3ff0582b073c2`。

| 指标 | 本次结果 | 含义 |
| --- | ---: | --- |
| 三态准确率 | 100.0% | 包含信息不足、错误输出，不删失败样本 |
| 宏平均 F1 | 1.000 | 同时考察支持、矛盾、信息不足 |
| 可判案例上的判断覆盖率 | 100.0% | 金标可判时实际作出支持/矛盾判断 |
| 可判案例上的保留判断率 | 0.0% | 缺能力也必须进入分母 |
| 已作确定判断的正确率 | 100.0% | 必须与覆盖率一起看 |
| 错误确定判断 | 0/18 | 非确定金标被过度断言也计错 |
| 引用锚点有效率 | 100.0% | 只检验原文位置，不证明推理成立 |

| 子任务 | 案例数 | 准确率 | 可判覆盖率 |
| --- | ---: | ---: | ---: |
| comparison | 8 | 100.0% | 100.0% |
| scope | 8 | 100.0% | 100.0% |
| stability | 8 | 100.0% | 100.0% |

评分自检（始终回答信息不足，非模型基线）：准确率 25.0%，宏F1 0.133，判断覆盖率 0.0%，确定判断正确率不适用。

未正确判断的案例：


本机串行中位耗时 6.7 ms；最近秩 P95 16.6 ms。含本地保存，不含模型、网络、渲染；不可当作线上 SLA。

## 后续工作

公开开发集上的修复通过不代表真实科研准确率。应冻结本轮代码与格式，再收集独立教师标注的留出材料、完成同模型基线对比。教学效果必须通过独立学生任务验证。完整协议见仓库 `docs/evaluation/plan.md`。
