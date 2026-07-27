# 统计套利论文复刻：数据阶段

本阶段实现用户确认的 **Yahoo Approximate Price-Return Baseline**：

- 数据范围从 `2020-01-01` 开始；默认结束于运行日前一日。
- 候选集默认保留 Yahoo 当前可发现的全部 NYSE、NYSE American 和 NASDAQ 普通股发行人；可选地按当前发行人市值预筛选。
- 普通股使用 Yahoo `quoteType=EQUITY` 并排除明显优先股、权证、单位和权利作为近似口径；它并不等同于 CRSP `SHRCD 10/11`。
- 每个交易日 `t` 使用前一 SPY 交易日 `t-1` 的信息。每个发行人先只保留一支股票，再动态选取市值前 500 个发行人。
- Alphabet 明确固定使用 `GOOG`；其他多类别发行人使用截至 `t-1` 的 60 个市场交易日平均成交额选择股票类别。
- 股票和 SPY 的策略收益均由 Yahoo `Close` 计算：历史价格已按拆股统一尺度，但不包含股息。复权价、股息和总收益仍作为核对字段保留。
- 历史市值使用根据拆股事件重建的当时实际成交价；若历史股数报告尚未反映已经发生的拆股，计算时会同步调整股数。
- 历史股数缺失时不使用未来或当前股数向过去回填，该股票在有股数观测前不会进入排名。
- 当前 Yahoo Screener 无法完整发现已经退市或不再可发现的历史证券。因此，逐日排名避免了未上市股票向过去进入股票池，但不能彻底消除 survivorship bias；严格复刻需要 CRSP/WRDS 一类历史证券主表。
- FF12 字段保留为空；本阶段不计算 beta、残差、聚类或交易信号。

## 安装

在 PowerShell 中执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .
```

## 在程序中下载完整数据（推荐）

在 PyCharm、VS Code 或其他 Python IDE 中打开 `scripts/run_data_download.py`，然后点击 Run。

需要调整的参数都集中在文件顶部：

- `START_DATE`：数据起始日；
- `END_DATE`：`None` 表示运行日前一天；
- `TOP_N`：默认 500；
- `CANDIDATE_POOL_SIZE`：可选的当前发行人市值预筛选数量；默认 `None`，表示保留全部当前可发现普通股发行人；
- `REPLACE_EXISTING_DATABASE`：默认禁止覆盖已有数据库。

程序默认生成 `data/yahoo_market_data.duckdb`。

## 在程序中查看数据（推荐）

数据库生成后，在 IDE 中直接运行 `scripts/view_data.py`。它会以只读方式启动 DuckDB 官方本地 UI，并在浏览器中打开数据库。查看结束后，请回到运行它的终端按 Enter，停止 UI 并释放数据库文件。

首次使用 DuckDB UI 需要联网安装官方 `ui` 扩展。数据库只保留三个业务 schema：

- `browse.daily_universe`：逐日的动态前 500 发行人、主要股票选择依据及当日行情；`strategy_return` 为不含股息的价格收益；
- `browse.latest_universe`：最新交易日股票池；
- `browse.daily_quality`：每日入选数量和缺失情况；
- `market_data`：证券、价格、历史股数、SPY 收益、市值和股票池等持久化数据；
- `audit`：运行记录、参数、字段说明和下载问题；运行第二阶段后也记录预处理运行。
- `preprocessing`：运行第二阶段后新增，保存逐日 beta、市场残差收益和按需生成的相关矩阵快照。

数据下载完成时仍只有 `market_data/audit/browse` 三个 schema；首次运行预处理后增加
`preprocessing`。`browse` 只保留隐藏了多表关联或质量计算的视图；原表不再以转发视图重复出现。

## 命令行方式（可选）

```powershell
.\.venv\Scripts\python.exe -m stat_arb_data download
```

默认生成 `data/yahoo_market_data.duckdb`。若文件已经存在，程序会拒绝覆盖；确认需要重建时显式增加 `--replace`。

下载会先在同一目录构建临时数据库，只有完整流程成功后才发布为正式数据库。即使显式使用
`--replace`，下载失败或正式数据库仍被 DuckDB 占用时，已有数据库也会保留。

默认完整下载需要对全部当前可发现普通股分别请求历史股数，可能耗时较长，也可能触发 Yahoo 限流。可以先做小规模验证：

```powershell
.\.venv\Scripts\python.exe -m stat_arb_data download --candidate-pool-size 20 --top-n 10 --database data/smoke_test.duckdb
```

### 从命令行打开数据库

完整数据库生成后，双击 `scripts/open_database.cmd`。它会以只读方式启动 DuckDB 官方本地 UI，并在浏览器中打开数据库。也可以执行：

```powershell
.\.venv\Scripts\python.exe -m stat_arb_data open
```

终端快速检查：

```powershell
.\.venv\Scripts\python.exe -m stat_arb_data inspect
```

### 升级已有数据库的 catalog

早期版本生成的 `meta/raw/core/quality/browse` 五 schema 数据库可以原地升级，无需重新下载：

```powershell
.\.venv\Scripts\python.exe -m stat_arb_data upgrade-catalog
```

升级前先在启动 DuckDB UI 的终端按 Enter 或 `Ctrl+C`，确保数据库已经释放。升级过程先复制到
同目录临时库，核对关键表行数后才替换原文件；失败时保留旧数据库。

## 测试

测试不调用 Yahoo 网络接口：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## 第二阶段：beta、市场残差收益和相关矩阵

本阶段使用已经确认的 Yahoo Price-Return Baseline，不改用总收益：股票输入为
`market_data.daily_prices.price_return`，市场输入为
`market_data.market_returns.market_return`。

对每只历史上至少进入过一次股票池的股票，在每个 SPY 交易日 `t` 使用包含当日的连续
60 个市场交易日计算：

```text
beta(i,t) = Cov(R(i), R(mkt)) / Var(R(mkt))
residual(i,t) = R(i,t) - beta(i,t) * R(mkt,t)
```

窗口必须有 60 个完整的股票/市场收益观测；不填零、不前向填充。结果写入
`preprocessing.daily_market_residuals`，包含窗口边界、观测数和无效原因。

### 构建逐日 beta 和残差

```powershell
.\.venv\Scripts\python.exe -m stat_arb_preprocessing build `
  --database data\yahoo_market_data.duckdb
```

也可以在 IDE 中运行 `scripts/run_preprocessing.py`。构建在同一 DuckDB 事务中发布；失败时保留
上一次完整结果。成功重建会清空旧的相关矩阵缓存。

新版预处理首次打开旧数据库时会保留逐日残差和运行记录，将 `beta_60d` 字段迁移为与窗口无关的
`beta`，并清空后续可以重建的旧结构快照缓存。请求快照时，beta 窗口、对齐方式、缺失值规则、
计算版本、方差阈值和收益口径必须与当前逐日残差运行一致，否则程序会要求先重新构建预处理数据。

### 导出指定日期快照

```powershell
.\.venv\Scripts\python.exe -m stat_arb_preprocessing export `
  --database data\yahoo_market_data.duckdb `
  --as-of-date 2026-07-17 `
  --output outputs\preprocessing\preprocessing_snapshot_2026-07-17.xlsx
```

`as-of-date=T` 表示在 `T` 日交易前构造快照：股票池使用 `eligible_date=T`，beta、残差矩阵和
相关矩阵只使用 `T` 之前 5 个 SPY 交易日。窗口不完整或五日残差方差为零的股票被整列剔除，
原因写入 `snapshot_exclusions` 和 Excel 的 `Excluded_Stocks`。

DuckDB 按需缓存：

- `correlation_snapshots`：快照参数和质量指标；
- `snapshot_residuals`：实际使用的 5 日 beta、收益和残差；
- `snapshot_correlations`：相关矩阵上三角；
- `snapshot_exclusions`：未进入矩阵的股票及原因。

缓存只有在日期、预处理运行和全部计算参数一致时才复用；同一日期改用新的相关窗口时，新快照会在
单个事务中替换旧快照，数据库不同时保留同一日期的多套参数版本。

Excel 包含 `Summary`、`Beta_Used`、`Stock_Returns`、`Residual_Matrix`、
`Correlation_Matrix` 和 `Excluded_Stocks`。摘要页集中展示参数、质量指标和总体 QC；
其余工作表保留构造相关矩阵所需的输入及中间结果，不再并排展示重复的 Excel 复核列。
输出文件已存在时默认拒绝覆盖；确认覆盖时增加 `--replace`。也可以在 IDE 中修改并运行
`scripts/export_preprocessing_snapshot.py`。

## 第三阶段：累计方差解释率确定 K

本阶段按照论文动态 K 的设定，使用指定日期之前 20 个交易日的市场残差收益构造独立的 Pearson
相关矩阵。这个窗口只用于确定 K；第二阶段和后续实际图聚类仍使用 5 日市场残差相关矩阵。
20 日 Pearson 相关矩阵的理论秩最多为 19，与论文动态方法通常选择 10–20 个 clusters 的结果
范围一致。

对相关矩阵的特征值从大到小排序，默认取累计解释 90% 总方差所需的最少特征值数量：

```text
K = min { k : sum(lambda[1:k]) / sum(lambda[1:N]) >= P }
```

阈值 `P` 默认是 `0.90`，可以在 `(0, 1]` 范围内调整。计算使用指定日期的内存快照，不保存
相关矩阵、特征值或 K，也不新增 DuckDB 结果表。

### 导出指定日期的 K 计算过程

```powershell
.\.venv\Scripts\python.exe -m stat_arb_cluster_count export `
  --database data\yahoo_market_data.duckdb `
  --as-of-date 2026-07-17 `
  --cluster-count-estimation-window 20 `
  --variance-threshold 0.90 `
  --output outputs\cluster_count\cluster_count_2026-07-17.xlsx
```

`--cluster-count-estimation-window` 默认是论文基线的 `20`，可以显式传入其他值用于核对；它不会修改预处理
或实际图聚类使用的 5 日默认窗口。

Excel 只包含 `Summary` 和 `Eigenvalues`。摘要页记录窗口、阈值、最终 K 和总体 QC；
特征值表同时列出原始值、实际使用值、累计解释率以及是否计入 K，不再把参数和 496 行累计过程
混排在同一张工作表。输出文件已存在时默认拒绝覆盖，确认覆盖时增加 `--replace`。也可以在
IDE 中修改并运行 `scripts/export_cluster_count.py`。

## 第四阶段：SPONGE_sym 股票聚类

本阶段对同一个 `as-of-date=T` 使用两套相互独立的历史窗口：

- 前 20 个交易日的市场残差相关矩阵只用于第三阶段的 90% 累计方差规则并确定 K；
- 前 5 个交易日的市场残差相关矩阵作为 SPONGE_sym 的 signed adjacency matrix。

两个窗口都严格截止到 `T` 之前的最后一个交易日。股票必须满足各自窗口的完整数据规则，因此用于
确定 K 和用于实际聚类的股票数量可以不同；K 是从 20 日窗口得到的标量，随后应用到 5 日股票集合。

### 当前暂用的作者代码兼容口径

主论文第 2.1.3 节写明应取 K 个最小广义特征向量，并直接在 K 维空间执行 k-means++。作者示例
notebook 调用的旧版 SigNet 实际默认取 K-1 个特征向量，并在聚类前执行 `v / lambda`。这会改变
embedding 中的距离，因此两种口径可能产生不同 clusters。

本阶段根据已确认的临时决定使用 notebook/SigNet 口径，计算版本为
`sponge_sym_signet_compat_v1`：

```text
eigenvector_count = K - 1
embedding[:, j] = generalized_eigenvector[:, j] / eigenvalue[j]
```

该结果不是论文文字所描述的 K 维原始特征向量基线。未来切换到论文口径时必须使用新的计算版本，
并将两种结果作为不同实验进行比较，不能静默替换或混合。

作者 notebook 没有固定 LOBPCG 或 KMeans 的随机状态，也没有显式传入 `n_init`。为满足本项目的
可复现要求，当前显式使用 `seed=0`、`n_init=10`；两者都会写入程序结果和 Excel。显式指定
`n_init` 也避免 scikit-learn 从 1.4 起将默认值改为 `"auto"` 后产生版本漂移。

### 导出指定日期的聚类结果

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
  --output outputs\clustering\sponge_sym_clusters_2026-07-17.xlsx
```

也可以在 IDE 中修改并运行 `scripts/export_clustering.py`。默认的
`tau-positive=1` 和 `tau-negative=1` 来自作者 notebook；前者是广义特征问题分母的正则项
\(\tau^+\)，后者是分子的正则项 \(\tau^-\)。

Excel 包含 `Summary`、`Eigenvalues`、`Spectral_Embedding` 和
`Cluster_Assignments`。摘要页保留配置、诊断指标、方法口径、版本和总体 QC，不再重复程序值、
Excel 重算值与差异列。cluster ID 与作者代码一致使用从 0 开始的标签；标签数字本身没有跨日期
的经济含义。输出文件已存在时默认拒绝覆盖，确认覆盖时增加 `--replace`。计算在内存中完成，
不新增 clustering 或 cluster-count DuckDB 结果表。

## 第五阶段：识别 previous winners 与 previous losers

本阶段严格实现论文第 2.2.3 节。对每个 cluster 和决策日 `T` 之前的 `w=5`
个交易日，使用原始股票价格收益计算逐日 cluster 横截面平均收益，再累计每只股票
相对该均值的偏离：

```text
deviation(i) = sum[t=T-w..T-1] (raw_return(i,t) - cluster_mean(t))
winner: deviation(i) > p
loser:  deviation(i) < -p
neutral: -p <= deviation(i) <= p
```

论文基线阈值为 `p=0`。图片和 Markdown 笔记中的 loser 公式误写为 `> p`；
实现按主论文原文使用 `< -p`。本阶段只做分类，不分配多空权重。

```powershell
.\.venv\Scripts\python.exe -m stat_arb_stock_selection export `
  --database data\yahoo_market_data.duckdb `
  --as-of-date 2026-07-17 `
  --lookback-window 5 `
  --deviation-threshold 0 `
  --output outputs\stock_selection\stock_signals_2026-07-17.xlsx
```

也可以在 IDE 中修改并运行 `scripts/export_stock_selection.py`。Excel 包含
`Summary`、`Raw_Returns`、`Cluster_Mean_Returns`、`Daily_Deviations` 和
`Trade_Signals`。均值、偏差和信号表只保留各自的关键研究字段，完整计算校验由 Python
质量检查和自动化测试负责。输出文件已存在时默认拒绝覆盖；确认覆盖时增加 `--replace`。
本阶段不向 DuckDB 新增 stock-selection、clustering 或 cluster-count 结果表。

## 第六阶段：分配多空权重

本阶段实现论文第 2.2.4 节的单个决策日权重分配，但不实现跨日持仓、
`l=3` 再平衡、`q=5%` 止盈或回测。它直接消费第五阶段的分类结果，不重复计算
previous winners 和 previous losers。

在每个同时包含 winner 和 loser 的有效 cluster 内，两侧分别等权：

```text
previous loser local weight = +1 / loser count
previous winner local weight = -1 / winner count
neutral local weight = 0
```

因此每个有效 cluster 的局部多头、空头、净敞口和总敞口分别为 `+1`、`-1`、`0`
和 `2`。论文中“所有股票权重相同”的字面表述与其示例冲突；实现采用示例所明确
表达的“多空两侧分别等权”。

全组合使用总敞口为 `1` 的口径，并将每个 cluster 分配为总敞口的 `1/K`：

```text
portfolio weight = local weight / (2 * K)
```

若所有 clusters 都有效，全组合多头为 `+0.5`、空头为 `-0.5`、净敞口为 `0`、
总敞口为 `1`。只有一侧信号、单股票或全中性的 cluster 被标记为 inactive，权重
全部置零；其 `1/K` 额度保留为未投资资金，不重新分配给其他 clusters。

```powershell
.\.venv\Scripts\python.exe -m stat_arb_portfolio_weights export `
  --database data\yahoo_market_data.duckdb `
  --as-of-date 2026-07-17 `
  --lookback-window 5 `
  --deviation-threshold 0 `
  --output outputs\portfolio_weights\portfolio_weights_2026-07-17.xlsx
```

也可以在 IDE 中修改并运行 `scripts/export_portfolio_weights.py`。Excel 包含
`Summary`、`Cluster_Allocations` 和 `Stock_Weights`：摘要页集中展示参数、敞口和
总体 QC；其余两页只保留 cluster 分配与逐股权重的关键结果。计算正确性由 Python
质量检查和自动化测试负责，报告中不再并排重复程序值、Excel 重算值和差异列。
输出文件已存在时默认拒绝覆盖；确认覆盖时增加 `--replace`。本阶段不向 DuckDB
新增任何结果表。

未来回测阶段中，`q=5%` 将针对所有 clusters 汇总后的总敞口归一化组合收益判断；
止盈在当日收盘后确认，新组合从下一交易日起生效，以避免使用日频收盘数据产生
look-ahead bias。
