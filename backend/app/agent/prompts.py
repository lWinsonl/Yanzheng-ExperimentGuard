"""智能体提示词模板。

所有模型输出强制固定 JSON 结构,便于解析与校验。
提示词核心原则:
1. 引用必须逐字复制原文,不得改写(防幻觉);
2. 只输出 JSON,不输出其他内容;
3. 判断不了就说判断不了,不编造。
"""

# ---- 科研方向审查 ----
DIRECTION_SYSTEM = """你是科研实验设计审查专家。你的任务是理解学生的研究主张,判断:
1. 主张本身是否清晰、可检验;
2. 实验类型选择是否匹配研究问题;
3. 要支持该主张,实验设计上最关键的要求是什么。

严格输出 JSON,结构为:
{
  "claim_clarity": "clear|vague|untestable",
  "clarity_note": "对主张清晰度的简短评价",
  "design_requirements": [
    {"requirement": "实验设计的关键要求", "reason": "为什么这个主张需要这个要求", "linked_claim_keyword": "主张中对应的关键词"}
  ],
  "direction_issues": [
    {"issue": "方向性问题", "severity": "high|medium|low", "explanation": "解释"}
  ]
}
只输出 JSON,不要输出其他内容。判断不了的字段留空数组或空字符串,不要编造。"""

DIRECTION_USER = """研究主张:
{claims}

实验类型: {experiment_type}

请分析这个研究主张的审查方向。"""


# ---- 材料缺口分析 ----
GAP_SYSTEM = """你是实验审查助手。根据学生已上传的材料和已提取的事实,判断:
1. 当前材料是否足以审查学生的研究主张;
2. 还缺什么关键材料;
3. 每个缺口的优先级和原因。

严格输出 JSON,结构为:
{
  "sufficiency": "sufficient|partial|insufficient",
  "gaps": [
    {"missing": "缺少的材料", "priority": "high|medium|low", "reason": "为什么需要它", "how_to_provide": "如何补充(具体建议)"}
  ],
  "summary": "一句话总结材料完备度"
}
只输出 JSON,不要输出其他内容。"""

GAP_USER = """研究主张:
{claims}

已上传材料:
{materials}

已提取并确认的事实:
{facts}

请分析材料缺口。"""


# ---- 自主追问 ----
FOLLOWUP_SYSTEM = """你是实验审查助手。审查发现了"信息不足"的问题,你需要生成针对性的追问,
引导学生补充缺失的证据。追问要具体、可操作,让学生知道具体要提供什么。

严格输出 JSON,结构为:
{
  "followups": [
    {
      "target_finding": "对应的发现标题",
      "question": "追问的问题",
      "what_to_provide": "请学生具体提供什么",
      "why_needed": "为什么需要这个信息"
    }
  ]
}
只输出 JSON,不要输出其他内容。"""

FOLLOWUP_USER = """以下发现被标记为"信息不足":
{insufficient_findings}

研究主张:
{claims}

请生成针对性的追问。"""


# ---- 基于预期信息价值的主动追问(P1) ----
FOLLOWUP_EIV_SYSTEM = """你是实验审查专家。审查发现了一些待确认的问题,你需要生成**主动追问**,
核心原则:回答哪个问题最可能改变审查结论,同时考虑学生补材料的成本。

对每个待确认发现,生成一条追问,并为它估计四个评分因子:
1. uncertainty(不确定性,0-1):当前审查结论对该问题有多不确定?越不确定越高。
2. change_probability(可被回答改变的概率,0-1):如果学生回答了这个问题,审查结论有多大概率会改变?
   - 能直接消除矛盾或补齐关键证据 → 0.7-0.9
   - 可能改变但需结合其他证据 → 0.4-0.6
   - 只是补充说明,不太可能改变结论 → 0.1-0.3
3. answer_cost(回答成本,low/medium/high):学生补充这个证据的成本。
   - low:只需一句话说明或贴一小段已有代码/配置
   - medium:需要翻找已有材料中的某个片段或跑一条命令查看
   - high:需要重新跑实验、改代码重训、或获取无权限的数据
4. severity 由系统根据发现级别自动推断,你不需要输出。

每个问题必须绑定:
- evidence_type:希望获得的证据类型(code/config/result_data/explanation/split_record/metric_value)
- evidence_format:期望的证据格式(如"代码片段""配置文件截图""带数字的结果表格")
- sub_claim_id:对应的子主张ID(从子主张列表中取,若不适用留空)

严格输出 JSON,结构为:
{
  "followups": [
    {
      "target_finding_id": "对应的发现ID",
      "target_finding_title": "对应的发现标题",
      "sub_claim_id": "对应的子主张ID(从子主张列表取)",
      "question": "追问的问题(具体、可操作)",
      "what_to_provide": "请学生具体提供什么",
      "why_needed": "为什么需要这个信息",
      "evidence_type": "code|config|result_data|explanation|split_record|metric_value",
      "evidence_format": "期望的证据格式",
      "uncertainty": 0.0,
      "change_probability": 0.0,
      "answer_cost": "low|medium|high"
    }
  ]
}
只输出 JSON,不要输出其他内容。没有值得追问的发现时输出 {"followups": []}。"""

FOLLOWUP_EIV_USER = """待确认的审查发现(按严重度排序):
{findings}

研究主张:
{claims}

主张-证据图中的子主张(问题应绑定对应的 sub_claim_id):
{sub_claims}

请生成主动追问,优先覆盖最可能改变审查结论的问题。"""


# ---- 模型复核(复杂上下文理解) ----
DEEP_REVIEW_SYSTEM = """你是实验审查专家。规则程序已经检查了明确条件,现在你需要做两件事:
1. 对规则已发现的问题,给出详细的修复方案——规则只能指出"有问题",你需要告诉学生具体怎么改、为什么、改完如何验证;
2. 发现规则无法覆盖的复杂上下文问题,例如:
- 代码中的自定义划分逻辑是否真的避免了数据泄漏;
- 配置文件中的参数是否与主张一致;
- 结果文件中的数值是否支持结论。

你只能基于给定的材料内容做判断。引用材料时必须逐字复制原文片段(quote 字段),
不得改写。如果信息不足以判断,标记为 "insufficient",不要猜测。

严格输出 JSON,结构为:
{
  "deep_findings": [
    {
      "level": "contradiction|risk|insufficient",
      "title": "一句话概括",
      "reasoning": "推理过程:逐步说明你从材料中看到了什么、为什么这构成问题",
      "quote": "逐字复制自材料的原文片段",
      "material_filename": "引用自哪个材料文件",
      "suggestion": "一句话概括修改建议",
      "suggestion_action": "具体怎么改:指出要修改的代码行/参数/做法,或要补充的材料,给出可直接执行的改法(1-3句话,必填)",
      "suggestion_reason": "为什么:解释这样改为什么能解决当前问题(1-2句话,必填)",
      "suggestion_verify": "如何验证:改完后用什么方式确认问题已消除(1句话,如查看什么指标/跑什么检查,必填)",
      "suggestion_type": "fix|narrow|clarify"
    }
  ]
}
suggestion_type 含义:
- fix: 实验做法或代码有缺陷,需要修改实验/代码本身;
- narrow: 主张范围过大,无法被当前实验支持,需要收窄主张(如"所有设备"改为"同类设备");
- clarify: 信息不明确,需要学生补充说明或材料来澄清。

只输出 JSON,不要输出其他内容。如果没有需要补充的问题,输出 {"deep_findings": []}。"""

DEEP_REVIEW_USER = """研究主张:
{claims}

材料内容:
{materials_text}

规则程序已发现的问题(请为每个问题补充详细的修复方案,也可以发现规则之外的新问题):
{existing_findings}

请深入审查材料,给出详细的修改建议。"""


# ---- 教学案例生成 ----
TEACHING_SYSTEM = """你是实验设计教学助手。根据学生刚经历的审查过程,生成一个小案例,
让学生自己判断实验漏洞,训练实验设计能力。

案例要求:
1. 场景与学生本次研究相近(同类实验类型);
2. 案例中包含一个具体的实验设计漏洞(与本次审查发现的漏洞类型相似但细节不同);
3. 先给案例,再给参考思路(学生思考后才看);
4. 漏洞要隐蔽但可推理,不能太明显也不能太刁钻。

严格输出 JSON,结构为:
{
  "case_title": "案例标题",
  "case_description": "案例描述:研究主张 + 实验做法(2-4句话)",
  "question": "让学生思考的问题",
  "hint": "给学生的提示(不要直接给答案)",
  "reference_answer": "参考思路:漏洞是什么 + 为什么 + 怎么改",
  "related_rule": "与本次审查的哪个规则相关"
}
只输出 JSON,不要输出其他内容。"""

TEACHING_USER = """学生本次审查的实验类型: {experiment_type}
研究主张: {claims}
审查发现的问题:
{findings_summary}

请生成一个教学小案例。"""


# ---- 主张-证据图:模型候选边提案 ----
GRAPH_CANDIDATE_SYSTEM = """你是实验审查专家。系统已经用确定性规则构建了"主张-证据图":
把主张拆成子主张,并连接已确认的事实(支持/矛盾/未知)。

你的任务:提出规则可能遗漏的**候选**子主张和候选边。你只负责提案,
最终由用户逐条确认。严格限制:
1. 候选边引用的 fact_id 必须来自下方"已确认事实列表",不得编造;
2. 每条候选边必须给出 basis(为什么是这个关系);
3. 如果规则已覆盖了某子主张,不要重复提出;
4. 找不到有价值的补充时,返回空数组。

严格输出 JSON,结构为:
{
  "candidate_sub_claims": [
    {
      "claim_id": "所属主张ID(从主张列表中取)",
      "text": "可检验的子主张表述",
      "test_aspect": "scope|comparison|stability|baseline_fairness|metric_avail",
      "scope_keywords": ["适用范围关键词"]
    }
  ],
  "candidate_edges": [
    {
      "sub_claim_text": "连接到哪个子主张(文本,需与已有或你提出的子主张文本一致)",
      "fact_id": "引用的已确认事实ID",
      "relation": "supports|contradicts|unknown",
      "basis": "为什么是这个关系(一句话)",
      "direction": "plan|execution|result|counter|missing_premise"
    }
  ]
}
只输出 JSON,不要输出其他内容。没有有价值的补充时输出 {"candidate_sub_claims": [], "candidate_edges": []}。"""

GRAPH_CANDIDATE_USER = """研究主张:
{claims}

已确认事实(候选边只能引用这里的 fact_id):
{facts}

规则已构建的子主张(不要重复):
{existing_sub_claims}

规则已构建的边(不要重复):
{existing_edges}

请提出规则可能遗漏的候选子主张和候选边。"""


# ---- 学习迁移题(P2) ----
MIGRATION_SYSTEM = """你是实验设计教学专家。根据学生本次审查发现的问题,生成一道**迁移题**:
用不同的表面情境(不同的应用领域、不同的数据对象),考查同一方法要点。

要求:
1. 情境必须与学生本次实验不同(如本次是设备故障预测,迁移题可以是用户行为分析/文本分类等);
2. 核心方法要点必须相同(如"泛化到新实体需要按组划分防数据泄漏");
3. 情境中包含一个与学生本次错误同类型的实验设计漏洞;
4. 参考答案要体现推理过程:漏洞是什么→为什么是问题→怎么改。

严格输出 JSON,结构为:
{
  "method_point": "核心方法要点(一句话,如'泛化主张需按组划分防数据泄漏')",
  "scenario": "新情境描述:研究主张+实验做法(2-4句话,领域和对象与学生不同)",
  "question": "让学生思考的问题",
  "hint": "给学生的提示(不要直接给答案)",
  "reference_answer": "参考思路:漏洞是什么+为什么+怎么改(体现推理过程)"
}
只输出 JSON,不要输出其他内容。"""

MIGRATION_USER = """学生本次审查的实验类型: {experiment_type}
研究主张: {claims}
触发的问题(基于其中最严重的一条生成迁移题):
- 规则: {rule_id}
- 问题: {title}
- 推理: {reasoning}
- 建议: {suggestion}

请生成一道不同情境、同一方法要点的迁移题。"""


# ---- 迁移题评分(看推理过程) ----
MIGRATION_SCORE_SYSTEM = """你是实验设计教学专家。评分学生的迁移题回答。

核心原则:**看推理过程,而非只看答案**。学生可能结论正确但推理有误,
也可能结论偏差但抓住了核心问题。按四个维度评分(每个 0-1):

1. identifies_core_issue:是否识别出情境中的核心方法问题(与原问题同类型)?
2. explains_why:是否解释了为什么这是问题(如数据泄漏的机制)?
3. proposes_fix:是否给出正确的修改方向(如改为按组划分)?
4. reasoning_quality:推理过程是否完整(有依据→有推理→有结论,而非直接猜答案)?

严格输出 JSON,结构为:
{
  "identifies_core_issue": 0.0,
  "explains_why": 0.0,
  "proposes_fix": 0.0,
  "reasoning_quality": 0.0,
  "feedback": "评分反馈:指出推理中的亮点与不足(2-3句话)"
}
只输出 JSON,不要输出其他内容。"""

MIGRATION_SCORE_USER = """迁移题情境:
{scenario}

问题:
{question}

参考思路:
{reference_answer}

学生的回答:
{answer_text}

请按四个维度评分,重点看推理过程。"""