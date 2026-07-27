# 统计套利论文复刻项目：AI 协作规范

最后更新：2026-07-27  
适用范围：本目录及所有子目录

## 1. 项目目标与当前状态

本项目分阶段复刻 Cartea、Cucuringu 与 Jin 的论文 *Correlation Matrix Clustering for Statistical Arbitrage Portfolios*。目标是先得到时间语义清楚、可审计、可测试的论文复刻，再把用户确认的策略修改作为独立口径实现。

当前已经使用 Python 3.11、DuckDB 和 Excel 报告完成：

1. Yahoo 近似数据集、动态股票池和数据审计；
2. 60 日滚动 beta、市场残差收益和相关矩阵快照；
3. 20 日相关矩阵累计方差解释率确定动态 `K`；
4. `SPONGE_sym` 聚类；
5. previous winners / previous losers / neutral 分类；
6. 单个决策日的只做多组合权重。

尚未实现：

- 跨日持仓状态；
- `l=3` 的定期再平衡；
- `q=5%` 的提前止盈再平衡；
- 完整回测、基准、交易成本、滑点和绩效评价；
- FF12 行业标签。

不得把 notes 中的第 7 阶段直接视为已经实现或完全确认。开始回测前，仍需和用户确认事件顺序、收益记账、持仓生效时点、现金处理及止盈后的再建仓规则。

## 2. 权威资料与冲突处理

### 2.1 主要资料

- 主论文：`references/Correlation_Matrix_Clustering_for_Statistical_Arbitrage_Portfolios_CarteaAlvaro_JinQi_CucuringuMihai.pdf`
- 用户笔记：`references/Markdown_Notes.zip`
- 作者聚类示例：<https://github.com/maxclchen/Correlation-Matrix-Clustering-for-Statistical-Arbitrage-Portfolios>
- 扩展论文与 PPT：`references/`
- 当前实现：`src/`
- 当前行为的自动化证据：`tests/`
- 用户入口与运行说明：`README.md`

### 2.2 信息优先级

发生冲突时按以下顺序处理：

1. 用户当前的明确要求；
2. 用户已确认的项目决定；
3. 主论文；
4. 用户 notes 和作者示例；
5. 当前代码和测试所记录的现状；
6. 次级资料与 AI 建议。

代码可以证明“现在做了什么”，不能自动证明“研究上应该做什么”。若代码与更高优先级来源冲突，必须指出差异和影响，再确认是改代码还是修文档；不得用现状静默覆盖研究口径。

## 3. 已确认口径与论文偏差

### 3.1 数据

论文使用 2000-01 至 2022-12 的 CRSP 日频数据、NYSE/Amex/NASDAQ 普通股、市值前 25%，并使用拆股和股息调整后的收益。当前项目采用已确认的 **Yahoo Approximate Price-Return Baseline**：

- 默认从 `2020-01-01` 开始，结束于运行日前一日；
- 市场收益使用 SPY；
- Yahoo 当前 screener 近似 NYSE、NYSE American、NASDAQ 普通股候选集；
- 每个交易日 `t` 只使用前一 SPY 交易日 `t-1` 的市值和流动性信息；
- 每个发行人保留一条股票线，再选择市值前 `500` 个发行人；
- Alphabet 固定使用 `GOOG`；其他多类别发行人按截至 `t-1` 的 60 个市场交易日平均成交额选主类别；
- 历史股数只向未来沿用，不用未来或当前股数向过去回填；
- 股票和 SPY 的策略收益均由 Yahoo `Close` 计算，保持拆股尺度一致但不含股息；
- `adjusted_close`、股息和 `total_return` 只保留用于核对；
- `ff12_code` 当前为空。

这是近似数据口径，不是严格 CRSP 复刻。当前 Yahoo screener 无法完整发现历史退市证券，因此仍有 survivorship bias；普通股过滤也不等同于 CRSP `SHRCD 10/11`。

### 3.2 预处理与决策时点

- 每个股票交易日 `t` 的 beta 使用包含 `t` 的连续 60 个 SPY 交易日：

  ```text
  beta(i,t) = Cov(R(i), R(mkt)) / Var(R(mkt))
  residual(i,t) = R(i,t) - beta(i,t) * R(mkt,t)
  ```

- 不估计或扣除 alpha；
- 60 日窗口必须有 60 个完整股票/市场收益观测；不填零、不前向填充；
- `as_of_date=T` 表示在 `T` 日交易前形成决策，股票池使用 `eligible_date=T`，所有信号输入严格截止于 `T-1`；
- 实际聚类和选股窗口默认共用 `w=5` 个交易日；
- 缺少完整窗口或 5 日残差方差为零的股票不进入相关矩阵，并记录排除原因。

### 3.3 动态 K

- 使用 `T` 之前 20 个 SPY 交易日的市场残差收益构造独立 Pearson 相关矩阵；
- 特征值降序排列；
- 默认选择累计解释率首次达到 `P=90%` 的最小 `K`；
- 20 日窗口只用于确定 `K`，不替代实际聚类使用的 5 日相关矩阵；
- 该步骤在内存中计算，不持久化 K 或特征值。

### 3.4 SPONGE_sym

当前实现采用用户已确认的作者 notebook / 旧 SigNet 兼容口径：

```text
eigenvector_count = K - 1
embedding[:, j] = generalized_eigenvector[:, j] / eigenvalue[j]
```

这不同于论文第 2.1.3 节文字所述的“K 个最小广义特征向量直接组成 K 维 embedding”。不得把当前结果称为纯论文文字基线。未来若实现论文口径，应使用独立计算版本并做对照实验。

当前默认：

- `tau_positive=1`；
- `tau_negative=1`；
- `random_seed=0`；
- `kmeans_n_init=10`；
- cluster ID 从 `0` 开始，数字标签没有跨日期的经济含义。

### 3.5 股票分类

对每个 cluster，在 `T` 前 `w=5` 日用原始价格收益计算：

```text
deviation(i) = sum(raw_return(i,t) - cluster_mean(t))
winner: deviation(i) > p
loser:  deviation(i) < -p
neutral: -p <= deviation(i) <= p
```

- 主论文基线为 `p=0`；
- `StockSelectionConfig` 的库级默认仍为 `0.0`；
- 当前 CLI 和 IDE 导出脚本按用户决定默认使用 `p=0.05`，以减少实际持仓数量；
- notes 中 loser 条件曾误写为 `> p`，代码按主论文使用 `< -p`；
- 等于阈值时归为 neutral。

### 3.6 只做多权重

论文是 cluster 内做多 losers、做空 winners 的多空策略。当前项目按用户决定改为只做多：

```text
loser local weight = 1 / cluster loser count
winner and neutral local weight = 0
portfolio weight = local weight / K
```

- 有至少一个 loser 的 cluster 为 active；
- 没有 loser 的 cluster 为 inactive；
- 每个 cluster 的目标额度固定为 `1/K`；
- inactive cluster 的额度保留为未投资现金，不重新分配；
- 因此实际组合总权重可能小于 1。

不得把该只做多结果描述为论文的市场中性组合。

## 4. 当前代码边界

### 4.1 模块职责

- `stat_arb_data`：Yahoo 获取、证券过滤、股票池、DuckDB catalog 与浏览；
- `stat_arb_preprocessing`：逐日 beta/残差、点时相关矩阵快照与缓存；
- `stat_arb_cluster_count`：动态 K；
- `stat_arb_clustering`：`SPONGE_sym` 与 k-means++；
- `stat_arb_stock_selection`：winner/loser/neutral；
- `stat_arb_portfolio_weights`：单日只做多权重；
- `scripts/`：适合 IDE 直接运行的入口；
- `tests/`：离线单元与集成测试。

依赖方向应保持从后续阶段指向前序阶段，不允许前序模块反向依赖策略、组合或回测模块。公共计算规则只保留一个权威实现；Excel 文件是审计输出，不是下游计算输入。

### 4.2 持久化边界

DuckDB 持久化：

- `market_data`：证券、行情、历史股数、市值和股票池；
- `audit`：运行、参数、字段字典和问题；
- `browse`：便于人工查看的只读视图；
- `preprocessing`：逐日 beta/残差及按需快照缓存。

动态 K、聚类、选股和权重当前只在内存中计算并导出 Excel，不新增对应 DuckDB 结果表。除非后续阶段明确需要，不能为方便而改变这一边界。

### 4.3 IDE 脚本与 CLI 默认值

必须区分两种入口：

- CLI 默认安全：下载保留全部当前可发现发行人，已有数据库和 Excel 不显式 `--replace` 时拒绝覆盖；
- `scripts/*.py` 是用户可编辑入口，当前多个导出脚本设置 `REPLACE_EXISTING=True`；
- `scripts/run_data_download.py` 当前设置 `CANDIDATE_POOL_SIZE=1500` 和 `REPLACE_EXISTING_DATABASE=True`，并非 CLI 默认值。

修改文档或行为时必须分别核对两套入口，不能笼统写成一个“默认值”。

## 5. 分阶段协作规则

开始任何新阶段前，只对齐完成该阶段所必需的事项：

- 目标、范围和非目标；
- 对应论文、notes 与现有代码；
- 输入、输出及其 schema；
- 决策时点、观察窗口、持仓生效和数据可用性；
- 论文未说明或来源冲突的内容；
- 论文基线与项目修改是否需要并行口径；
- 最小代码结构；
- 验收样例、质量检查和回归测试。

若用户已经完整说明，复述关键约束后即可实现。若歧义会实质改变收益、持仓、风险或论文复刻结论，应先给出推荐方案并等待确认。

不要提前实现尚未讨论的阶段。可以提出后续建议，但不能静默加入会改变策略含义的功能。

## 6. 编码与研究规范

- 使用清晰、务实的 OOP、SRP、DIP、DRY 和 KISS；不为未来假设过度抽象；
- 数学计算、编排、持久化和 Excel 展示保持分离；
- 所有输入矩阵必须校验标签、形状、排序、有限值及时间窗口；
- 随机过程必须显式记录 seed 和关键库参数；
- 数据库发布、缓存替换和文件覆盖应保持失败安全；
- 不使用未来数据填补过去，不静默改变缺失值规则；
- 不能只根据最终收益判断复刻正确性，应先核对股票池、窗口、beta、残差、相关矩阵、K、clusters、信号和权重；
- notebook 可用于研究，但不能成为生产逻辑的唯一来源；
- 新功能和 bug 修复必须添加与风险相称的自动化测试；
- 默认运行：

  ```powershell
  .\.venv\Scripts\python.exe -m unittest discover -s tests -v
  ```

截至 2026-07-27，测试套件共有 68 项，全部通过。

## 7. 回测阶段的待确认清单

用户 notes 给出的研究方向是 `l=3` 日再平衡和 `q=5%` 组合止盈，但实现前至少需要确认：

1. `T` 日生成的权重从 `T` 开盘、收盘还是 `T+1` 生效；
2. 组合日收益使用 close-to-close 还是其他可交易口径；
3. “经过 3 天”的精确计数和再平衡优先级；
4. `q=5%` 是从本轮建仓起的简单累计收益、复利净值收益还是其他定义；
5. 止盈在收盘后触发时，新组合何时生效；
6. inactive cluster 的现金收益如何处理；
7. 股票退出股票池、停牌、缺价、退市和公司行为如何处理；
8. 是否先实现无成本基线，再单独加入费用与滑点；
9. 基准、绩效指标和论文结果的对比方式；
10. 动态 K、clusters 和信号是否每个再平衡日全部重算。

在这些问题确认前，不得自行实现一个看似合理但研究含义不明确的回测器。

## 8. 沟通要求

- 默认使用中文解释，代码标识符使用清晰英文；
- 明确区分“论文规定”“用户确认”“当前代码”“AI 建议”和“尚待确认”；
- 完成后说明输入、输出、时间语义、边界情况、测试结果与已知限制；
- 发现代码、notes、论文或 README 不一致时主动报告；
- 改进研究必须说明它解决的问题、与论文的偏差、风险、复杂度和对照实验；
- 交易成本、滑点、协方差收缩、风险约束、机器学习过滤、Kelly sizing 等不得静默混入基线。
