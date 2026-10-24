# 黄金评测集

阶段 0 目标：准备 **50 个真实业务问数原话**。阶段 1 第 6 周接入自动回归。

## 题目格式（每行一条 JSONL）

| 字段 | 说明 |
|---|---|
| id | q001 起顺序编号 |
| question | 业务用户的**原话**，不要改写（找运营/分析师直接收集，禁止自己编） |
| domain | 所属业务域（试点：交易域） |
| metric | 对应指标名（阶段 1 与指标语义服务的 name 对齐） |
| expected_sql | 分析师确认的标准 SQL（可以后补） |
| expected_result_features | 结果特征：`columns`（列名）、`row_count`（行数）、`sample_rows`（关键行） |
| source_user | 提供人（用于追问歧义） |
| collected_at | 收集日期 |

## 收集动作（本周内完成）

1. 找 2-3 位运营/分析师，请他们把最近一周真实问过数据同学的问题原话发来（聊天记录截图转文字即可），目标 50 条
2. 每条请分析师补「正确口径一句话 + 在 demo/真实库里对应的表」
3. 汇总到 `evals/golden/questions.jsonl`（不入 git 的真实业务数据放团队共享盘，仓库里只放结构与样例）
4. 歧义题（同一问法两种理解）保留并标注，是语义层设计的重要输入

## 判定方式（阶段 1 自动化）

1. SQL 能否执行
2. 执行结果集与 expected_result_features 的集合比对（顺序无关）
3. 图表/维度类型规则判定

### 结果集比对的类型归一化（Task 4 复审 Minor）

网关 `_jsonable` 会改变部分 Python 类型，比对器必须在比较前做归一化，否则会静默失配：

- 绝对值超 2^53 的 BIGINT（如雪花 ID）返回**字符串**保精度 → 大整数列统一按字符串比对
- Decimal/DECIMAL 转 float，高精度金额可能丢末位 → 金额列按容差（如 abs 差 < 1e-6 或相对误差）比对
- 非有限值（inf/NaN）与 PG numeric sNaN 分别归一化为 null / 字符串
- MySQL TIME 返回 "HH:MM:SS" 字符串；date/datetime 为 ISO 字符串
