// 演示用示例数据:含一处典型缺陷(计划按设备划分,执行却用了记录级随机划分)
// 该缺陷会触发"数据划分一致性"与"主张泛化范围"两条规则的明确矛盾发现

export const DEMO_TITLE = '设备故障预测模型对比实验'

export const DEMO_CLAIMS = '模型 A 比基线 B 更能预测新设备的故障,且更稳定。'

export const DEMO_PLAN = `实验计划:设备故障预测模型对比

一、研究目标
验证模型 A(基于注意力机制的双向 LSTM)在设备故障预测任务上优于基线 B(逻辑回归)。

二、数据集
工业设备运行数据,共 100 台设备、12000 条运行记录,每条记录含 36 个传感器特征与故障标签。

三、数据划分
按设备划分:训练集为设备 001-080,测试集为设备 081-100(未见设备),确保评估泛化到新设备的能力。

四、评价指标
准确率(accuracy)、召回率(recall)、F1 分数。

五、基线方法
基线 B:逻辑回归(LogisticRegression),使用相同特征与划分。

六、重复运行
每组实验重复 5 次,报告均值±标准差。`

export const DEMO_EXECUTION = `# train.py —— 模型 A 训练与评估
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, recall_score, f1_score

# 数据加载:100 台设备共 12000 条记录
X, y = load_data()

# 数据划分
X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42
)

# 基线 B
baseline = LogisticRegression(max_iter=1000)
baseline.fit(X_train, y_train)

# 模型 A
model_a = AttentionBiLSTM(input_dim=36)
model_a.fit(X_train, y_train, epochs=20)

# 评估
y_pred_a = model_a.predict(X_test)
y_pred_b = baseline.predict(X_test)
acc_a = accuracy_score(y_test, y_pred_a)
f1_a = f1_score(y_test, y_pred_a)
print(f"模型 A: acc={acc_a:.4f}, f1={f1_a:.4f}")
print(f"基线 B: acc={accuracy_score(y_test, y_pred_b):.4f}")`