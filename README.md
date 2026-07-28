# Correlation Matrix Clustering 统计套利复刻

本项目分阶段复刻 Cartea、Cucuringu 与 Jin 的论文 *Correlation Matrix Clustering for Statistical Arbitrage Portfolios*。当前代码已经贯通从点时信号到跨日回测的完整研究链路：

```text
Yahoo 数据 → 动态股票池 → beta / 市场残差收益 → 动态 K
          → SPONGE_sym clusters → winners / losers → 只做多权重
          → 固定份额持仓 → l/q 事件再平衡 → SPY 与绩效评价
```

目前已完成阶段 1–7。

## 项目状态

| 阶段 | 状态 | 当前实现 |
|---|---:|---|
| 1. Data | 已完成 | Yahoo 行情、历史股数、SPY、逐日动态前 500 股票池、DuckDB |
| 2. Data Pre-Processing | 已完成 | 60 日 beta、市场残差收益、5 日相关矩阵快照 |
| 3. Number of Clusters K | 已完成 | 20 日相关矩阵、累计方差解释率 90% |
| 4. Clustering | 已完成 | `SPONGE_sym` SigNet 兼容 embedding、k-means++ |
| 5. Identify Stocks | 已完成 | previous winner / loser / neutral |
| 6. Assign Weights | 已完成 | 单决策日、只做多、cluster 等额度 |
| 7. Backtest & Rebalance | 已完成 | 固定份额持仓、`l=3`、复利 `q=5%`、SPY 与无成本绩效评价 |

## 论文口径与当前项目口径

当前实现不是对论文数据和组合规则的逐字复制。重要差异如下：

| 项目 | 论文 | 当前代码 |
|---|---|---|
| 数据源与时期 | CRSP，2000-01 至 2022-12 | Yahoo，默认从 2020-01-01 至运行日前一日 |
| 股票池 | NYSE/Amex/NASDAQ 普通股，市值前 25% | Yahoo 普通股近似口径，每日市值前 500 个发行人 |
| 收益 | 拆股和股息调整后收益 | Yahoo `Close` 价格收益，拆股尺度一致、不含股息 |
| FF12 | 有行业标签 | `ff12_code` 暂为空 |
| 动态 K | 论文动态方法 | 20 日残差相关矩阵，累计解释率 90% |
| SPONGE embedding | 论文文字：K 个原始特征向量 | 作者 notebook/SigNet 兼容：K-1 个向量并除以特征值 |
| 信号阈值 p | `0` | CLI 与 IDE 脚本默认 `0.05` |
| 组合 | 做多 losers、做空 winners | 只做多 losers |

因此，当前结果应称为 **Yahoo Approximate Price-Return、SigNet-compatible、Long-only 项目口径**。严格论文复刻仍需要历史证券主表（如 CRSP/WRDS）、含股息收益及论文多空组合。

## 安装

要求 Python 3.11 或更高版本。在 PowerShell 中执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .
```

主要依赖为 DuckDB、pandas、NumPy（由依赖间接安装）、SciPy、scikit-learn、openpyxl 和 yfinance。

## 推荐运行方式：IDE 脚本

`scripts/` 中每个入口的参数都集中在文件顶部，适合在 PyCharm 或 VS Code 中修改后直接运行：

1. `scripts/run_data_download.py`
2. `scripts/run_preprocessing.py`
3. `scripts/export_preprocessing_snapshot.py`
4. `scripts/export_cluster_count.py`
5. `scripts/export_clustering.py`
6. `scripts/export_stock_selection.py`
7. `scripts/export_portfolio_weights.py`
8. `scripts/export_backtest.py`

注意：

- 单日导出脚本当前示例日期为 `2026-07-17`；回测脚本显式设置 `START_DATE` 和 `END_DATE`，运行前应核对；
- 多个 IDE 导出脚本当前设置 `REPLACE_EXISTING=True`；
- `run_data_download.py` 当前设置 `CANDIDATE_POOL_SIZE=1500`、`REPLACE_EXISTING_DATABASE=True`；
- 这些是脚本内的当前设置，不是 CLI 的安全默认值。

默认数据库为 `data/yahoo_market_data.duckdb`。

## 命令行完整流程

以下示例使用 `2026-07-17` 作为决策日 `T`。`T` 必须是数据库中的 SPY 交易日，并且存在该日的股票池。

### 1. 下载数据

```powershell
.\.venv\Scripts\python.exe -m stat_arb_data download
```

CLI 默认：

- `start=2020-01-01`；
- `end=运行日前一日`；
- `top-n=500`；
- 不做当前市值候选集预筛选；
- 若数据库已存在则拒绝覆盖。

完整下载需要对当前可发现的普通股候选逐一请求历史股数，可能耗时较长并触发 Yahoo 限流。建议先运行小规模验证：

```powershell
.\.venv\Scripts\python.exe -m stat_arb_data download `
  --candidate-pool-size 20 `
  --top-n 10 `
  --database data\smoke_test.duckdb
```

确认重建已有数据库时显式增加 `--replace`。程序先在同目录构建临时 DuckDB，只有完整成功后才原子替换正式文件；失败时保留旧数据库。

### 2. 构建逐日 beta 和市场残差收益

```powershell
.\.venv\Scripts\python.exe -m stat_arb_preprocessing build `
  --database data\yahoo_market_data.duckdb
```

对历史上至少进入过一次股票池的股票，在每个 SPY 交易日 `t` 使用包含当日的连续 60 个交易日计算：

```text
beta(i,t) = Cov(R(i), R(mkt)) / Var(R(mkt))
residual(i,t) = R(i,t) - beta(i,t) * R(mkt,t)
```

窗口必须有 60 个完整的股票和市场收益观测；不填零、不前向填充，也不估计 alpha。结果写入 `preprocessing.daily_market_residuals`。

### 3. 导出预处理快照

```powershell
.\.venv\Scripts\python.exe -m stat_arb_preprocessing export `
  --database data\yahoo_market_data.duckdb `
  --as-of-date 2026-07-17 `
  --output outputs\step2_preprocessing\preprocessing_snapshot_2026-07-17.xlsx
```

`as-of-date=T` 表示在 `T` 日交易前构造快照：

- 股票池使用 `eligible_date=T`；
- beta、股票收益、SPY 收益和残差只使用 `T` 之前 5 个 SPY 交易日；
- 窗口不完整或 5 日残差方差为零的股票整列剔除；
- 排除原因写入数据库缓存和 Excel。

Excel 工作表：

- `Summary`
- `Beta_Used`
- `Stock_Returns`
- `Residual_Matrix`
- `Correlation_Matrix`
- `Excluded_Stocks`

### 4. 确定动态 K

```powershell
.\.venv\Scripts\python.exe -m stat_arb_cluster_count export `
  --database data\yahoo_market_data.duckdb `
  --as-of-date 2026-07-17 `
  --cluster-count-estimation-window 20 `
  --variance-threshold 0.90 `
  --output outputs\step3_cluster_count\cluster_count_2026-07-17.xlsx
```

程序使用 `T` 前 20 个交易日的市场残差收益构造独立相关矩阵，并计算：

```text
K = min { k : sum(lambda[1:k]) / sum(lambda[1:N]) >= 0.90 }
```

20 日窗口只用于确定 K；实际图聚类仍使用 5 日窗口。Excel 包含 `Summary` 和 `Eigenvalues`。该步骤不把相关矩阵、特征值或 K 持久化到 DuckDB。

### 5. 运行 SPONGE_sym 聚类

```powershell
.\.venv\Scripts\python.exe -m stat_arb_clustering export `
  --database data\yahoo_market_data.duckdb `
  --as-of-date 2026-07-17 `
  --clustering-correlation-window 5 `
  --cluster-count-estimation-window 20 `
  --variance-threshold 0.90 `
  --tau-positive 1 `
  --tau-negative 1 `
  --seed 0 `
  --n-init 10 `
  --output outputs\step4_clustering\sponge_sym_clusters_2026-07-17.xlsx
```

当前计算版本为 `sponge_sym_signet_compat_v1`：

```text
eigenvector_count = K - 1
embedding[:, j] = generalized_eigenvector[:, j] / eigenvalue[j]
```

这与论文文字描述的 K 维原始特征向量口径不同，但与作者 notebook 调用的旧 SigNet 行为兼容。随机种子和 `n_init` 被显式固定以保证可复现。

Excel 工作表：

- `Summary`
- `Eigenvalues`
- `Spectral_Embedding`
- `Cluster_Assignments`

cluster ID 从 `0` 开始；标签数字不应跨日期直接比较。

### 6. 识别 previous winners 和 losers

```powershell
.\.venv\Scripts\python.exe -m stat_arb_stock_selection export `
  --database data\yahoo_market_data.duckdb `
  --as-of-date 2026-07-17 `
  --lookback-window 5 `
  --deviation-threshold 0.05 `
  --output outputs\step5_stock_selection\stock_signals_2026-07-17.xlsx
```

对每个 cluster 和 `T` 前 5 个交易日：

```text
deviation(i) = sum(raw_return(i,t) - cluster_mean(t))
winner: deviation(i) > p
loser:  deviation(i) < -p
neutral: -p <= deviation(i) <= p
```

这里使用股票原始价格收益，不使用市场残差收益。主论文 `p=0`；当前 CLI 和 IDE 脚本默认 `p=0.05`，这是为减少持仓数量而确认的项目修改。等于阈值时归为 neutral。

Excel 工作表：

- `Summary`
- `Raw_Returns`
- `Cluster_Mean_Returns`
- `Daily_Deviations`
- `Trade_Signals`

### 7. 分配单日只做多权重

```powershell
.\.venv\Scripts\python.exe -m stat_arb_portfolio_weights export `
  --database data\yahoo_market_data.duckdb `
  --as-of-date 2026-07-17 `
  --lookback-window 5 `
  --deviation-threshold 0.05 `
  --output outputs\step6_portfolio_weights\portfolio_weights_2026-07-17.xlsx
```

当前项目只买入 previous losers：

```text
loser local weight = 1 / loser count in cluster
winner and neutral local weight = 0
portfolio weight = local weight / K
```

每个 cluster 的目标额度为 `1/K`。没有 loser 的 cluster 为 inactive，其额度保留为未投资现金，不分配给其他 clusters。因此组合实际总权重可能小于 1。

Excel 工作表：

- `Summary`
- `Cluster_Allocations`
- `Stock_Weights`

第五、六阶段会在内存中重新运行动态 K、聚类和信号计算，不读取前一步 Excel，也不在 DuckDB 中保存这些下游结果。

所有 Excel 导出在文件已存在时默认拒绝覆盖；确认覆盖时增加 `--replace`。

### 8. 跨日回测与再平衡

```powershell
.\.venv\Scripts\python.exe -m stat_arb_backtest export `
  --database data\yahoo_market_data.duckdb `
  --start-date 2026-07-13 `
  --end-date 2026-07-17 `
  --rebalance-period 3 `
  --take-profit-threshold 0.05 `
  --lookback-window 5 `
  --deviation-threshold 0.05 `
  --output outputs\step7_backtest\backtest_2026-07-13_2026-07-17.xlsx
```

`start-date` 和 `end-date` 必须显式提供。`start-date` 是允许开始回测的最早自然日；若它不是 SPY 交易日，程序顺延到下一个 SPY 交易日，并将该日记录为结果和 Excel 中的实际开始日。`end-date` 仍必须是 SPY 交易日。初始目标使用 `as_of_date=实际开始日`，所以信号只使用实际开始日前的数据。

CLI 与 `scripts/export_backtest.py` 默认显示 `tqdm` 交易日进度、运行速度和预计剩余时间。CLI 自动化运行时可传入 `--no-progress` 关闭；Python API 的 `show_progress` 默认为 `False`。

每轮组合按建仓时的经济份额持有，权重随价格自然漂移，不进行隐含的每日再平衡：

- 获得 3 个日收益后，在第 3 日收盘边界执行定期换仓；
- 第 1 或第 2 日的本轮复利净值收益达到 `5%` 时提前换仓；
- 事件日收益归旧组合，新组合从下一 SPY 交易日起获得收益；
- 第 3 日同时达到止盈阈值时仍记录为定期换仓；
- inactive cluster 和未成交额度保留为零收益现金。

缺少有效 Close 时，持仓按上一有效 Close 估值并冻结。事件日的冻结腿不参与新目标资本；可交易部分先换仓且不使用杠杆。仍属于新目标的冻结腿恢复后继续持有；已退出新目标的冻结腿恢复后卖为现金，不追补之前未完成的目标仓位。所有缺价、冻结、恢复和未成交行为写入审计表。

Excel 工作表：

- `Summary`
- `Daily_Performance`
- `Rebalance_Events`
- `Target_Weights`
- `Trades`
- `Missing_Data_Audit`

`Target_Weights` 只保存 `portfolio_weight > 0` 的实际做多股票，避免为每次换仓重复输出 previous winners、neutral 和其他零权重股票。单决策日的 stock-selection 与 portfolio-weight 报告仍保留完整横截面，便于核对分类和零权重规则。

策略与 SPY 使用相同日期，风险利率和现金收益均为零。报告给出复利年化收益、年化 Sharpe 和按负收益样本标准差计算的 Sortino。回测结果只在内存中计算并导出 Excel，不写入 DuckDB。

## 查看 DuckDB

在 IDE 中运行 `scripts/view_data.py`，或在命令行执行：

```powershell
.\.venv\Scripts\python.exe -m stat_arb_data open
```

首次使用 DuckDB 官方本地 UI 时需要联网安装 `ui` 扩展。查看结束后回到启动终端按 Enter，停止 UI 并释放数据库。

快速查看表行数和近期下载问题：

```powershell
.\.venv\Scripts\python.exe -m stat_arb_data inspect
```

当前 catalog：

- `market_data`：`security_master`、`daily_prices`、`shares_outstanding`、`market_returns`、`daily_market_cap`、`universe_membership`；
- `audit`：数据下载与预处理运行、设置、字段字典和下载问题；
- `browse`：`daily_universe`、`latest_universe`、`daily_quality`；
- `preprocessing`：逐日 beta/残差，以及按需缓存的快照元数据、残差、相关矩阵上三角和排除原因。

`browse.daily_universe.strategy_return` 等于不含股息的 `price_return`。

早期 `meta/raw/core/quality/browse` 五 schema 数据库可原地升级，无需重新下载：

```powershell
.\.venv\Scripts\python.exe -m stat_arb_data upgrade-catalog
```

升级前必须关闭 DuckDB UI。升级先复制到临时库并核对关键表行数，成功后才替换原文件。

## 时间语义与防止前视偏差

这是本项目最重要的约束：

- 股票池在交易日 `T` 生效，但排名信息来自前一 SPY 交易日；
- beta 可以在历史日 `t` 使用该日收盘收益，因为它只用于未来决策日的历史窗口；
- 决策日 `T` 的任何相关矩阵、K、cluster、信号和权重都只使用 `T` 之前的数据；
- 不使用未来股数向过去回填；
- 缺失窗口不填零、不前向填充；
- 回测目标 `as_of_date=T` 只用至 `T-1` 的输入，并获得日期为 `T` 的 close-to-close 收益；
- 事件日 `T` 先结算旧组合，再用截至 `T` 的信息形成 `T+1` 目标；新组合不重复获得 `T` 日收益。

## 测试

测试完全离线，不调用 Yahoo 网络接口：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

截至 2026-07-28，共 86 项测试，全部通过。测试覆盖：

- 数据库失败安全发布和 catalog 升级；
- Yahoo 字段规范化、普通股近似过滤和拆股处理；
- `t-1` 股票池、历史股数和发行人单一股票线；
- beta、残差、快照缓存、缺失窗口和相关矩阵质量；
- 动态 K 的阈值与数值边界；
- `SPONGE_sym` embedding、可复现性和求解失败；
- winner/loser 严格阈值；
- 只做多权重、inactive cluster 现金保留；
- 固定份额漂移、`l=3`、`q=5%`、事件日收益归属和计数重置；
- 缺价冻结、部分换仓、目标内恢复持有、目标外恢复清算、SPY 对齐和绩效公式；
- 回测全链路只读 DuckDB 边界；
- Excel 结构和禁止静默覆盖。

## 代码结构

```text
src/
  stat_arb_data/               数据获取、股票池、DuckDB
  stat_arb_preprocessing/      beta、残差、相关矩阵快照
  stat_arb_cluster_count/      动态 K
  stat_arb_clustering/         SPONGE_sym
  stat_arb_stock_selection/    winner / loser / neutral
  stat_arb_portfolio_weights/  只做多权重
  stat_arb_backtest/           跨日状态、l/q 再平衡、绩效与审计报告
scripts/                       IDE 入口
tests/                         离线单元与集成测试
references/                    主论文、notes、扩展论文和 PPT
data/                          本地 DuckDB
outputs/                       Excel 研究输出
```

## 已知限制与下一阶段

当前最重要的限制：

- Yahoo 当前候选集不能完整覆盖历史退市证券，存在 survivorship bias；
- Yahoo 普通股筛选和发行人标识都是近似值；
- 当前收益不含股息，与论文数据口径不同；
- FF12 尚未填充；
- 当前 SPONGE embedding 是作者代码兼容口径，不是论文文字口径；
- `p=5%` 和只做多均为项目修改；
- 回测尚未加入交易成本、滑点、融资利息和正现金收益；
- 缺价使用冻结及按新目标决定恢复持有/清算的规则，但 Yahoo 不提供可靠的历史退市收益，因此永久退市风险仍无法严格复刻；
- FF12 基准尚未实现。

第七步是 **Yahoo Approximate Price-Return、SigNet-compatible、Long-only、No-cost** 项目基线，不应与论文的 CRSP 多空市场中性结果直接等同。交易成本、滑点和 FF12 应作为后续独立口径加入并保留无成本对照。
