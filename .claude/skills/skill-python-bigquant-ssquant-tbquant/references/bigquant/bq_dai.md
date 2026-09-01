# 数据平台_DAI

> 来源：https://bigquant.com/wiki/doc/PLSbc1SbZX（本地 HTML 快照转换；远程为最新版本，如需更新访问链接）

数据平台/DAI


### 什么是DAI
DAI (Data for AI) 是BigQuant研发的高性能分布式数据平台

- 使用简单：通过统一接口访问BigQuant各类数据
- 数据丰富：提供PB级金融数据、另类投资数据和因子数据 ([数据字典](https://bigquant.com/data/home?target=true))，并支持[用户自定义数据](https://bigquant.com/data/categories/my-data?target=true)
- 技术先进：采用现代化的分布式架构，支持大规模数据的低延迟读写和高性能计算

### DAI 快速入门
#### 导入dai
DAI已经预装在BigQuant的[AIStudio](https://bigquant.com/aistudio?target=true)策略开发IDE中，无需额外安装。

```
import dai
```

#### 读取数据
分区表默认不能全表扫描，需要对表的字段（如instrument，date）做过滤；如需读取全表数据，则需设置full_db_scan参数为True。

```
import dai

dai.query("SELECT * FROM cn_stock_instruments WHERE date = '2020-06-04'")
```

#### 指定股票代码
如下是一个是用DAI读取平台数据的示例：

从中国A股市场（cn_stock_bar1d）数据集中筛选出2020年1月1日至2021年1月1日期间，每支股票的“开盘价除以收盘价”和“交易量”数据：

```
import dai
df = dai.query("SELECT date, open/close, volume FROM cn_stock_bar1d WHERE date BETWEEN '2020-01-01' AND '2021-01-01' ").df()
df
```

其中

- `dai.query` 是DAI读取平台数据的接口，可以对[平台所有数据](https://bigquant.com/data/home?target=true)做读取和计算
- `SELECT date, open, close, volume FROM cn_stock_bar1d WHERE date BETWEEN '2023-01-01' AND '2023-05-01' AND instrument = '000001.SZ'` 是 SQL 数据访问语言，SQL是使用简单也是使用最广泛的数据操作语言，DAI会解析SQL并调用C++执行引擎，充分利用现代 CPU/GPU 特性实现高性能计算`SELECT` 读取/选择数据`date, open/close, volume` 需要的数据列`date` 日期，`open/close` 表示计算开盘价除以收盘价，通过表达式和SQL算子可以实现对数据的衍生计算，支持使用python函数自定义算子`volume` 交易量`FROM` 用于指定应从哪个表格或者多个表读取数据`cn_stock_bar1d` 是 [后复权日行情数据](https://bigquant.com/data/datasources/cn_stock_bar1d?target=true) 表名`WHERE date BETWEEN '2023-01-01' AND '2023-05-01' AND instrument = '000001.SZ'` 按条件过滤数据，`WHERE`之后是条件`date BETWEEN '2023-01-01' AND '2023-05-01'` 日期在 `2023-01-01` 和 `2023-05-01` 间`AND` 并且`instrument = '000001.SZ'` 股票代码为 `000001.SZ``.SZ` 是深交所的股票代码后缀，`.SH` 为上交所，平台所有数据定义保持一致
- `.df()` 将返回数据转为 pandas DataFrame

#### 计算因子
从中国A股市场（cn_stock_bar1d）数据集中筛选出2020年1月1日至2021年1月1日的数据，用每支股票的开盘价除以收盘价作为股票日收益率：

```
import dai
df = dai.query("SELECT date, open/close AS daily_returns FROM cn_stock_bar1d WHERE date BETWEEN '2023-01-01' AND '2023-05-01' ").df()
df
```

#### DAI核心概念
##### SQL
DAI提供多种数据格式的访问和计算支持，包括SQL、DataFrame、Arrow等。

其中SQL：

- 全兼容和支持SQL标准
- 性能优化，支持CPU和GPU
- 专为量化因子和指标计算开发和优化的函数
- 双计算引擎BigDB：DAI的高性能向量化计算引擎，主要用于大规模数据计算场景BigStream：DAI的低延迟实时数据流计算引擎，有高度的并行性和快速的数据处理能力。可用于高频因子实时计算交易、高频交易、市场实时监控等
- QuantChat 辅助生成查询和计算SQL，通过自然语言就可以实现因子构建

##### DataSource
DataSource是DAI组织数据的基本单元，类似于数据库中的table。

DataSource使用列式存储、支持数据分区和索引。基于高性能的数据表示，可以实现TB/s的数据从磁盘到内存高吞吐。

##### View
View是一种特殊的数据表，类似于数据库中的view。

View可以用于联合多个DataSource创建新的数据表，比如BigQuant平台的因子表，其实是一个view，底层由成百上千个不同的DataSource联合组成。通过专门的性能优化，View已能实现高性能的JOIN和裁剪，也能支持无限层次嵌套。

#### 数据字典和文档
##### 数据字典
BigQuant平台数据字典入口：[BigQuant数据字典和文档](https://bigquant.com/data?target=true)

##### 数据表规范
**数据表名**

BigQuant表命名由小写字母、数据和下划线构成，并且只能以字母开始，一般使用复数形式。

表名主要由如下几部分构成，i.e. cn_stock_indexes：

- 国家、地区或者市场的代码，常用代码如下（更多见术语部分）：cn：中国/A股us：美国/美股hk：中国香港地区/港股uk：英国/英国股票jp：日本/日本股票de：德国/德国股票fr：法国/法国股票sg：新加坡/新加坡股票binance：币安交易所okex：OKEX交易所
- 交易标的，常见如下（更多见术语部分）stock：股票bond：债券cbond：可转债future：期货option：期权fund：基金forex：外汇crypto：数字货币
- 数据类别：命名的第三部分表示数据类别，多个单词见用下划线(_)连接，示例如下 （更多见术语部分）：bar1d：日线行情数据bar1m：分钟行情数据income_sheet：利润表financial_pit_ttm：滚动十二期的PIT财务数据dividend：分红信息basic_info：基础信息index_bar1d：指数日线行情数据index_weights：指数权重industry_components：行业成分

**通用字段**

以下为数据表通用字段，它们在大部分表中都有一致的定义：

- date日期和时间类型：datetime
- instrument股票代码类型：字符串 (categorical)

##### 术语
| 术语 | 说明 | 示例 |
|---|---|---|
| bar | 行情数据 | cn_stock_bar1d |
| changes | 变更记录 | cn_stock_index_changes |
| cn | 中国A股市场 | cn_stock_bar1d |
| financial | 财务相关 | cn_stock_financial_pit_ttm |
| index | 指数相关 | cn_stock_index_bar1d |
| industry | 行业分类相关 | cn_stock_industry_members |
| component | 成分 | cn_stock_industry_component |
| weights | 权重 | cn_stock_index_weights |

#### 数据研究和探索
#### 数据标注
#### 可视化数据模块
### SQL入门教程
SQL，全称为结构化查询语言(Structured Query Language)，是用于管理关系数据库的标准语言。它可以用来查询、更新和操作数据库。SQL对于数据分析师和数据科学家来说是一项重要的技能，因为它让你能够从大型数据库中提取、过滤和分析数据。

本教程将指导你了解SQL的基础知识。我们将假设你已经有了Python和pandas的基础知识。

#### SQL基础
##### #`%%sql`

在aistudio的notebook单元格中键入`%%sql`便能够使用sql通过dai查询数据，如下：

```
%%sql
from cn_stock_bar1d limit 10;
```

如果要给sql中的所有数据字典添加过滤区间，比如只查询`2023-06-01`之后的数据，可以如下操作：

```
%%sql {"date": ["2023-06-01", "2024-01-01"]}
from cn_stock_bar1d limit 10;
```

如果要将查询到的数据在python程序中继续处理，比如转成dataframe的格式，可以如下操作：

```
# import pandas as pd
# 去除行数限制/列数限制
# pd.set_option('display.max_rows', 200)
# pd.set_option('display.max_columns', 200)
result = _.df()
result
```

注：`_`是一个特殊变量，用来存储最近一个代码单元格的输出结果，也支持使用 `__`(两个下划线) 来访问倒数第二个单元格的输出，`___`(三个下划线) 来访问倒数第三个单元格的输出。

##### 数据库和表
SQL数据库是一个或多个相关的表的集合。表是行（称为记录）和列（称为字段）的二维表示。每一行通常表示一个实体（如一个人、一个产品等），每一列代表实体的一个属性（如名字、年龄等）。

##### SQL语句
SQL语句是你告诉数据库想要做什么的方式。比如，你想要从数据平台中获取后复权日行情数据表的所有记录，你可以使用SELECT语句：

```
%%sql
SELECT * FROM cn_stock_bar1d;
```

`*`代表所有列，`cn_stock_bar1d`是表的名字，是后复权日行情数据。每条SQL语句都以分号结束。

#### #查询数据

##### #SELECT语句

SELECT语句用于从数据库中选取数据。语法为：

```
SELECT column1, column2, ...
FROM table_name;
```

例如，从数据平台的`cn_stock_bar1d`表中选择`date`、`instrument`以及`close`列：

```
%%sql
SELECT date, instrument, close FROM cn_stock_bar1d;
```

##### #WHERE子句

WHERE子句用于过滤记录，即通过condition筛选我们想要的数据。语法为：

```
SELECT column1, column2, ...
FROM table_name
WHERE condition;
```

例如，从日线表格中抽取特定日期的收盘价:

```
%%sql
SELECT date, instrument, close FROM cn_stock_bar1d WHERE date = '2023-02-08';
```

##### #ORDER BY子句

ORDER BY子句用于对结果集按照一列或多列进行排序。语法为：

```
SELECT column1, column2, ...
FROM table_name
ORDER BY column1 [ASC|DESC], column2 [ASC|DESC], ...;
```

例如，从日线表中选择特定日期, 并查看换手率最高的三只股票:

```
%%sql
set full_db_scan=true;
SELECT instrument, name, turn FROM cn_stock_bar1d WHERE date = '2023-02-08' ORDER BY turn DESC LIMIT 3;
```

注：全表扫描时（一般是没有对date字段做过滤），需要在查询前执行set full_db_scan=true;以设置支持全表扫描。

#### #聚合函数和分组

SQL也支持对数据进行聚合和分组，比如计算平均值、总和等。

##### #聚合函数

SQL提供了一些内置的聚合函数，如COUNT()、SUM()、AVG()、MAX()、MIN()、LAG()还有统计学中的相关系数函数CORR()等。

例如，我们来求`000001.SZ`股票在指定一段日期内成交量和收盘价的相关系数：

```
%%sql
SELECT CORR(volume, close) as corr_vol_close
FROM cn_stock_bar1d
WHERE date between '2023-02-08' and '2023-02-10'
and instrument = '000001.SZ';
```

##### #GROUP BY子句

GROUP BY子句用于将结果集按照一列或多列进行分组。语法为：

```
SELECT column1, function(column2)
FROM table_name
GROUP BY column1;
```

例如, 求得每日截面上股票平均价格水平:

```
%%sql
SELECT date, AVG(close) FROM cn_stock_bar1d GROUP BY date;
```

再如，按股票分组求每只股票下的成交量和收盘价的相关系数：

```
%%sql
SELECT instrument, CORR(volume, close) corr_vol_close FROM cn_stock_bar1d GROUP BY instrument;
```

#### #窗口函数

窗口函数在SQL中提供了一种处理数据的强大方法，它可以在一行的上下文中对一组行进行计算。窗口由输入行的集合组成，它是根据窗口函数的使用情况定义的。

窗口函数的基本语法如下：

```
<窗口函数> (<列名>) OVER ([PARTITION BY <列名>]
                           [ORDER BY <列名>]
                           [ROWS BETWEEN <开始行> AND <结束行>])
```

##### #PARTITION BY子句

PARTITION BY子句将输入行划分为若干个组或分区。窗口函数将独立于每个分区进行计算。

例如，计算每只股票五日区间收益率:

```
%%sql
SELECT date, instrument, 
close / LAG(close, 5) OVER (PARTITION BY instrument ORDER BY date) as return_5
FROM cn_stock_bar1d
WHERE date > '2023-01-01';
```

剖析: 将数据按照变量`instrument`进行分组`PARTITION BY instrument`，有多少只股票就会拆分出多少组，并且对拆分出来的组按照日期进行排序`ORDER BY date`，进而在每组中计算五日区间收益率`close / LAG(close, 5)`，最后将所有组拼接成大表，和没被拆分的表格一样，区别在于多了一列`return_5`。

##### #ORDER BY子句

ORDER BY子句定义了窗口内的行排序。这对于像RANK()这样的窗口函数尤其有用，它会根据排序顺序对行进行排名。

例如，按照`date`形成一个截面数据的换手率排行：

```
%%sql
SELECT date, instrument, 
RANK() OVER (PARTITION BY date ORDER BY turn DESC) as rank_turn
FROM cn_stock_bar1d
WHERE date > '2023-01-01';
```

剖析: 首先按照日期进行分区，每张表都是特定时期下的截面数据，进一步按照股票的换手率进行降序排序，并给每张表格添加一列`rank_turn`，最后将所有截面数据拼接成总表。

##### #ROWS子句

ROWS子句定义了窗口的物理限制，即窗口函数计算的行的范围。它可以定义为在当前行之前和之后的一定数量的行，或者是从分区的起始到当前行，以及从当前行到分区的结束。

ROWS子句的语法如下：

- `ROWS UNBOUNDED PRECEDING`：从分区的第一行到当前行。
- `ROWS N PRECEDING`：从当前行的前N行到当前行。
- `ROWS CURRENT ROW`：只有当前行。
- `ROWS N FOLLOWING`：从当前行到后N行。
- `ROWS UNBOUNDED FOLLOWING`：从当前行到分区的最后一行。
- `ROWS BETWEEN A AND B`：定义一个从A到B的范围，其中A和B可以是上述任何选项。

例如，计算每支股票的5日移动平均线以及对应的收盘价:

```
%%sql
SELECT date, instrument, close, 
(AVG(close) OVER (PARTITION BY instrument ORDER BY date ROWS BETWEEN 4 PRECEDING AND CURRENT ROW)) ma5
FROM cn_stock_bar1d 
WHERE date > '2023-01-01';
```

剖析: 首先按照股票代码进行分区，每个分区都保存了单只股票的时间序列数据，再对每个分区按照date排序， 取前4期的数据到当期数据的一个平均值。

注意: 聚合函数和窗口同时出现时，聚合函数和窗口共同形成一个字段`AVG(close) OVER (PARTITION BY instrument ORDER BY date ROWS BETWEEN 4 PRECEDING AND CURRENT ROW)`该字段如果是浮点数, 依旧可以进行加减乘除运算。

#### #dai的SQL扩展功能

dai提供了许多非常方便的SQL扩展功能。这些功能可以极大地简化SQL查询的编写，提高查询的效率和灵活性。

##### #USING

传统的联表查询使用JOIN ON的方式是比较繁琐的，dai对于JOIN列相等的情况可以使用USING的语法简化，老的方式：

```
%%sql
SELECT *
FROM cn_stock_bar1d a
JOIN cn_stock_valuation b
ON a.instrument = b.instrument and a.date = b.date
WHERE a.date > '2023-01-01';
```

新的方式：

```
%%sql
SELECT *
FROM cn_stock_bar1d
JOIN cn_stock_valuation USING (instrument, date)
WHERE date > '2023-01-01';
```

##### #`EXCLUDE/REPLACE`

- `EXCLUDE`

在传统的SQL查询中，我们需要明确指定所请求的列。`SELECT *`可以让SQL返回所有相关的列，这在构建查询的时候非常灵活。但是相对该表全部字段数量来说，我们需要取得字段数量巨大，这时将字段逐个输入就显得浪费时间，所以我们只需要在总表的基础上排除个别字段即可。在dai中，我们只需要指定要排除的列就可以了。

例如, 在上述例子中，我不想取出收盘价数据：

```
%%sql
WITH t AS (
    SELECT date, instrument, close, 
    (AVG(close) OVER (PARTITION BY instrument ORDER BY date ROWS BETWEEN 4 PRECEDING AND CURRENT ROW)) ma5
    FROM cn_stock_bar1d 
    WHERE date > '2023-01-01'
)

SELECT * EXCLUDE (close) FROM t;
```

这里有一个`WITH`语句，其目的是将取出的表赋值给一个中间变量`t`，最后取出表中除去收盘价的所有数据。

- `REPLACE`

有时，我们希望使用表中的所有列，除了几个需要做一些小调整的列。在dai中，我们可以使用`REPLACE`轻松地对少数列进行更改。

例如, 求出当天股票交易的总价值(粗略计算，价格乘以当天交易量)，并将其替换`close`字段的值：

```
%%sql
WITH t AS (
    SELECT date, instrument, close, volume
    FROM cn_stock_bar1d
    WHERE date > '2023-01-01'
)

SELECT * REPLACE (close * volume AS close) FROM t;
```

##### #`GROUP/ORDER BY ALL`

- `GROUP BY ALL`在SQL中，我们经常需要在`SELECT`子句和`GROUP BY`子句中指定列。理论上这增加了SQL的灵活性，但实际上很少有价值。dai现在提供`GROUP BY ALL` ：即`GROUP BY`所有在`SELECT`子句中没有被聚合函数包裹的列。例如：`%%sql WITH t AS ( SELECT date, instrument, close, volume FROM cn_stock_bar1d WHERE date > '2023-01-01' ) SELECT date, instrument, AVG(close) FROM t GROUP BY ALL`上述`GROUP BY ALL`语句等价于`GROUP BY date, instrument`。
- `ORDER BY ALL``%%sql SELECT date, instrument, close FROM cn_stock_bar1d WHERE date > '2023-01-01' ORDER BY ALL`这里的`ORDER BY ALL`等价于`ORDER BY date, instrument, close`。这在构建汇总时特别有用，因为许多其他客户端工具会自动按照这种方式对结果进行排序。dai还支持`ORDER BY ALL DESC`以逆序排序每一列，以及指定`NULLS FIRST`或`NULLS LAST`的选项。

##### 在** `WHERE / GROUP BY / HAVING`中使用**列别名
在许多SQL方言中，除了在那个语句的`ORDER BY`子句中，无法在其他地方使用在`SELECT`子句中定义的别名。在dai中，`SELECT`子句中的非聚合别名可以立即在`WHERE`和`GROUP BY`子句中使用，聚合别名可以在`HAVING`子句中使用，即使在同一查询深度也不需要子查询。

例如, 以单个标的`000001.SZ`为例, 找出价格上穿布林带上限（20日均线加上一倍标准差）的时点：

```
%%sql
WITH t AS (
    /*计算布林带上轨*/
    SELECT date, instrument, close, 
    (AVG(close) OVER (ORDER BY date ROWS 19 PRECEDING)) + (STDDEV(close) OVER (ORDER BY date ROWS 19 PRECEDING)) up_line
    FROM cn_stock_bar1d 
    WHERE date > '2023-01-01' AND instrument = '000001.SZ'
)

/*筛选突破布林带上轨的时点, 卖出资产的时点*/
SELECT date, close - up_line delta FROM t WHERE delta > 0;
```

这里为收盘价和布林带上轨的差值取了别名`delta`。`delta > 0`代表收盘价突破了布林带上轨，进一步在`where`子句中过滤取出`delta > 0`的时点。

再如，筛选出2023年以来平均换手率低于0.3的股票：

```
%%sql
SELECT instrument, AVG(turn) avg_turn 
FROM cn_stock_bar1d
WHERE date > '2023-01-01'
GROUP BY instrument
HAVING avg_turn < 0.3;
```

这里给平均换手率指标取了别名`avg_turn`，`HAVING`子句中用别名做了判断。

##### 字符串切片
在dai中，你可以使用方括号语法切片字符串，而不是使用笨重的`SUBSTRING`函数。

例如：

```
%%sql
SELECT 'bigquant'[:-3];
```

##### 简单的列表和结构创建
dai提供了嵌套类型，以允许比纯关系模型更灵活的数据结构，同时保持高性能。为了尽可能容易使用它们，创建一个`LIST`（数组）或一个`STRUCT`（对象）使用比其他SQL系统更简单的语法。数据类型会自动推断。

例如：

```
%%sql
SELECT
    ['1', '2', '3', '4'] as num_list,
    {corp: 'bigquant', vision: 'Democratize AI to empower investors'} as bigquant
```

##### 列表切片
方括号语法也可以用来切片一个`LIST`。同样，注意这里是从1开始索引的，以保持SQL的兼容性。

例如：

```
%%sql
SELECT 
    num_list[2:2] as one_number
FROM (SELECT ['1', '2', '3', '4'] as num_list);
```

##### 结构点符号
使用方便的点符号来访问dai `STRUCT`列中特定键的值。如果键包含空格，可以使用双引号。

例如：

```
%%sql
SELECT 
    bigquant.corp,
    bigquant."corp vision" 
FROM (SELECT {corp: 'bigquant', 'corp vision': 'Democratize AI to empower investors'} as bigquant)
```

##### 尾随逗号
`SELECT`语句中如果最后存在逗号的话，一般来讲会报错, 而`dai`会忽略掉这种错误。

例如：

```
%%sql
SELECT date, instrument,
FROM cn_stock_bar1d
WHERE date > '2023-01-01'
GROUP BY date, instrument,
```

##### 自动增量重复列名
当你构建一个连接相似表的查询时，你会经常遇到重复的列名。如果查询是最后的结果，`dai`将简单地返回重复的列名，而不进行修改。然而，如果查询用于创建表，或者嵌在子查询或公共表表达式（CTE）中（在其他数据库中，重复的列是被禁止的！），`dai`将自动为重复的列分配新的名称，以便更容易地制定查询。

例如, 我想提取表`cn_stock_limit_price`和表`cn_stock_bar1d`中的日期：

```
%%sql
SELECT a.date, b.date FROM cn_stock_bar1d a
JOIN cn_stock_limit_price b
ON a.date = b.date AND a.instrument = b.instrument
WHERE b.date > '2023-01-01';
```

##### 可重复使用的列别名
在 `select` 语句中使用增量计算表达式时，传统的SQL方言要求您为每个列编写完整的表达式，或者围绕计算的每一步创建一个公共表表达式（CTE）。现在，任何列别名都可以在同一 `select` 语句中的后续列中重复使用。不仅如此，这些别名还可以在 `where` 和 `order by` 子句中使用。

旧方式1：重复自己

```
%%sql
SELECT
    date,
    instrument,
    AVG(amount) OVER (PARTITION BY instrument ORDER BY date ROWS 4 PRECEDING) AS avg_amount_5,
    AVG(amount) OVER (PARTITION BY instrument ORDER BY date ROWS 19 PRECEDING) AS avg_amount_20,
    AVG(amount) OVER (PARTITION BY instrument ORDER BY date ROWS 4 PRECEDING)
    / AVG(amount) OVER (PARTITION BY instrument ORDER BY date ROWS 19 PRECEDING) AS 'avg_amount_5/avg_amount_20',
FROM cn_stock_bar1d
WHERE date > '2023-01-01'
ORDER BY instrument, date
```

旧方式2：使用CTEs

```
%%sql
WITH t AS
(SELECT
    date,
    instrument,
    AVG(amount) OVER (PARTITION BY instrument ORDER BY date ROWS 4 PRECEDING) AS avg_amount_5,
    AVG(amount) OVER (PARTITION BY instrument ORDER BY date ROWS 19 PRECEDING) AS avg_amount_20,
    FROM cn_stock_bar1d WHERE date > '2023-01-01')

SELECT
    date,
    instrument,
    avg_amount_5,
    avg_amount_20,
    avg_amount_5 / avg_amount_20 AS 'avg_amount_5/avg_amount_20',
FROM t
ORDER BY instrument, date
```

新方式

```
%%sql
SELECT
    date,
    instrument,
    AVG(amount) OVER (PARTITION BY instrument ORDER BY date ROWS 4 PRECEDING) AS avg_amount_5,
    AVG(amount) OVER (PARTITION BY instrument ORDER BY date ROWS 19 PRECEDING) AS avg_amount_20,
    avg_amount_5 / avg_amount_20 AS 'avg_amount_5/avg_amount_20',
FROM cn_stock_bar1d
WHERE date > '2023-01-01'
ORDER BY instrument, date
```

如果使用dai预定义的宏能够更加简化sql

```
%%sql
SELECT
    date,
    instrument,
    M_AVG(amount, 5) AS avg_amount_5,
    M_AVG(amount, 20) AS avg_amount_20,
    avg_amount_5 / avg_amount_20 AS 'avg_amount_5/avg_amount_20',
FROM cn_stock_bar1d
WHERE date > '2023-01-01'
ORDER BY instrument, date
```

如果只是把`avg_amount_5`和`avg_amount_20`作为中间变量，最后输出 `avg_amount_5/avg_amount_20` 因子，则可以在`avg_amount_5` 和 `avg_amount_20` 前添加下划线（`_`），如下：

```
%%sql
SELECT
    date,
    instrument,
    M_AVG(amount, 5) AS _avg_amount_5,
    M_AVG(amount, 20) AS _avg_amount_20,
    _avg_amount_5 / _avg_amount_20 AS 'avg_amount_5/avg_amount_20',
FROM cn_stock_bar1d
WHERE date > '2023-01-01'
ORDER BY instrument, date
```

##### FROM table SELECT
传统查询语句遵循先选特征再写表名, 这也是为什么`SELECT`在前，`FROM`在后。但构建查询时，你需要知道的第一件事就是你的数据来自哪里:

```
%%sql
FROM cn_stock_bar1d SELECT * WHERE date > '2023-01-01'
```

不仅如此， `SELECT` 语句可以完全移除，dai将假定应该选择所有的列。现在查看一张表就像这样简单：

```
%%sql
FROM cn_stock_bar1d WHERE date > '2023-01-01'
```

##### 函数链
dai为标量函数提供了函数链功能：使用点操作符将函数链接在一起，链中的先前表达式作为随后函数的第一个参数。

```
%%sql
SELECT
('Democratize AI to empower investors')
.UPPER()
.string_split(' ')
.list_aggr('string_agg','.')
.concat('.') AS cool;
```

上方函数链代码与下方代码表达的意思相同：

```
%%sql
SELECT
concat(
list_aggr(
string_split(
UPPER('Democratize AI to empower investors'),
' '),
'string_agg','.'),
'.') AS oof;
```

#### 与python/pandas对比
虽然SQL和python语言两者的应用领域和设计目标有所不同，但在某些地方，它们的语法还是存在相通之处。同时我们也给出在数据分析方面很常用的pandas的一些例子。

##### 操作符
- Python

Python使用相同的操作符进行算术和比较操作。例如，`+`、`-`、`*`、`/`用于算术运算，而`<`、`>`、`=`、`!=`用于比较运算。

```
x = 10
y = 20
print(x + y)  # 输出30
print(x > y)  # 输出False
```

- SQL

SQL也是：

```
SELECT 10 + 20;  -- 输出30
SELECT 10 > 20;  -- 输出false
```

- Pandas

Pandas也是：

```
df = pd.DataFrame({'x': [10], 'y': [20]})
print(df['x'] + df['y'])  # 输出30
print(df['x'] > df['y'])  # 输出False
```

##### 条件语句
- Python

Python 提供了条件语句，例如 `if`、`else`。

```
x = 10
if x > 5:
    print("x is greater than 5")
else:
    print("x is not greater than 5")
```

- SQL

SQL 提供了 `CASE`、`WHEN`、`THEN`、`ELSE` 条件语句。

```
%%sql
CREATE TABLE students AS (SELECT 10 as age);
SELECT 
    CASE 
        WHEN age > 5 THEN 'Age is greater than 5'
        ELSE 'Age is not greater than 5'
    END
FROM students;
```

- Pandas

Pandas 提供了 `where` 条件语句。

```
df = pd.DataFrame({'age': [10]})
df['age'].where(df['age'] > 5, 'Age is not greater than 5', 'Age is greater than 5')
```

##### 创建和使用表
- Python

Python中，我们可以创建一个新的变量并给它赋值，然后在后续的代码中引用它。

```
students = [("Alice", 20), ("Bob", 22)]
```

- SQL

在SQL中，你可以使用`CREATE TABLE`语句来定义并命名一个新的表，然后在后续的查询中引用它：

```
%%sql
CREATE TABLE students AS SELECT * FROM (VALUES ('Alice', 20), ('Bob', 22)) students(name, age);
```

- Pandas

在Pandas中，DataFrame可以视作一个表，我们可以创建一个新的DataFrame并给它赋值，然后在后续的代码中引用它。

```
import pandas as pd
df = pd.DataFrame({'name': ['Alice', 'Bob'], 'age': [20, 22]})
```

##### 使用临时表
- Python

Python中，我们可以创建一个新的变量并给它赋值，然后在后续的代码中引用它。

```
student_ages = [("Alice", 20), ("Bob", 22)]
old_students = [student for student in student_ages if student[1] > 21]
```

- SQL

在SQL中，`WITH`语句（也称为公共表表达式，或CTE）允许你定义一个临时的命名结果集，然后在后续的查询中引用它：

```
%%sql
WITH student_ages AS (
    SELECT * FROM (VALUES ('Alice', 20), ('Bob', 22)) students(name, age)
)
SELECT * FROM student_ages WHERE age > 21;
```

- Pandas

在Pandas中，我们也可以创建一个新的DataFrame并给它赋值，然后在后续的代码中引用它。

```
import pandas as pd
df = pd.DataFrame({'name': ['Alice', 'Bob'], 'age': [20, 22]})
old_students = df[df['age'] > 21]
```

##### 定义和使用函数
- Python

在Python中，我们使用 `def` 关键字定义函数：

```
def square(x):
    return x * x
```

- SQL

在SQL中，我们可以使用 `CREATE MACRO` 语句定义函数：

```
%%sql
CREATE MACRO square(x) AS x * x;
SELECT square(2);
```

- Pandas

在Pandas中，我们可以定义Python函数，然后在DataFrame上应用它：

```
import pandas as pd
def square(x):
    return x * x
df = pd.DataFrame({'x': [2]})
df['x_squared'] = df['x'].apply(square)
```

以上就是dai SQL、Python和Pandas语法在一些方面的相通之处。

### 用DAI代替Python表达式
在进行量化投资的过程中，你可能会需要对大量的交易数据进行分析，比如计算某只股票的历史收益率、波动、流动性等因子。当你使用代码编写策略时，你就需要使用 DAI 来进行数据查询和分析。本文给出了常见的可视化程序中Python表达式的DAI实现。

例如：分别用可视化编程和代码编程提取当日收盘价并求对数值。

| 可视化编程 |
|---|
|  |

| 代码编程 |
|---|
|  |

#### 替换表达
| 描述 | Python函数 | DAI函数 |
|---|---|---|
| 数据过滤函数 | where | if(close>m_lag(close,1), 1, 0) |
| 正弦函数 | sin | sin(x) |
| 余弦函数 | cos | cos(x) |
| 正切函数 | tan | tan(x) |
| 反正弦函数 | arcsin | asin(x) |
| 反余弦函数 | arccos | acos(x) |
| 反三角函数 | arctan | atan(x) |
| 反三角函数，=arctan(x/y) | arctan2(x, y) | atan2(close, open) |
| 双曲正弦 | sinh(x) | (exp(x) - exp(-x)) / 2 |
| 双曲余弦 | cosh(x) | (exp(x) + exp(-x)) / 2 |
| 双曲正切 | tanh(x) | (exp(x) - exp(-x)) / (exp(x) + exp(-x)) |
| 反双曲正弦 | arcsinh（x） | ln(x + sqrt(x * x + 1)) |
| 反双曲余弦 | arccosh（x） | ln(x + sqrt(x * x - 1)) |
| 反双曲正切 | arctanh（x） | 0.5 * ln((1 + x) / (1 - x)) |
| 自然对数 | log(x) | log(x) |
| 10为底的对数 | log10（x） | log10(x) |
| log(1+x) | log1p（x） | ln(1 + x) |
| 指数 | exp（x） | exp(x) |
| exp(x)-1 | expm1（x） | exp(x) - 1 |
| 平方根 | sqrt(x) | sqrt(x) |
| 绝对值 | abs(x) | abs(x) |
| 向上取整 | ceil(x) | ceil(x) |
| 向下取整 | floor(x) | floor(x) |
| 取 x 的符号，如果 x > 0, 为1; x == 0，为0; 否则为-1 | sign(x) | sign(close/open - 1) |
| 等价于 sign(x) * (abs(x)**a) | signedpower(x, a) | sign(close) * power(abs(close), 2) |
| 最小值 | min | min(close) |
| 求最大值 | max | max(close) |
| 判断是否为NaN | isnan(number) | if(isnan(close), 0, close) |
| 对s做裁剪，裁剪区间为[lower,upper],如果lower，则设置为lower，如果upper，则设置为upper | clip(s, lower, upper) | clip(close, 10, 20) |
| 计算s的第q个百分位数, q属于[0, 1]。则 all_quantile(s, 0)得到s的最小值，all_quantile(s, 1)对应s的最大值。注意，这里计算的是全部s数据的百分位(而不是按天或者按股票处理的) | all_quantile(s, q) | all_quantile_cont(close, 0.01) |
| 按等宽做离散化，映射从0开始。bins可以是正整数，表示bins的数量；list，表示splits | all_wbins(s, bins) | all_wbins(close, 5) |
| 按等频做离散化，映射从0开始。bins可以是正整数，表示bins的数量；list，表示每个bin里的数据比例 | all_cbins(s, bins) | all_cbins(close, 5) |
| 移动x值的函数 | shift(x, d) | m_shift(x, d) |
| 今天的x值减去d天以前的x值 | delta(x, d) | m_delta(x, d) |
| 在过去长度为d天，x和y的相关性 | correlation(x, y, d) | m_corr(close, volume, 20) |
| 在过去长度为d天，x和y的协方差 | covariance(x, y, d) | m_covar_pop(close, volume, 20) |
| 返回y与x的滚动回归所得到的result_type序列 | ols(result_type, y, x, d) | m_regr_slope(close, volume, 20) |
| 过去 d 天 x 的和 | sum(x, d) | m_sum( volume, 5) |
| 过去 d 天 x 的乘积 | product(x, d) | m_product( close/m_lag(close,1)-1, 1) |
| 过去 d 天 x 的标准差 | std(x,d) | m_stddev(close, 21) |
| 过去 d 天 x 的均值 | mean(x, d) | m_avg(close, 5) |
| 过去 d 天 x 的均值（去除NaN值） | nanmean(x, d) | m_nanavg(close, 5) |
| 过去 d 天 x 的方差（去除NaN值） | nanvar(x, d) | m_nanvar(close, 5) |
| 过去 d 天 x 的标准差（去除NaN值） | nanstd(x, d) | m_nanstd(close, 5) |
| 过去 d 天 x 的方差 | var(x, d) | m_var_pop(close, 5) |
| 过去 d 天 x 的偏度 | skew(x, d) | m_skewness(close, 20) |
| 过去 d 天 x 的峰度 | kurt(x, d) | m_kurtosis(close, 20) |
| 过去 d 天的加权平均，权重是1,…,d-1,d | decay_linear(x, d) | m_decay_linear(close, 10) |
| 时间序列函数， d 天内的最小值 | ts_min(x, d) | m_min(low, 20) |
| 时间序列函数， d 天内的最大值 | ts_max(x, d) | m_max(low, 20) |
| 时间序列函数， d 天内的最大值发生在哪一天 | ts_argmax(x, d) | 20 - m_imax(high, 20) |
| 时间序列函数， d 天内的最小值发生在哪一天 | ts_argmin(x, d) | 20 - m_imin(high, 20) |
| 时间序列函数， 当天的值在d天的内的排名百分比 | ts_rank(x, d) | m_rolling_rank(close, 20) |
| x在当天的百分比排名 | rank | pct_rank_by(date, volume) |
| 按日期分组后的数据处理函数 | scale(x, a=1) | close/sum(abs(amount)) over (PARTITION BY date ) |
| 同时按日期和key做分组，求平均 | group_mean(key, x) | avg(amount) over( PARTITION BY date, key) |
| 同时按日期和key做分组，求和 | group_sum(key, x) | sum(amount) over( PARTITION BY date, key) |
| 同时按日期和key做分组，求当前值在分组内的排名百分比 | group_rank(key, x) | percent_rank() over( PARTITION BY date,key order by amount asc) |
| timeperiod周期的简单移动平均值 | ta_sma(x, timeperiod) | m_ta_sma(close,20) |
| timeperiod周期的指数移动平均值 | ta_ema(x, timeperiod) | m_ta_ema(close,20) |
| timeperiod周期的加权移动平均值 | ta_wma(x, timeperiod) | m_ta_wma(close,20) |
| timeperiod周期的动量指标 | ta_mom(x, timeperiod) | m_ta_mom(close, 10) |
| timeperiod周期的变动率指标 | ta_roc(x, timeperiod) | m_ta_roc(close, 10) |
| timeperiod周期的相对强弱指标 | ta_rsi(x, timeperiod) | m_ta_rsi(close, 14) |
| timeperiod周期的三重指数平滑平均线 | ta_trix(x, timeperiod) | m_ta_trix(close, 15) |
| timeperiod周期的威廉指标 | ta_willr(x, timeperiod) | m_ta_willr(close, low, close,14) |
| timeperiod周期的均幅指标（=SMA 口径，**非 Wilder RMA**——实证 TR 突变期差 3~16%，吊灯/波动率类策略须 pandas Wilder 兜底） | ta_atr(high, low, close, timeperiod) | m_avg(greatest(high - low, abs(high - pre_close), abs(low - pre_close)), 14) |
| timeperiod周期的平均趋向指数 | ta_adxr(high, low, close, timeperiod) | m_ta_adxr(high, low, close,4) |
| timeperiod周期的顺势指标 | ta_cci(high, low, close, timeperiod) | m_ta_cci(high, low, close,14) |
| timeperiod周期的回归斜率 | ta_beta(x, y, timeperiod) | m_ta_beta(close, volume, 5) |
| timeperiod多空指数,空头市场 | ta_bbi(close, 'long', timeperiod_1=3, timeperiod_2=6, timeperiod_3=12, timeperiod_4=24) | (m_avg(close,3) + m_avg(close, 6) + m_avg(close,12) + m_avg(close, 24)) / 4 |

#### 使用示例
##### SQL使用示例
上述DAI示例代码为sql代码，可直接运行

```
%%sql 
select 
*
from 
cn_stock_bar1d 
where date >= '2015-01-01'
```

输出结果：

##### DAI使用示例
"%%sql" 是 Jupyter Notebook 的一种命令，用于在 Jupyter Notebook 中运行 SQL 语句。使用DAI时，需将%%sql 去掉。因此，使用DAI时，需将%%sql 去掉。

```
import dai

df = dai.query("select 
instrument,
date,
if(close>m_lag(close,1), 1, 0) as kline_color 
from 
cn_stock_bar1d 
where date >= '2015-01-01'").df()
print(df)
```

输出结果：

### 进阶 SQL
#### SQL常用语句
##### select
`SELECT`语句的主要功能是查询，从数据库中检索符合条件的行。

- **例子**

```
%%sql
/*单纯的从表cn_stock_bar1d中取出所有字段*/
SELECT * FROM cn_stock_bar1d;

/*从表cn_stock_bar1d中取出2023年9月13日的收盘价*/
SELECT close FROM cn_stock_bar1d WHERE date >= '2005-01-04';

/*统计A股换手率的截面均值*/
SELECT date, AVG(turn) FROM cn_stock_bar1d GROUP BY date;

/*筛选出2023年9月13日换手率最低的三只股票*/
SELECT instrument, turn FROM cn_stock_bar1d WHERE date = '2023-09-13' ORDER BY turn LIMIT 3;

/*将日线表和估值表按照日期和股票代码合并进而观察每只股票的市值*/
SELECT * FROM cn_stock_bar1d JOIN cn_stock_valuation USING (date, instrument) WHERE date > '2021-01-01';
```

- **语法**

`SELECT`语句的规范顺序如下（缩进了不太常见的子句）：

```
SELECT select_list
FROM tables
    USING SAMPLE sample_expr
WHERE condition
GROUP BY groups
HAVING group_filter
    WINDOW window_expr
    QUALIFY qualify_filter
ORDER BY order_expr
LIMIT n
```

`SELECT`语句可以带有`WITH`子句作为前缀。[with](https://bigquant.com/wiki/doc/dai-PLSbc1SbZX#h-with) 用于指定公用表表达式（CTE）。常规（非递归）公用表表达式本质上是仅限于特定查询的视图。CTE可以相互引用，并且可以嵌套。

**注：由于**`SELECT`**语句非常复杂，我们将其分解成几个部分放到下一节**[select语法详解](https://bigquant.com/wiki/doc/dai-PLSbc1SbZX#h-select%E8%AF%AD%E6%B3%95%E8%AF%A6%E8%A7%A3)**进行讲解。**

##### create table
`CREATE TABLE`语句的主要功能是在当下目录中创建一个表。

- **例子**

```
%%sql
/*创建一个名为bigquant_factor_1的表, 其中包含两个字段i和j, 两个字段都只能存放整数*/
CREATE TABLE bigquant_factor_1(i INTEGER, j INTEGER);

/*创建一个名为bigquant_factor_2的表, 其中包含两个字段i和j, i只能存放整数, j只能存放字符串, i表的主键, 如果插入的数据存在两个同样的i值, 则会报错*/
CREATE TABLE bigquant_factor_2(id INTEGER PRIMARY KEY, j VARCHAR);

/*创建一个名为bigquant_factor_3的表, 其中包含两个字段id和j, id只能存放整数, j能存放字符串, 将这两个字段同时设为主键*/
CREATE TABLE bigquant_factor_3(id INTEGER, j VARCHAR, PRIMARY KEY(id, j));

/*创建一个名为bigquant_factor_4的表, 其中包含四个字段, i只能存放整数, decimalnr能存放小于10的浮点数, date存放的是DATE类型的数据, time 存放的是TIMESTAMP数据, 其中DATE存放的期限比后者长*/
CREATE TABLE bigquant_factor_4(i INTEGER NOT NULL, decimalnr DOUBLE CHECK(decimalnr<10), date DATE UNIQUE, time TIMESTAMP);

/*创建一个名为bigquant_factor_5的表, 其中用SELECT语句建立了包含一个样本的表, 进一步将这个表赋给bigquant_factor_5*/
CREATE TABLE bigquant_factor_5 AS SELECT 42 AS i, 84 AS j;

/*创建一个名为bigquant_factor_6的表, 读取csv中的表并将表赋给bigquant_factor_6*/
CREATE TABLE bigquant_factor_6 AS SELECT * FROM read_csv_auto ('path/file.csv');
```

- **CREATE OR REPLACE**

`CREATE OR REPLACE` 语法允许创建新表或由新表覆盖现有表。这是删除现有表然后创建新表的简写。

```
%%sql
/*创建一个表bigquant_factor_1, 表中包含i和j两个变量, 如果之前存在bigquant_factor_1这张表, 则覆盖掉之前的表*/
CREATE OR REPLACE TABLE bigquant_factor_1(i INTEGER, j INTEGER);
```

- **IF NOT EXISTS**

仅当表尚不存在时，`IF NOT EXISTS` 语法才会继续创建表。如果该表已存在，则不会执行任何操作，现有表将保留在数据库中。

```
%%sql
/*创建表bigquant_factor_1, 如果之前没有表bigquant_factor_1, 则创建一个包含i和j两个字段的表, 并赋给bigquant_factor_1*/
CREATE TABLE IF NOT EXISTS bigquant_factor_1(i INTEGER, j INTEGER);
```

##### create macro
`CREATE MACRO`语句可以在目录中创建标量宏或表宏（函数）。

宏是一种批量处理的称谓，一种语法替换的规则或模式，用于说明某一特定输入（通常是字符串）如何根据预定义的规则转换成对应的输出（通常也是字符串)。宏可能只是单个`SELECT`语句 ，但它具有接受参数的好处。

对于标量宏，`CREATE MACRO`后面跟着宏的名称, 以及一组在括号中的可选参数。接着关键字`AS`后跟着宏具体的文本。根据设计，标量宏可以只返回单个值。而对于表宏，语法跟标量宏是类似的，除了关键字`AS`被替换成了`AS TABLE`。表宏可以返回任意大小和格式的表。

- **例子**

```
%%sql
/*创建一种加法运算符*/
CREATE MACRO add(a, b) AS a + b;

/*创建一种新的条件语句语法, 如果满足条件a, 则输出值b, 否则是c*/
CREATE MACRO ifelse(a, b, c) AS CASE WHEN a THEN b ELSE c END;

/*定义一个函数one(), 该函数能直接调用出后面SELECT语句抽出的表格*/
CREATE MACRO one() AS (SELECT 1);

/*创建一个带参数b的函数, 函数作用于一个名为cte的表格, 从表格中取出名为a的列, 再对a列的值加上b*/
CREATE MACRO plus_one(b) AS (WITH cte AS (SELECT 1 AS a) SELECT cte.a + b FROM cte);

/*创建一个均值函数*/
CREATE FUNCTION main.myavg(x) AS SUM(x) / COUNT(x);

/*创建一个包含默认参数的函数, 以下函数中参数b默认为5*/
CREATE MACRO add_default(a, b := 5) AS a + b;

/*创建一个数组添加函数, 传入参数l和e, l是一个数组结构数据, 该函数实现了将e添加到l的尾端这一功能*/
CREATE MACRO arr_append(l, e) AS list_concat(l, list_value(e));

/*自定义一个不需要传参的函数, 调用这个函数会返回一张表*/
CREATE MACRO static_table() AS TABLE SELECT 'Hello' as column1, 'World' as column2;

/*定义一个作用于动态表的带参数的函数, 以下函数实现的功能是: 传入的参数直接输出成一张两个字段的表*/
CREATE MACRO dynamic_table(col1_value,col2_value) AS TABLE SELECT col1_value as column1, col2_value as column2;

/*定义一个作用于动态表的带参数的函数*/
CREATE OR REPLACE MACRO dynamic_table(col1_value,col2_value) AS TABLE 
    SELECT col1_value as column1, col2_value as column2 
    UNION ALL 
    SELECT 'Hello' as col1_value, 456 as col2_value;
```

- **语法**

宏允许您为表达式组合创建快捷方式。

```
%%sql
/*以下这个代码会报错, 因为b没有被定义*/
CREATE MACRO add(a) AS a + b;

/*定义加法运算函数*/
CREATE MACRO add(a,b) AS a + b;

/*字符串和数值格式不匹配, 所以这里会报错*/
SELECT add('hello', 3);

/*这里是成功的*/
SELECT add(1, 2);
```

宏可以具有默认参数。

```
%%sql
CREATE MACRO add_default(a, b := 5) AS a + b;

/*结果返回42*/
SELECT add_default(37);

/*结果会报错, 只能填入一个参数, 没有指定的情况下无法修改默认参数*/
SELECT add_default(40, 2);

/*结果返回42*/
SELECT add_default(40, b:=2);

/*结果报错, 默认参数和非默认参数之间不能被改变传参位置*/
SELECT add_default(b:=2, 40);

/*默认参数之间是可以改变传参位置的*/
CREATE MACRO triple_add(a, b := 5, c := 10) AS a + b + c;
SELECT triple_add(40, c := 1, b := 1);
```

当使用宏时，它们被展开（即替换为原始表达式），并且扩展表达式中的参数将替换为提供的参数。具体步骤如下：

```
%%sql
/*使用宏*/
SELECT add(40, 2);

/*宏展开成原始表达式*/
SELECT a + b;

/*然后将宏的参数替换原始表达式中的a和b*/
SELECT 40 + 2;
```

##### pivot
`PIVOT`语句的主要功能是将列中的不同值分隔到它们自己的列中。这些新列中的值是通过在与每个非重复值匹配的行子集进行聚合函数计算得到的。

`PIVOT_WIDER`是`PIVOT`的另一种写法，二者可相互替换使用。

**① 简化的pivot语法**

简化的`PIVOT`语法可以总结如下：

```
PIVOT [dataset]
ON [column(s)]
USING [value(s)]
GROUP BY [row(s)]
```

`ON`，`USING`和`GROUP BY`子句都是可选的，但不能全部省略。

- **示例数据**

首先, 抽取`399330.SZ、000300.SH、000852.SH、000852.SH`的部分指数成分股`000001.SZ、000002.SZ、002061.SZ、002063.SZ、002068.SZ`:

```
%%sql
CREATE TABLE IF NOT EXISTS bigquant_table AS
SELECT a.date, a.instrument, b.index_code, a.volume
FROM cn_stock_bar1d AS a
INNER JOIN (
    SELECT date, instrument index_code, member_code instrument
    FROM cn_stock_index_component
    WHERE date > '2023-09-11'
) AS b
ON a.date = b.date AND a.instrument = b.instrument
WHERE a.instrument IN ('000001.SZ', '000002.SZ', '002061.SZ', '002063.SZ', '002068.SZ') AND index_code IN ('399330.SZ', '000300.SH', '000852.SH', '000852.SH')
ORDER BY a.date, a.instrument;

SELECT * FROM bigquant_table;
```

| date | instrument | index_code | volume |
|---|---|---|---|
| 2023-09-12 | 000001.SZ | 399330.SZ | 49548506 |
| 2023-09-12 | 000001.SZ | 000300.SH | 49548506 |
| 2023-09-12 | 000002.SZ | 399330.SZ | 41997403 |
| 2023-09-12 | 000002.SZ | 000300.SH | 41997403 |
| …… | …… | …… | …… |
| 2023-09-15 | 000002.SZ | 399330.SZ | 38951414 |
| 2023-09-15 | 002061.SZ | 000852.SH | 15470940 |
| 2023-09-15 | 002063.SZ | 000852.SH | 12598762 |
| 2023-09-15 | 002068.SZ | 000852.SH | 5826088 |

- **PIVOT ON和USING**

使用以下`PIVOT`语句为每年创建一个单独的列，并且计算每天总成交量。

`ON`子句指定哪一列或者哪几列需要拆分为单独的列。它等效于excel中数据透视表的列参数；

`USING`子句确定如何聚合拆分为单独列的值。这等效于excel何种数据透视表的值参数；

如果没有`USING`子句，则默认使用`SUM(*)`进行聚合。

```
%%sql
/*统计每个指数每天的总成交量*/

CREATE TABLE IF NOT EXISTS bigquant_table AS
SELECT a.date, a.instrument, b.index_code, a.volume
FROM cn_stock_bar1d AS a
INNER JOIN (
    SELECT date, instrument index_code, member_code instrument
    FROM cn_stock_index_component
    WHERE date > '2023-09-11'
) AS b
ON a.date = b.date AND a.instrument = b.instrument
WHERE a.instrument IN ('000001.SZ', '000002.SZ', '002061.SZ', '002063.SZ', '002068.SZ') AND index_code IN ('399330.SZ', '000300.SH', '000852.SH', '000852.SH')
ORDER BY a.date, a.instrument;

/*之后每次访问bigquant_table都必须加上上述创建表格的语句*/
PIVOT bigquant_table ON date USING SUM(volume);
```

| instrument | index_code | 2023-09-12 | …… | 2023-09-15 |
|---|---|---|---|---|
| 000001.SZ | 399330.SZ | 49548506 | …… | 89047613 |
| 000001.SZ | 000300.SH | 49548506 | …… | 89047613 |
| …… | …… | …… | …… | …… |
| 002068.SZ | 000852.SH | 11382458 | …… | 5826088 |

在上面的示例中，`SUM`聚合函数总是对单个值进行操作。如果我们只想更改数据的显示方向而不进行聚合计算，则可以使用`FIRST`聚合函数。在这个示例中，虽然我们是透视的数值，但是使用`FIRST`函数也可以非常方便地透视文本列。

此查询生成的结果与上述结果相同：

```
%%sql
/*统计每个指数每天的总成交量*/

CREATE TABLE IF NOT EXISTS bigquant_table AS
SELECT a.date, a.instrument, b.index_code, a.volume
FROM cn_stock_bar1d AS a
INNER JOIN (
    SELECT date, instrument index_code, member_code instrument
    FROM cn_stock_index_component
    WHERE date > '2023-09-11'
) AS b
ON a.date = b.date AND a.instrument = b.instrument
WHERE a.instrument IN ('000001.SZ', '000002.SZ', '002061.SZ', '002063.SZ', '002068.SZ') AND index_code IN ('399330.SZ', '000300.SH', '000852.SH', '000852.SH')
ORDER BY a.date, a.instrument;

PIVOT bigquant_table ON date USING FIRST(volume);
```

- **PIVOT ON，USING和GROUP BY**

默认情况下，`PIVOT`语句保留所有没在`ON`或者`USING`子句中指定的列。

若要仅包含某些列并进一步聚合，可以在`GROUP BY`子句中指定列。这相当于在excel数据透视表中的行参数。

在下面的示例中，`index_code`列不再包含在输出中，数据将聚合到`instrument`级别。

```
%%sql
CREATE TABLE IF NOT EXISTS bigquant_table AS
SELECT a.date, a.instrument, b.index_code, a.volume
FROM cn_stock_bar1d AS a
INNER JOIN (
    SELECT date, instrument index_code, member_code instrument
    FROM cn_stock_index_component
    WHERE date > '2023-09-11'
) AS b
ON a.date = b.date AND a.instrument = b.instrument
WHERE a.instrument IN ('000001.SZ', '000002.SZ', '002061.SZ', '002063.SZ', '002068.SZ') AND index_code IN ('399330.SZ', '000300.SH', '000852.SH', '000852.SH')
ORDER BY a.date, a.instrument;

PIVOT bigquant_table ON instrument USING SUM(volume) GROUP BY date;
```

| instrument | 2023-09-12 | …… | 2023-09-15 |
|---|---|---|---|
| 000001.SZ | 99097012 | …… | 1158 |
| …… | …… | …… | …… |
| 002068.SZ | 11382458 | …… | 5826088 |

- **在ON子句中使用IN表达式做过滤**

若要仅为`ON`子句中列中的特定值创建单独的列，可以使用`IN`表达式。例如我们想要日期为`2023-09-12、2023-09-13`每只股票的成交量：

```
%%sql
/*取出特定日期列*/

CREATE TABLE IF NOT EXISTS bigquant_table AS
SELECT a.date, a.instrument, b.index_code, a.volume
FROM cn_stock_bar1d AS a
INNER JOIN (
    SELECT date, instrument index_code, member_code instrument
    FROM cn_stock_index_component
    WHERE date > '2023-09-11'
) AS b
ON a.date = b.date AND a.instrument = b.instrument
WHERE a.instrument IN ('000001.SZ', '000002.SZ', '002061.SZ', '002063.SZ', '002068.SZ') AND index_code IN ('399330.SZ', '000300.SH', '000852.SH', '000852.SH')
ORDER BY a.date, a.instrument;

PIVOT bigquant_table ON date IN ('2023-09-12', '2023-09-13') USING SUM(volume) GROUP BY instrument;
```

| instrument | 2023-09-12 | 2023-09-13 |
|---|---|---|
| 000001.SZ | 49548506 | 49021797 |
| 000002.SZ | 41997403 | 38931911 |
| 002061.SZ | 9552777 | 19570800 |
| 002063.SZ | 9497603 | 19020440 |
| 002068.SZ | 11382458 | 11276348 |

- **每个子句多个表达式**

可以在`ON`和`GROUP BY`子句中指定多个列，并且可以在`USING`子句中包含多个聚合表达式。

**ON多个列和ON多个表达式**

可以将多个列透视到它们自己的列中。我们会在每个`ON`子句列中找到不同的值，并为这些值的所有组合创建一个新列（笛卡尔积）。

在下面的示例中，`instrument`和`index_code`的所有唯一组合都会组成一个新列。某些组合在基础数据中可能不存在，那么这些列会用`NULL`值进行填充。

```
%%sql
/*以时间为列, 统计每支股票的成交量*/

CREATE TABLE IF NOT EXISTS bigquant_table AS
SELECT a.date, a.instrument, b.index_code, a.volume
FROM cn_stock_bar1d AS a
INNER JOIN (
    SELECT date, instrument index_code, member_code instrument
    FROM cn_stock_index_component
    WHERE date > '2023-09-11'
) AS b
ON a.date = b.date AND a.instrument = b.instrument
WHERE a.instrument IN ('000001.SZ', '000002.SZ', '002061.SZ', '002063.SZ', '002068.SZ') AND index_code IN ('399330.SZ', '000300.SH', '000852.SH', '000852.SH')
ORDER BY a.date, a.instrument;

PIVOT bigquant_table ON instrument, index_code  USING SUM(volume) GROUP BY date;
```

| date | 000001.SZ_000300.SH | 000001.SZ_000852.SH | …… | 002068.SZ_399330.SZ |
|---|---|---|---|---|
| 2023-09-12 | 49548506 | NULL | …… | NULL |
| 2023-09-13 | 49021797 | NULL | …… | NULL |
| 2023-09-14 | 55165017 | NULL | …… | NULL |
| 2023-09-15 | 89047613 | NULL | …… | NULL |

若仅要透视基础数据中存在的值组合，可以在`ON`子句中使用表达式。

在下面的例子中，`instrument`和`index_code`通过下划线连接在一起，生成的每个连接都会作为一列。当然也可以使用其它任何非聚合的表达式进行连接：

```
%%sql
/*用'-'连起来*/

CREATE TABLE IF NOT EXISTS bigquant_table AS
SELECT a.date, a.instrument, b.index_code, a.volume
FROM cn_stock_bar1d AS a
INNER JOIN (
    SELECT date, instrument index_code, member_code instrument
    FROM cn_stock_index_component
    WHERE date > '2023-09-11'
) AS b
ON a.date = b.date AND a.instrument = b.instrument
WHERE a.instrument IN ('000001.SZ', '000002.SZ', '002061.SZ', '002063.SZ', '002068.SZ') AND index_code IN ('399330.SZ', '000300.SH', '000852.SH', '000852.SH')
ORDER BY a.date, a.instrument;

PIVOT bigquant_table ON instrument || '-' || index_code  USING FIRST(volume) GROUP BY date;
```

| date | 000001.SZ-000300.SH | …… | 002068.SZ-000852.SH |
|---|---|---|---|
| 2023-09-12 | 49548506 | …… | 11382458 |
| 2023-09-13 | 49021797 | …… | 11276348 |
| 2023-09-14 | 55165017 | …… | 7103837 |
| 2023-09-15 | 89047613 | …… | 5826088 |

**USING多个表达式**

可以为`USING`子句中的每个表达式设置一个别名。该别名会被添加到生成的列名之后，并用下划线（`_`）连接。这使得在 USING 子句中包含多个表达式时列名会更加清晰。

在此示例中，计算每年`volume`列的`SUM`和`MAX`被拆分成了单独的列：

```
%%sql
/*统计指数最大值和均值*/

CREATE TABLE IF NOT EXISTS bigquant_table AS
SELECT a.date, a.instrument, b.index_code, a.volume
FROM cn_stock_bar1d AS a
INNER JOIN (
    SELECT date, instrument index_code, member_code instrument
    FROM cn_stock_index_component
    WHERE date > '2023-09-11'
) AS b
ON a.date = b.date AND a.instrument = b.instrument
WHERE a.instrument IN ('000001.SZ', '000002.SZ', '002061.SZ', '002063.SZ', '002068.SZ') AND index_code IN ('399330.SZ', '000300.SH', '000852.SH', '000852.SH')
ORDER BY a.date, a.instrument;

PIVOT bigquant_table ON instrument USING MAX(volume) max, AVG(volume) avg GROUP BY date;
```

| date | 000001.SZ_max | 000001.SZ_avg | …… | 002063.SZ_avg | 002068.SZ_max | 002068.SZ_avg |
|---|---|---|---|---|---|---|
| 2023-09-12 | 49548506 | 49548506.0 | …… | 9497603.0 | 11382458 | 11382458.0 |
| …… | …… | …… | …… | …… | …… | …… |
| 2023-09-18 | 50132501 | 50132501.0 | …… | 11398882.0 | 10294500 | 10294500.0 |

**GROUP BY多个列**

请注意，必须使用列名而不是列位置（1、2 等），并且`GROUP BY`子句中不支持表达式。

```
%%sql
/*统计个股的面板数据*/

CREATE TABLE IF NOT EXISTS bigquant_table AS
SELECT a.date, a.instrument, b.index_code, a.volume
FROM cn_stock_bar1d AS a
INNER JOIN (
    SELECT date, instrument index_code, member_code instrument
    FROM cn_stock_index_component
    WHERE date > '2023-09-11'
) AS b
ON a.date = b.date AND a.instrument = b.instrument
WHERE a.instrument IN ('000001.SZ', '000002.SZ', '002061.SZ', '002063.SZ', '002068.SZ') AND index_code IN ('399330.SZ', '000300.SH', '000852.SH', '000852.SH')
ORDER BY a.date, a.instrument;

PIVOT bigquant_table ON date USING SUM(volume) GROUP BY instrument, index_code;
```

| instrument | index_code | …… | 2023-09-15 | 2023-09-18 |
|---|---|---|---|---|
| 000001.SZ | 399330.SZ | …… | 89047613 | 50132501 |
| …… | …… | …… | …… | …… |
| 002068.SZ | 000852.SH | …… | 5826088 | 50132501 |

- **在SELECT语句中使用PIVOT**

`PIVOT`语句可以作为[CTE](https://bigquant.com/wiki/doc/dai-PLSbc1SbZX#h-with)或者子查询被包含在SELECT语句中。这样`PIVOT`就可以与其他SQL逻辑一起使用，并且一个查询中也可以使用多个`PIVOT`语句。

在CTE中，可以用`PIVOT`关键字替代`SELECT`。

```
%%sql
CREATE TABLE IF NOT EXISTS bigquant_table AS
SELECT a.date, a.instrument, b.index_code, a.volume
FROM cn_stock_bar1d AS a
INNER JOIN (
    SELECT date, instrument index_code, member_code instrument
    FROM cn_stock_index_component
    WHERE date > '2023-09-11'
) AS b
ON a.date = b.date AND a.instrument = b.instrument
WHERE a.instrument IN ('000001.SZ', '000002.SZ', '002061.SZ', '002063.SZ', '002068.SZ') AND index_code IN ('399330.SZ', '000300.SH', '000852.SH', '000852.SH')
ORDER BY a.date, a.instrument;

WITH pivot_alias AS (
    PIVOT bigquant_table ON instrument USING MAX(volume) max, AVG(volume) avg GROUP BY date
) 
SELECT * FROM pivot_alias;
```

`PIVOT` 可以在子查询中使用，并且必须括在括号中。请注意，此操作与标准SQL透视不同，如后续示例所示。

```
%%sql
CREATE TABLE IF NOT EXISTS bigquant_table AS
SELECT a.date, a.instrument, b.index_code, a.volume
FROM cn_stock_bar1d AS a
INNER JOIN (
    SELECT date, instrument index_code, member_code instrument
    FROM cn_stock_index_component
    WHERE date > '2023-09-11'
) AS b
ON a.date = b.date AND a.instrument = b.instrument
WHERE a.instrument IN ('000001.SZ', '000002.SZ', '002061.SZ', '002063.SZ', '002068.SZ') AND index_code IN ('399330.SZ', '000300.SH', '000852.SH', '000852.SH')
ORDER BY a.date, a.instrument;

SELECT 
    * 
FROM (
    PIVOT bigquant_table ON instrument USING MAX(volume) max, AVG(volume) avg GROUP BY date
) pivot_alias;
```

**使用多个Pivots**

每个`PIVOT`都可以被当作`SELECT`，也可以使用`JOIN`或者一些其他方式进行操作。

例如，如果两个`PIVOT`语句共享同一个`GROUP BY`表达式，则可以使用`GROUP BY`子句中的列将它们连接在一起。

```
%%sql
CREATE TABLE IF NOT EXISTS bigquant_table AS
SELECT a.date, a.instrument, b.index_code, a.volume
FROM cn_stock_bar1d AS a
INNER JOIN (
    SELECT date, instrument index_code, member_code instrument
    FROM cn_stock_index_component
    WHERE date > '2023-09-11'
) AS b
ON a.date = b.date AND a.instrument = b.instrument
WHERE a.instrument IN ('000001.SZ', '000002.SZ', '002061.SZ', '002063.SZ', '002068.SZ') AND index_code IN ('399330.SZ', '000300.SH', '000852.SH', '000852.SH')
ORDER BY a.date, a.instrument;

FROM (
    PIVOT bigquant_table ON index_code USING SUM(volume) GROUP BY date
)
JOIN (
    PIVOT bigquant_table ON instrument USING SUM(volume) GROUP BY date
)
USING (date);
```

| instrument | 2023-09-12 | 2023-09-13 | …… | 000300.SH | 000852.SH | 399330.SZ |
|---|---|---|---|---|---|---|
| 000001.SZ | 99097012 | 98043594 | …… | 292915434 | NULL | 292915434 |
| …… | …… | …… | …… | …… | …… | …… |
| 002068.SZ | 11382458 | 11276348 | …… | NULL | 45883231 | NULL |

**② SQL标准pivot语法**

SQL的标准`PIVOT`语法如下：

```
FROM [dataset] 
PIVOT (
    [values(s)]
    FOR 
        [column_1] IN ([in_list])
        [column_2] IN ([in_list])
        ...
    GROUP BY [rows(s)]
)
```

与简化语法不同，必须要为透视的每一列指定`IN`子句。 如果您对动态透视感兴趣，建议使用简化语法。

请注意，`FOR`子句中的表达式之间没有逗号分隔，但`value`和`GROUP BY`表达式必须以逗号分隔！

- **例子**

此示例使用单值表达式、单列表达式和单行表达式：

```
%%sql
CREATE TABLE IF NOT EXISTS bigquant_table AS
SELECT a.date, a.instrument, b.index_code, a.volume
FROM cn_stock_bar1d AS a
INNER JOIN (
    SELECT date, instrument index_code, member_code instrument
    FROM cn_stock_index_component
    WHERE date > '2023-09-11'
) AS b
ON a.date = b.date AND a.instrument = b.instrument
WHERE a.instrument IN ('000001.SZ', '000002.SZ', '002061.SZ', '002063.SZ', '002068.SZ') AND index_code IN ('399330.SZ', '000300.SH', '000852.SH', '000852.SH')
ORDER BY a.date, a.instrument;

FROM bigquant_table
PIVOT (
    SUM(volume)
    FOR date IN ('2023-09-12', '2023-09-13')
    GROUP BY instrument
);
```

| instrument | 2023-09-12 | 2023-09-13 |
|---|---|---|
| 000001.SZ | 99097012 | 98043594 |
| …… | …… | …… |
| 002068.SZ | 11382458 | 11276348 |

此示例在`FOR`子句中使用多个值表达式和多个列。

```
%%sql
CREATE TABLE IF NOT EXISTS bigquant_table AS
SELECT a.date, a.instrument, b.index_code, a.volume
FROM cn_stock_bar1d AS a
INNER JOIN (
    SELECT date, instrument index_code, member_code instrument
    FROM cn_stock_index_component
    WHERE date > '2023-09-11'
) AS b
ON a.date = b.date AND a.instrument = b.instrument
WHERE a.instrument IN ('000001.SZ', '000002.SZ', '002061.SZ', '002063.SZ', '002068.SZ') AND index_code IN ('399330.SZ', '000300.SH', '000852.SH', '000852.SH')
ORDER BY a.date, a.instrument;

FROM bigquant_table
PIVOT (
    SUM(volume), 
    AVG(volume)
    FOR 
        date IN ('2023-09-12', '2023-09-13')
        instrument IN ('000001.SZ', '000002.SZ')
);
```

| index_code | 2023-09-12_000001.… | …… | 2023-09-13_000001.… | 2023-09-13_000002.… | 2023-09-13_000002.… |
|---|---|---|---|---|---|
| 399330.SZ | 49548506 | …… | 49021797.0 | 38931911 | 38931911.0 |
| 000300.SH | 49548506 | …… | 49021797.0 | 38931911 | 38931911.0 |
| 000852.SH | NULL | …… | NULL | NULL | NULL |

#### select语法详解
`SELECT`子句指定查询将返回的列的列表。虽然它首先出现在子句中，但从逻辑上讲，此处的表达式却仅在最后执行。它可以包含转换输出的任意表达式，以及聚合函数和窗口函数。

- **例子**

```
%%sql
/*从后复权日行情表cn_stock_bar1d中抽取所有字段的数据*/
SELECT * FROM cn_stock_bar1d;

/*对表cn_stock_bar1d按照字段instrument去重后取出instrument字段的数据*/
SELECT DISTINCT instrument FROM cn_stock_bar1d;

/*统计数据的条数(一共多少行)*/
SELECT COUNT(*) FROM cn_stock_bar1d;

/*除了成交量, 其他数据全部取出*/
SELECT * EXCLUDE (volume) FROM cn_stock_bar1d;

/*取出所有字段的数据, 其中让股票代码所有英文后缀小写*/
SELECT * REPLACE (LOWER(instrument) AS instrument) FROM cn_stock_bar1d;

/*筛选出列名包含特定字符的字段(正则表达式匹配)*/
SELECT COLUMNS('v[a-z]*e') FROM cn_stock_bar1d;

/*拿到每个字段的最小值*/
SELECT MIN(COLUMNS(*)) FROM cn_stock_bar1d;
```

##### from & join
`FROM`子句指定查询操作的数据源。从逻辑上讲，`FROM`子句是查询开始执行的位置。`FROM`子句可以包含单个表、使用`JOIN`子句联接在一起的多个表的组合或子查询节点内的另一个`SELECT`查询。DAI还可以把`FROM`放在最前面，可以在没有`SELECT`语句的情况下进行查询。

- **例子**

```
%%sql
/*从表cn_stock_bar1d中取出所有字段*/
FROM cn_stock_bar1d;

/*同上*/
SELECT * FROM cn_stock_bar1d;

/*从csv文件中导入数据*/
SELECT * FROM 'test.csv';

/*子查询出来的数据依旧可以看一个表, 所以可以对子表进行查询语句*/
SELECT * FROM (SELECT * FROM cn_stock_bar1d);

/*使用join函数对两个表进行连接*/
SELECT a.date, a.instrument, a.close, b.total_market_cap
FROM cn_stock_bar1d AS a
JOIN (
    SELECT date, instrument, total_market_cap
    FROM cn_stock_valuation
    WHERE date > '2022-01-01'
) AS b
ON a.date = b.date AND a.instrument = b.instrument;

/*从2023年9月18日当天抽取80%的样本作为股票池(最好不要用百分数)*/
SELECT * FROM (
    SELECT date, instrument, close
    FROM cn_stock_bar1d
    WHERE date = '2023-09-18'
)
TABLESAMPLE 80%;

/*抽取10个样本(推荐)*/
SELECT * FROM (
    SELECT date, instrument, close
    FROM cn_stock_bar1d
    WHERE date = '2023-09-18'
)
TABLESAMPLE 10 ROWS;
```

- **联接**

联接是用于水平连接两个表或关系的基本关系操作。基于它们在`JOIN`子句中的位置，这些关系称为连接的左侧和右侧。每个结果行都有来自两个关系的列。

联接会使用某一种规则来匹配每个关系中的行对。通常这是一个谓词，但也可以指定其他隐含规则。

**OUTER JOIN**

如果指明是`OUTER JOIN`，那么没有任何匹配项的行仍然会返回。 外联接可以是以下的一种：

- `LEFT` (左侧表中的所有行至少出现一次)
- `RIGHT` (右侧表中的所有行至少出现一次)
- `FULL` (两个表中的所有行至少出现一次)

与`OUTER`相对的是`INNER`，它表示仅返回配对的行。

返回未配对的行时，不存在的属性将设置为`NULL`。

**CROSS JOIN**

最简单的联接类型是`CROSS JOIN`。这种类型的联接没有条件，它只是返回所有可能的组合。

```
%%sql
/*返回所有匹配行*/
SELECT a.*, b.* FROM cn_stock_valuation AS a CROSS JOIN cn_stock_bar1d AS b;
```

**条件联接**

大多数联接可以使用`ON`或者`WHERE`子句显式指定联接条件。

```
%%sql
/*查看指数和其成分股的换手率*/
SELECT a.date, a.instrument, a.turn, b.index_code
FROM cn_stock_bar1d AS a
INNER JOIN (
    SELECT date, instrument index_code, member_code instrument
    FROM cn_stock_index_component
    WHERE date > '2022-01-01'
) AS b
ON a.date = b.date AND a.instrument = b.instrument;
```

如果列名相同且条件是相等， 可以使用更简单的`USING`语法：

```
%%sql
/*日行情数据和估值数据公用日期和股票代码, 使用USING语句对二表进行连接*/
SELECT date, instrument, close, total_market_cap 
FROM cn_stock_valuation 
JOIN cn_stock_bar1d 
USING(date, instrument);
```

表达式不必是等式，可以使用任何谓词：

```
%%sql
/*选取收盘价大于开盘价的股票(动量较大)*/
SELECT date, instrument, close, open
FROM cn_stock_bar1d
WHERE close > open AND date > '2020-01-01';
```

**POSITIONAL JOIN**

使用相同大小的数据框或其他嵌入式表时，这些行可能具有基于其物理顺序的自然对应关系。在python脚本语言中，这很容易用循环来表达：

```
for i in range(n):
    f(t1.a[i], t2.b[i])
```

然后在标准SQL中却很难表达出来，因为关系表不是有序的，然而导入的表（如Dataframe）或磁盘文件（如CSV或Parquet文件）往往具有自然排序。如果要使用这种顺序进行联接则可以使用`POSITIONAL JOIN`：

```
%%sql
/*没有连接条件, 原来的表是怎样的顺序, 连接的时候依旧是原来的顺序(除非两表的数据一一对应, 否则不推荐使用该连接方式)*/
SELECT a.date, a.instrument, a.close, b.total_market_cap
FROM cn_stock_bar1d AS a
POSITIONAL JOIN
cn_stock_valuation AS b
WHERE a.date = '2022-02-17'
ORDER BY a.instrument;
```

`POSITIONAL JOIN`是`FULL OUTER`联接。

**ASOF JOIN**

处理时态或类似顺序数据时的常见操作是在表中查找最近的（第一个）数据：

```
%%sql
SELECT a.date, a.instrument, a.close, b.open
FROM (SELECT * FROM cn_stock_bar1d WHERE date > '2023-07-01') AS a
ASOF JOIN
(SELECT * FROM cn_stock_bar1d WHERE date > '2023-07-01') AS b
ON a.date = b.date AND a.instrument = b.instrument AND a.close > b.open;
```

`ASOF JOIN`要求排序字段上至少有一个不等条件，并且左侧的表必须是更大的一侧， 任何其他条件必须是相等的（或`NOT DISTINCT`）。 这意味着表的左/右顺序在这种联接中是很重要的。

`ASOF JOIN`仅将每个左侧行与最多一个右侧行配对。可以将其指定为`OUTER`联接以查找未配对的行

```
%%sql
SELECT a.date, a.instrument, a.close, b.open
FROM (SELECT * FROM cn_stock_bar1d WHERE date > '2023-07-01') AS a
ASOF LEFT JOIN
(SELECT * FROM cn_stock_bar1d WHERE date > '2023-07-01') AS b
ON a.date = b.date AND a.instrument = b.instrument AND a.close > b.open;
```

##### where
`WHERE`子句指明要应用于数据源的筛选器，这样您就可以选择感兴趣的数据子集。一般来说，`WHERE`子句紧跟在`FROM`子句之后执行。

- **例子**

```
%%sql
/*查看个股000001.SZ收盘价的时间序列*/
SELECT date, instrument, close
FROM cn_stock_bar1d
WHERE instrument = '000001.SZ';

/*筛选出股票代码后缀包含SZ的所有股票的收盘价*/
SELECT date, instrument, close
FROM cn_stock_bar1d
WHERE instrument LIKE '%SZ';

/*筛选出股票代码为000001.SZ、000002.SZ的收盘价序列*/
SELECT date, instrument, close
FROM cn_stock_bar1d
WHERE instrument = '000001.SZ' OR instrument = '000002.SZ';
```

##### group by
`GROUP BY`子句指明应使用哪些分组列来执行`SELECT`子句中的任何聚合。如果指定了`GROUP BY`子句，则查询就是聚合查询，即使`SELECT`子句中不存在聚合也是如此。

当指定`GROUP BY`子句时，分组列中具有匹配数据的所有元组（即属于同一组的所有元组）将被合并。分组列本身的值保持不变，任何其他列都可以使用聚合函数（如`COUNT`、`SUM`、`AVG`等）进行合并。

通常，`GROUP BY`子句沿单个维度分组。使用GROUPING SETS、CUBE或ROLLUP子句可以沿多个维度进行分组。

- **例子**

```
%%sql
/*统计自2022年初以来每日市场的平均换手率*/
SELECT date, AVG(turn)
FROM cn_stock_bar1d
WHERE date > '2022-01-01'
GROUP BY date;
```

##### grouping sets
`GROUPING SETS`，`ROLLUP`和`CUBE`都可以在`GROUP BY`子句中使用，以对同一查询中的多个维度进行分组。

- **例子**

```
%%sql
/*统计一级行业日均成交量和二级行业日均成交量*/
WITH bigquant_table AS (
    SELECT a.date, a.instrument, a.industry_level1_name, a.industry_level2_name, b.volume
    FROM cn_stock_industry_component AS a
    INNER JOIN (
        SELECT date, instrument, volume
        FROM cn_stock_bar1d
        WHERE date > '2023-01-01'
    ) AS b
    ON a.date = b.date AND a.instrument = b.instrument
)
SELECT date, industry_level1_name, industry_level2_name, AVG(volume) FROM bigquant_table GROUP BY GROUPING SETS((date, industry_level1_name), (date, industry_level2_name)) ORDER BY date;
```

- **描述**

`GROUPING SETS`可以在单个查询中跨不同`GROUP BY`子句执行相同的聚合。

```
%%sql
CREATE TABLE bigquant_employee(course VARCHAR, type VARCHAR);
INSERT INTO bigquant_employee(course, type) VALUES ('CS', 'Bachelor'), ('CS', 'Bachelor'), ('CS', 'PhD'), ('Math', 'Masters'), ('CS', NULL), ('CS', NULL), ('Math', NULL);
```

```
%%sql
SELECT course, type, COUNT(*)
FROM bigquant_employee
GROUP BY GROUPING SETS ((course, type), course, type, ());
```

```
┌────────┬──────────┬──────────────┐
│ course │   type   │ count_star() │
├────────┼──────────┼──────────────┤
│ CS     │ Bachelor │ 2            │
│ CS     │ PhD      │ 1            │
│ Math   │ Masters  │ 1            │
│ CS     │ NULL     │ 2            │
│ Math   │ NULL     │ 1            │
│ CS     │ NULL     │ 5            │
│ Math   │ NULL     │ 2            │
│ NULL   │ Bachelor │ 2            │
│ NULL   │ PhD      │ 1            │
│ NULL   │ Masters  │ 1            │
│ NULL   │ NULL     │ 3            │
│ NULL   │ NULL     │ 7            │
└────────┴──────────┴──────────────┘
```

在上面的查询中，我们分为四个不同的集合：`course, type`，`course`，`type`和`()`（空组）。上述查询等效于以下`UNION`语句：

```
%%sql
/*对course和type作聚类*/
SELECT course, type, COUNT(*)
FROM bigquant_employee
GROUP BY course, type
UNION ALL

/*对type作聚类*/
SELECT NULL AS course, type, COUNT(*)
FROM bigquant_employee
GROUP BY type
UNION ALL

/*对course作聚类*/
SELECT course, NULL AS type, COUNT(*)
FROM bigquant_employee
GROUP BY course
UNION ALL

/*不作聚类*/
SELECT NULL AS course, NULL AS type, COUNT(*)
FROM bigquant_employee
```

`CUBE`和`ROLLUP`是句法糖，可以轻松生成常用的分组集。

`ROLLUP`子句将产生分组集的所有“子组”，比如`ROLLUP (country, city, zip)`会生成分组集`(country, city, zip), (country, city), (country), ()`。也就是会生成`n+1`个分组集，其中n是`ROLLUP`子句中的项数。

`CUBE`为所有输入组合生成分组集，例如`CUBE (country, city, zip)` 将产生`(country, city, zip), (country, city), (country, zip), (city, zip), (country), (city), (zip), ()`。即生成`2^n`个分组集。

##### having
`HAVING`子句可以在`GROUP BY`子句后使用，以便在分组完成后提供筛选条件。在语法方面，`HAVING`子句和`WHERE`子句是相同的，只是`WHERE`在分组前执行，而`HAVING`子句在分组后执行。

- **例子**

```
%%sql
/*统计2023年9月20日不同指数下成分股的数量大于100个的指数*/
SELECT name, COUNT(*) number
FROM cn_stock_index_component
WHERE date = '2023-09-20'
GROUP BY name
HAVING number > 100; 
```

##### order by
`ORDER BY`是一个输出修饰语。从执行逻辑上说，它在查询的最后才会执行。`ORDER BY`子句按照排序条件对行进行升序或者降序排序。此外，每个order子句都可以指定将`NULL`值移动到开头还是结尾。

如果未指定修饰语，默认按照`ASC NULLS FIRST`排序，即按升序排序，并且空值放在第一位。

文本默认使用二进制比较规则进行排序，即根据其二进制的UTF8值进行排序。

- **例子**

```
%%sql
/*获取2022年以来的收盘价数据, 并按照日期进行升序排序*/
SELECT date, instrument, close
FROM cn_stock_bar1d
WHERE date > '2022-01-01'
ORDER BY date;

/*将存在NULL的行放在最后一行*/
SELECT date, instrument, close
FROM cn_stock_bar1d
WHERE date > '2022-01-01'
ORDER BY date NULLS LAST;

/*对日期进行升序排序, 进一步对换手率升序排序*/
SELECT date, instrument, turn
FROM cn_stock_bar1d
WHERE date > '2022-01-01'
ORDER BY date, turn;

/*COLLATE会对目标字符按照一定规则进行排序*/
SELECT *
FROM cn_stock_index_component
WHERE date = '2023-09-20'
ORDER BY member_name  COLLATE DE;
```

##### limit
`LIMIT`跟`ORDER BY`一样也是输出修饰语，也是在查询的最后执行。`LIMIT`子句限制提取的行数。`OFFSET`子句指明从哪个位置开始读取数据。

注意，虽然`LIMIT`可以在没有`ORDER BY`子句的情况下使用，但如果没有`ORDER BY`子句，结果可能是不定的。但无论如何，`LIMIT`可以帮助您查看部分数据快照。

- **例子**

```
%%sql
/*筛选出2023年9月20号这一天换手率最小的三只股票*/
SELECT date, instrument, turn
FROM cn_stock_bar1d
WHERE date = '2023-09-20'
ORDER BY turn LIMIT 3;

/*从第五行开始, 输出换手率最低的前三只股票*/
SELECT date, instrument, turn
FROM cn_stock_bar1d
WHERE date = '2023-09-20'
ORDER BY turn LIMIT 3 OFFSET 5;

/*按照成交量对股票降序排序*/
SELECT date, instrument, volume
FROM cn_stock_bar1d
WHERE date = '2023-09-20'
ORDER BY volume DESC;
```

##### unnest
`UNNEST`函数用于将列表转换为一组行，即平展操作。该函数可以用作常规标量函数，但只能在`SELECT`子句中使用。`UNNEST`是一个特殊函数，因为它改变了结果的基数。

当`UNNEST`与常规的标量表达式结合使用时，将对列表中的每个条目重复这些表达式。当多个列表在同一`SELECT`子句中取消展开时，这些列表将并排展开。如果一个列表比另一个列表长，则较短的列表将填充`NULL`值。

空列表和`NULL`列表都将平展为零元素。非类型化和类型化`NULL`参数都将返回零行。

- **例子**

```
%%sql
/*将列表[1, 2, 3]展开成一张表, 表共三行*/
SELECT UNNEST([1, 2, 3]);

/*每个UNNEST语句都会展开成一列, 将两个列表展开成三行两列的表, 不足三行的用NULL填充*/
/*返回结果((1, 10), (2, 11), (3, NULL))*/
SELECT UNNEST([1, 2, 3]), UNNEST([10, 11]);

/*返回结果((1, 10), (2, 10), (3, 10))*/
SELECT UNNEST([1, 2, 3]), 10;

/*建立一个每行为列表的表, 再对每行的列表进行展开*/
/*((1, 2, 3), (4, 5))-->((11), (12), (13), (14), (15))*/
SELECT UNNEST(l) + 10 FROM (VALUES ([1, 2, 3]), ([4, 5])) tbl(l);

/*创建一个空表, 没有行数*/
SELECT UNNEST([]);

/*创建一个空表, 没有行数*/
SELECT UNNEST(NULL);

/*创建一个空表, 没有行数*/
SELECT UNNEST(NULL::int[]);
```

##### with
`WITH`子句用于指定公用表表达式（CTE）。常规（非递归）公用表表达式本质上是仅限于特定查询的视图。CTE可以相互引用，并且可以嵌套。

- **基础的CTE例子**

```
%%sql
/*创建一个CTE, 将其命名为bigquant_table, 并且用查询语句去调用它*/
WITH bigquant_table AS (SELECT 42 AS x)
SELECT * FROM bigquant_table;
```

```
┌────┐
│ x  │
├────┤
│ 42 │
└────┘
```

```
%%sql
/*创建两个CTE, 第二个cte嵌套第一个cte*/
WITH bigquant_table_1 AS (SELECT 42 AS i),
    bigquant_table_2 AS (SELECT i*100 AS x FROM bigquant_table_1)
SELECT * FROM bigquant_table_2;
```

```
┌──────┐
│  x   │
├──────┤
│ 4200 │
└──────┘
```

- **递归CTE例子——树遍历**

`WITH RECURSIVE`可用于遍历树。例如，处理以下标签的层次结构：

```
%%sql
/*创建一个树*/
CREATE TABLE bigquant_tag(id int, name varchar, subclassof int);
INSERT INTO bigquant_tag VALUES
    (1, 'U2',     5),
    (2, 'Blur',   5),
    (3, 'Oasis',  5),
    (4, '2Pac',   6),
    (5, 'Rock',   7),
    (6, 'Rap',    7),
    (7, 'Music',  9),
    (8, 'Movies', 9),
    (9, 'Art', NULL);
```

以下查询返回从`Oasis`节点到树根的路径（`Art`）。

```
%%sql
/*完整代码*/
CREATE TABLE bigquant_tag(id int, name varchar, subclassof int);
INSERT INTO bigquant_tag VALUES
    (1, 'U2',     5),
    (2, 'Blur',   5),
    (3, 'Oasis',  5),
    (4, '2Pac',   6),
    (5, 'Rock',   7),
    (6, 'Rap',    7),
    (7, 'Music',  9),
    (8, 'Movies', 9),
    (9, 'Art', NULL);

WITH RECURSIVE tag_hierarchy(id, source, path) AS (
    SELECT id, name, [name] AS path
    FROM bigquant_tag
    WHERE subclassof IS NULL
UNION ALL
    SELECT bigquant_tag.id, bigquant_tag.name, list_prepend(bigquant_tag.name, tag_hierarchy.path)
    FROM bigquant_tag, tag_hierarchy
    WHERE bigquant_tag.subclassof = tag_hierarchy.id
)
SELECT path
FROM tag_hierarchy
WHERE source = 'Oasis';
```

```
┌───────────────────────────┐
│           path            │
├───────────────────────────┤
│ [Oasis, Rock, Music, Art] │
└───────────────────────────┘
```

- **递归CTE例子——图形遍历**

`WITH RECURSIVE`子句可用于表示任意图上的图遍历。但如果是有环图，则查询必须执行环路检测以防止无限循环。实现此目的的一种方法是将遍历的路径存储在[列表](https://bigquant.com/wiki/doc/list-udNuqzEiAO)中，并在使用新的边扩展路径之前，检查其端点之前是否被访问过（请参阅后面的示例）。

我们来看看以下有向图:

```
%%sql
CREATE TABLE bigquant_edge(node1id int, node2id int);
INSERT INTO bigquant_edge VALUES (1, 3), (1, 5), (2, 4), (2, 5), (2, 10), (3, 1), (3, 5),
    (3, 8), (3, 10), (5, 3), (5, 4), (5, 8), (6, 3), (6, 4), (7, 4), (8, 1), (9, 4);
```

注意，该图包含有向循环，例如节点1、2和5之间的有向循环。

**枚举节点中的所有路径**

以下查询返回从节点 1 开始的所有路径：

```
%%sql
/*完整代码*/
CREATE TABLE bigquant_edge(node1id int, node2id int);
INSERT INTO bigquant_edge VALUES (1, 3), (1, 5), (2, 4), (2, 5), (2, 10), (3, 1), (3, 5),
    (3, 8), (3, 10), (5, 3), (5, 4), (5, 8), (6, 3), (6, 4), (7, 4), (8, 1), (9, 4);

WITH RECURSIVE paths(startNode, endNode, path) AS (
    /*定义路径*/
    SELECT
        node1id AS startNode,
        node2id AS endNode,
        [node1id, node2id] AS path
        FROM bigquant_edge
        WHERE startNode = 1
    UNION ALL
    /*整合新的边*/
    SELECT
        paths.startNode AS startNode,
        node2id AS endNode,
        array_append(path, node2id) AS path
        FROM paths
        JOIN bigquant_edge ON paths.endNode = node1id
    /*防止添加重复的节点*/
    /*保证没有圆形循环发生*/
    WHERE node2id != ALL(paths.path)
)
SELECT startNode, endNode, path
FROM paths
ORDER BY length(path), path;
```

```
┌───────────┬─────────┬───────────────┐
│ startNode │ endNode │     path      │
├───────────┼─────────┼───────────────┤
│ 1         │ 3       │ [1, 3]        │
│ 1         │ 5       │ [1, 5]        │
│ 1         │ 5       │ [1, 3, 5]     │
│ 1         │ 8       │ [1, 3, 8]     │
│ 1         │ 10      │ [1, 3, 10]    │
│ 1         │ 3       │ [1, 5, 3]     │
│ 1         │ 4       │ [1, 5, 4]     │
│ 1         │ 8       │ [1, 5, 8]     │
│ 1         │ 4       │ [1, 3, 5, 4]  │
│ 1         │ 8       │ [1, 3, 5, 8]  │
│ 1         │ 8       │ [1, 5, 3, 8]  │
│ 1         │ 10      │ [1, 5, 3, 10] │
└───────────┴─────────┴───────────────┘
```

请注意，此查询的结果不限于最短路径，例如，对于节点5，结果包括路径`[1, 5]`和`[1, 3, 5]`。

**枚举节点中未加权的最短路径**

在大多数情况下，枚举所有路径是不切实际或不可行的。然而，**（未加权的）最短路径**却是比较有意思的。要找到这些路径，应调整`WITH RECURSIVE`查询的后半部分，使其仅包含尚未访问的节点。这是通过使用子查询来实现的，该子查询检查前面的任何路径是否包含节点：

```
%%sql
CREATE TABLE bigquant_edge(node1id int, node2id int);
INSERT INTO bigquant_edge VALUES (1, 3), (1, 5), (2, 4), (2, 5), (2, 10), (3, 1), (3, 5),
    (3, 8), (3, 10), (5, 3), (5, 4), (5, 8), (6, 3), (6, 4), (7, 4), (8, 1), (9, 4);

WITH RECURSIVE paths(startNode, endNode, path) AS (
    SELECT -- define the path as the first edge of the traversal
        node1id AS startNode,
        node2id AS endNode,
        [node1id, node2id] AS path
        FROM bigquant_edge
        WHERE startNode = 1
    UNION ALL
    SELECT -- concatenate new edge to the path
        paths.startNode AS startNode,
        node2id AS endNode,
        array_append(path, node2id) AS path
        FROM paths
        JOIN bigquant_edge ON paths.endNode = node1id
    -- Prevent adding a node that was visited previously by any path.
    -- This ensures that (1) no cycles occur and (2) only nodes that
    -- were not visited by previous (shorter) paths are added to a path.
    WHERE NOT EXISTS (SELECT 1
                    FROM paths previous_paths
                    WHERE list_contains(previous_paths.path, node2id))
)
SELECT startNode, endNode, path
FROM paths
ORDER BY length(path), path;
```

```
┌───────────┬─────────┬────────────┐
│ startNode │ endNode │    path    │
├───────────┼─────────┼────────────┤
│ 1         │ 3       │ [1, 3]     │
│ 1         │ 5       │ [1, 5]     │
│ 1         │ 8       │ [1, 3, 8]  │
│ 1         │ 10      │ [1, 3, 10] │
│ 1         │ 4       │ [1, 5, 4]  │
│ 1         │ 8       │ [1, 5, 8]  │
└───────────┴─────────┴────────────┘
```

**枚举两个节点之间的未加权最短路径**

`WITH RECURSIVE`还可用于查找**两个节点之间的所有（未加权）最短路径**。为了确保递归查询在到达最终节点后立即停止，我们使用一个窗口函数来检查终端节点是否在新添加的节点中。

以下查询返回节点1（起始节点）和节点8（结束节点）之间的所有未加权最短路径：

```
%%sql
CREATE TABLE bigquant_edge(node1id int, node2id int);
INSERT INTO bigquant_edge VALUES (1, 3), (1, 5), (2, 4), (2, 5), (2, 10), (3, 1), (3, 5),
    (3, 8), (3, 10), (5, 3), (5, 4), (5, 8), (6, 3), (6, 4), (7, 4), (8, 1), (9, 4);

WITH RECURSIVE paths(startNode, endNode, path, endReached) AS (
    SELECT -- define the path as the first edge of the traversal
        node1id AS startNode,
        node2id AS endNode,
        [node1id, node2id] AS path,
        (node2id = 8) AS endReached
        FROM bigquant_edge
        WHERE startNode = 1
    UNION ALL
    SELECT -- concatenate new edge to the path
        paths.startNode AS startNode,
        node2id AS endNode,
        array_append(path, node2id) AS path,
        max(CASE WHEN node2id = 8 THEN 1 ELSE 0 END)
            OVER (ROWS BETWEEN UNBOUNDED PRECEDING
                    AND UNBOUNDED FOLLOWING) AS endReached
        FROM paths
        JOIN bigquant_edge ON paths.endNode = node1id
        WHERE NOT EXISTS (SELECT 1
                    FROM paths previous_paths
                    WHERE list_contains(previous_paths.path, node2id))
        AND paths.endReached = 0
)
SELECT startNode, endNode, path
FROM paths
WHERE endNode = 8
ORDER BY length(path), path;
```

```
┌───────────┬─────────┬───────────┐
│ startNode │ endNode │   path    │
├───────────┼─────────┼───────────┤
│ 1         │ 8       │ [1, 3, 8] │
│ 1         │ 8       │ [1, 5, 8] │
└───────────┴─────────┴───────────┘
```

##### window
`WINDOW`子句允许您指定可在窗口函数中使用的命名窗口。当您有多个窗口函数时，这些命名窗口就很有用，因为它们让您避免重复相同的窗口子句。

##### qualify
`QUALIFY`子句用于筛选[窗口函数](https://bigquant.com/wiki/doc/dai-PLSbc1SbZX#h-%E7%AA%97%E5%8F%A3%E5%87%BD%E6%95%B0)。过滤结果跟应用于[GROUP BY子句](https://bigquant.com/wiki/doc/dai-PLSbc1SbZX#h-group-by)的[HAVING子句](https://bigquant.com/wiki/doc/dai-PLSbc1SbZX#h-having)类似。

`QUALIFY`子句避免了使用子查询或[WITH子句](https://bigquant.com/wiki/doc/dai-PLSbc1SbZX#h-with)来执行此筛选的需要（与`HAVING`避免子查询类似）。下面有一个使用`WITH`子句而不是`QUALIFY`的示例。

请注意，这是基于[窗口函数](https://bigquant.com/wiki/doc/dai-PLSbc1SbZX#h-%E7%AA%97%E5%8F%A3%E5%87%BD%E6%95%B0)进行筛选，而不一定是基于[WINDOW子句](https://bigquant.com/wiki/doc/dai-PLSbc1SbZX#h-window)。`WINDOW`子句可用于简化多个`WINDOW`函数表达式的创建，但不是必需的。

指定`QUALIFY`子句的位置是在`SELECT`语句中的[WINDOW子句](https://bigquant.com/wiki/doc/dai-PLSbc1SbZX#h-window)之后（`WINDOW`也可以不指定），并且在[ORDER BY](https://bigquant.com/wiki/doc/dai-PLSbc1SbZX#h-order-by)之前。

- **例子**

以下每个示例生成的输出都是相同的：

```
%%sql
/*编写威廉R(W&R指标), 定位指标值大于80的个股(超卖状态)*/
SELECT date, instrument, 
(MAX(high) OVER (PARTITION BY instrument ORDER BY date ROWS 5 PRECEDING) - close) / 
(MAX(high) OVER (PARTITION BY instrument ORDER BY date ROWS 5 PRECEDING) - MIN(low) OVER (PARTITION BY instrument ORDER BY date ROWS 5 PRECEDING)) * 100 WR
FROM cn_stock_bar1d
WHERE date > '2023-01-01'
QUALIFY WR > 80;

/*将分窗函数放入WINDOW语句中*/
SELECT date, instrument, 
100 * (MAX(high) OVER my_win - close) / (MAX(high) OVER my_win - MIN(low) OVER my_win) WR
FROM cn_stock_bar1d
WHERE date > '2023-01-01'
WINDOW
my_win AS (PARTITION BY instrument ORDER BY date ROWS 5 PRECEDING)
QUALIFY WR > 80;

/*将窗口函数放入WITH语句中, 此时再查询WITH语句中的表格时不需要用QUALIFY*/
WITH t1 AS (
    SELECT date, instrument, 
    (MAX(high) OVER my_win -close) / (MAX(high) OVER my_win - MIN(low) OVER my_win) * 100 WR
    FROM cn_stock_bar1d
    WHERE date > '2023-01-01'
    WINDOW
        my_win AS (PARTITION BY instrument ORDER BY date ROWS 5 PRECEDING)
)

SELECT * FROM t1 
WHERE WR > 80;
```

| date | instrument | WR |
|---|---|---|
| 2023-01-19 | 000025.SZ | 93.08755760368672 |
| 2023-02-15 | 000025.SZ | 83.14606741573056 |
| …… | …… | …… |
| 2023-07-17 | 002435.SZ | 88.88888888888879 |

##### values
`VALUES`子句用于指定固定的行数。`VALUES`子句可用作独立语句或`FROM`子句的一部分。

- **例子**

```
%%sql
/*产生一张两行两列的表, 并直接返回他们*/
VALUES ('bigquant', 1), ('othes', 2);

/*生成两行两列的表, 并给列赋予列名*/
SELECT * FROM (VALUES ('bigquant', 1), ('othes', 2)) Cities(Name, Id);

/*用value子句生成的表创建一个新表*/
CREATE TABLE Cities AS SELECT * FROM (VALUES ('bigquant', 1), ('othes', 2)) Cities(Name, Id);
```

##### filter
`FILTER`子句可以选择性地跟在在`SELECT`语句中的聚合函数后面。这样可以筛选聚合函数处理的数据行，其方式与`WHERE`子句筛选行的方式相同。当聚合函数在窗口中使用时，目前`FILTER`还不能使用。

`FILTER`在很多情况下都非常有用，比如使用不同过滤条件计算多个聚合时，以及创建数据透视图时。与下面讨论的更传统的`CASE WHEN`方法相比，`FILTER`为透视数据提供了更简洁的语法。

某些聚合函数不会筛选出`NULL`值，因此使用`FILTER`子句可以返回有效的结果，而`CASE WHEN`方法有时则不能。比如`FIRST`和`LAST`函数在非聚合的透视操作中使用时。`FILTER` 还改进了使用`LIST`和`ARRAY_AGG`函数时的`NULL`值处理，因为`CASE WHEN`方法会在列表结果中包含`NULL`值，而`FILTER`子句则会删除它们。

- **例子**

```
%%sql
/*统计2023年1月5日, 2023年1月6日这两天有多少只股票在交易, 并统计1月6日当天一字涨停或跌停的股票数量*/
SELECT COUNT(*) FILTER (WHERE date = '2023-01-05') trading_stock_1,
COUNT(*) FILTER (WHERE date = '2023-01-06') trading_stock_2, 
COUNT(*) FILTER (WHERE high = low AND date = '2023-01-06') count_1
FROM cn_stock_bar1d;
```

| trading_stock_1 | trading_stock_2 | count_1 |
|---|---|---|
| 5067 | 5068 | 5 |

```
%%sql
/*统计2023年1月5日, 2023年1月6日这两天平均换手率, 并统计1月6日当天剔除一字涨停或跌停的股票后平均换手率*/
SELECT AVG(turn) FILTER (WHERE date = '2023-01-05') trading_turn_1,
AVG(turn) FILTER (WHERE date = '2023-01-06') trading_turn_2, 
AVG(turn) FILTER (WHERE high != low AND date = '2023-01-06') count_turn_1
FROM cn_stock_bar1d;
```

| trading_turn_1 | trading_turn_2 | count_turn_1 |
|---|---|---|
| 0.025115489605260284 | 0.02556454240905246 | 0.025607455009196516 |

`FILTER`子句还可用于将数据从行透视到列中。这是一种静态透视，因为在SQL中列必须在运行时之前定义。

```
%%sql
CREATE TEMP TABLE bigquant_data as 
    SELECT 
        i,
        CASE WHEN i <= rows * 0.25 THEN 2022 
             WHEN i <= rows * 0.5 THEN 2023 
             WHEN i <= rows * 0.75 THEN 2024 
             WHEN i <= rows * 0.875 THEN 2025
             ELSE NULL 
             END as year 
    FROM (
        SELECT 
            i, 
            count(*) over () as rows 
        FROM generate_series(1,10000) tbl(i)
    ) tbl;

/*统计每年的数据量*/
SELECT
    count(i) FILTER (WHERE year = 2022) as "2022",
    count(i) FILTER (WHERE year = 2023) as "2023",
    count(i) FILTER (WHERE year = 2024) as "2024",
    count(i) FILTER (WHERE year = 2025) as "2025",
    count(i) FILTER (WHERE year IS NULL) as "NULLs"
FROM bigquant_data;

/*语法不同但结果一致*/
SELECT
    count(CASE WHEN year = 2022 THEN i END) as "2022",
    count(CASE WHEN year = 2023 THEN i END) as "2023",
    count(CASE WHEN year = 2024 THEN i END) as "2024",
    count(CASE WHEN year = 2025 THEN i END) as "2025",
    count(CASE WHEN year IS NULL THEN i END) as "NULLs"
FROM bigquant_data;
```

| 2022 | 2023 | 2024 | 2025 | NULLs |
|---|---|---|---|---|
| 2500 | 2500 | 2500 | 1250 | 1250 |

当使用不忽略`NULL`值的聚合函数时，`CASE WHEN`方法将无法按预期工作。上面已经谈到，`FIRST`函数就属于此类别，因此`FILTER`在这种情况下是首选。

```
%%sql
CREATE TEMP TABLE bigquant_data as 
    SELECT 
        i,
        CASE WHEN i <= rows * 0.25 THEN 2022 
             WHEN i <= rows * 0.5 THEN 2023 
             WHEN i <= rows * 0.75 THEN 2024 
             WHEN i <= rows * 0.875 THEN 2025
             ELSE NULL 
             END as year 
    FROM (
        SELECT 
            i, 
            count(*) over () as rows 
        FROM generate_series(1,10000) tbl(i)
    ) tbl;

SELECT
    first(i) FILTER (WHERE year = 2022) as "2022",
    first(i) FILTER (WHERE year = 2023) as "2023",
    first(i) FILTER (WHERE year = 2024) as "2024",
    first(i) FILTER (WHERE year = 2025) as "2025",
    first(i) FILTER (WHERE year IS NULL) as "NULLs"
FROM bigquant_data;
```

| 2022 | 2023 | 2024 | 2025 | NULLs |
|---|---|---|---|---|
| 1 | 2501 | 5001 | 7501 | 8751 |

```
%%sql
/*每当CASE WHEN子句的第一个计算返回NULL时, 将生成NULL值*/
CREATE TEMP TABLE bigquant_data as 
    SELECT 
        i,
        CASE WHEN i <= rows * 0.25 THEN 2022 
             WHEN i <= rows * 0.5 THEN 2023 
             WHEN i <= rows * 0.75 THEN 2024 
             WHEN i <= rows * 0.875 THEN 2025
             ELSE NULL 
             END as year 
    FROM (
        SELECT 
            i, 
            count(*) over () as rows 
        FROM generate_series(1,10000) tbl(i)
    ) tbl;

SELECT
    first(CASE WHEN year = 2022 THEN i END) as "2022",
    first(CASE WHEN year = 2023 THEN i END) as "2023",
    first(CASE WHEN year = 2024 THEN i END) as "2024",
    first(CASE WHEN year = 2025 THEN i END) as "2025",
    first(CASE WHEN year IS NULL THEN i END) as "NULLs"
FROM bigquant_data;
```

| 2022 | 2023 | 2024 | 2025 | NULLs |
|---|---|---|---|---|
| 1 | NULL | NULL | NULL | NULL |

##### 集合操作
集合操作指的是`UNION [ALL]`，`INTERSECT`和`EXCEPT`子句。

传统的集合操作**按列位置**统一查询，并要求要组合的查询具有相同数量的输入列。如果列的类型不同，则可以添加强制转换。结果将使用第一个查询中的列名。

DAI也支持`UNION BY NAME`，它按名称而不是按位置连接列。`UNION BY NAME`不要求输入具有相同数量的列。如果缺少列，将添加`NULL`值。

- **例子**

```
%%sql
/*拼接两个区间的数据, 分别是从0到9的所有整数和0到4的所有整数*/
SELECT * FROM range(10) bigquant_t1 UNION ALL SELECT * FROM range(5) bigquant_t2;

/*在上一个结果的基础上剔除缺失值*/
SELECT * FROM range(10) bigquant_t1 UNION SELECT * FROM range(5) bigquant_t2;

/*在之前的两个数据集基础上取交集*/
SELECT * FROM range(10) bigquant_t1 INTERSECT SELECT * FROM range(5) bigquant_t2;

/*在之前的两个数据集上用大的区间集合与小的区间集合取差集(从大集合剔除小集合中的元素)*/
SELECT * FROM range(10) bigquant_t1  EXCEPT SELECT * FROM range(5) bigquant_t2;

/*连接两个子表, 缺少列值用NULL填充*/
SELECT 24 AS id UNION ALL BY NAME SELECT 'bigquant' as Company;
```

- **示例表**

```
%%sql
CREATE TABLE bigquant_capitals_table(city VARCHAR, country VARCHAR);
INSERT INTO bigquant_capitals_table VALUES ('Amsterdam', 'NL'), ('Berlin', 'Germany');

CREATE TABLE bigquant_weather_table(city VARCHAR, degrees INTEGER, date DATE);
INSERT INTO bigquant_weather_table VALUES ('Amsterdam', 10, '2022-10-14'), ('Seattle', 8, '2022-10-12');
```

- **UNION (ALL)**

`UNION`子句可用于合并来自多个查询的行。查询必须具有相同数量的列和相同的列类型。

`UNION`子句默认执行重复消除，结果中仅包含唯一行。

`UNION ALL`则返回两个查询的所有行，而不进行重复消除。

```
%%sql
CREATE TABLE bigquant_capitals_table(city VARCHAR, country VARCHAR);
INSERT INTO bigquant_capitals_table VALUES ('Amsterdam', 'NL'), ('Berlin', 'Germany');
CREATE TABLE bigquant_weather_table(city VARCHAR, degrees INTEGER, date DATE);
INSERT INTO bigquant_weather_table VALUES ('Amsterdam', 10, '2022-10-14'), ('Seattle', 8, '2022-10-12');

SELECT city FROM bigquant_capitals_table UNION SELECT city FROM bigquant_weather_table;
-- 返回结果: Amsterdam, Berlin, Seattle

SELECT city FROM bigquant_capitals_table UNION ALL SELECT city FROM bigquant_weather_table;
-- 返回结果: Amsterdam, Amsterdam, Berlin, Seattle
```

- **INTERSECT**

`INTERSECT`子句可用于选择在两个查询的结果中都出现的所有行。`INTERSECT`会执行重复消除，仅返回唯一行。

```
%%sql
CREATE TABLE bigquant_capitals_table(city VARCHAR, country VARCHAR);
INSERT INTO bigquant_capitals_table VALUES ('Amsterdam', 'NL'), ('Berlin', 'Germany');
CREATE TABLE bigquant_weather_table(city VARCHAR, degrees INTEGER, date DATE);
INSERT INTO bigquant_weather_table VALUES ('Amsterdam', 10, '2022-10-14'), ('Seattle', 8, '2022-10-12');

SELECT city FROM bigquant_capitals_table INTERSECT SELECT city FROM bigquant_weather_table;
-- 返回结果: Amsterdam
```

- **EXCEPT**

`EXCEPT`子句可用于选择仅在左侧查询中出现的所有行。`EXCEPT`会执行重复消除，仅返回唯一行。

```
%%sql
CREATE TABLE bigquant_capitals_table(city VARCHAR, country VARCHAR);
INSERT INTO bigquant_capitals_table VALUES ('Amsterdam', 'NL'), ('Berlin', 'Germany');
CREATE TABLE bigquant_weather_table(city VARCHAR, degrees INTEGER, date DATE);
INSERT INTO bigquant_weather_table VALUES ('Amsterdam', 10, '2022-10-14'), ('Seattle', 8, '2022-10-12');

SELECT city FROM bigquant_capitals_table EXCEPT SELECT city FROM bigquant_weather_table;
-- 返回结果: Berlin
```

- **UNION (ALL) BY NAME**

`UNION (ALL) BY NAME`子句可用于按名称（而不是按位置）合并不同表中的行。`UNION BY NAME`不要求两个查询具有相同的列数。仅存在于在其中一个查询中的任何列在另一个查询中都将被填充为`NULL`值。

```
%%sql
CREATE TABLE bigquant_capitals_table(city VARCHAR, country VARCHAR);
INSERT INTO bigquant_capitals_table VALUES ('Amsterdam', 'NL'), ('Berlin', 'Germany');
CREATE TABLE bigquant_weather_table(city VARCHAR, degrees INTEGER, date DATE);
INSERT INTO bigquant_weather_table VALUES ('Amsterdam', 10, '2022-10-14'), ('Seattle', 8, '2022-10-12');

SELECT * FROM capitals UNION BY NAME SELECT * FROM weather;
```

```
┌───────────┬─────────┬─────────┬────────────┐
│   city    │ country │ degrees │    date    │
│  varchar  │ varchar │  int32  │    date    │
├───────────┼─────────┼─────────┼────────────┤
│ Amsterdam │ NULL    │      10 │ 2022-10-14 │
│ Seattle   │ NULL    │       8 │ 2022-10-12 │
│ Amsterdam │ NL      │    NULL │ NULL       │
│ Berlin    │ Germany │    NULL │ NULL       │
└───────────┴─────────┴─────────┴────────────┘
```

`UNION BY NAME`执行重复消除，而`UNION ALL BY NAME`不执行。

#### 数据类型
- **通用数据类型**

下表显示了所有内置的通用数据类型。别名列中列出的替代项也可用于引用这些类型，但请注意，别名不是标准SQL的一部分，因此可能不被其他数据库引擎接受。

| 名称 | 别名 | 描述 |
|---|---|---|
| `BIGINT` | `INT8`, `LONG` | 有符号八字节整数 |
| `BIT` | `BITSTRING` | 1 和 0 的字符串 |
| `BOOLEAN` | `BOOL`, `LOGICAL` | 逻辑布尔值 (true/false) |
| `BLOB` | `BYTEA`, `BINARY,` `VARBINARY` | 可变长度二进制数据 |
| `DATE` |  | 日历日期（年、月、日） |
| `DOUBLE` | `FLOAT8`, `NUMERIC`, `DECIMAL` | 双精度浮点数（8 字节） |
| `DECIMAL(s, p)` |  | 具有给定小数位数和精度的固定精度浮点数 |
| `HUGEINT` |  | 有符号 16 字节整数 |
| `INTEGER` | `INT4`, `INT`, `SIGNED` | 有符号四字节整数 |
| `INTERVAL` |  | 日期/时间增量 |
| `REAL` | `FLOAT4`, `FLOAT` | 单精度浮点数（4 字节） |
| `SMALLINT` | `INT2`, `SHORT` | 有符号双字节整数 |
| `TIME` |  | 一天中的时间（无时区） |
| `TIMESTAMP` | `DATETIME` | 时间和日期的组合 |
| `TIMESTAMP WITH TIME ZONE` | `TIMESTAMPTZ` | 使用当前时区的时间和日期的组合 |
| `TINYINT` | `INT1` | 有符号单字节整数 |
| `UBIGINT` |  | 无符号八字节整数 |
| `UINTEGER` |  | 无符号四字节整数 |
| `USMALLINT` |  | 无符号双字节整数 |
| `UTINYINT` |  | 无符号单字节整数 |
| `UUID` |  | UUID 数据类型 |
| `VARCHAR` | `CHAR`, `BPCHAR`, `TEXT`, `STRING` | 可变长度字符串 |

- **嵌套/复合类型**

DAI支持三种嵌套数据类型：`LIST`、`STRUCT`和`MAP`。每种类型都有不同的用法，并具有不同的结构。

| 名称 | 描述 | 在列中的使用规则 | 从值构建 | DDL/CREATE中的定义方式 |
|---|---|---|---|---|
| [LIST](https://bigquant.com/wiki/doc/list-udNuqzEiAO) | 相同类型的数据值的有序序列 | 每个 LIST 中的每一行必须具有相同的数据类型，但可以包含任意数量的元素 | [1, 2, 3] | INT[ ] |
| [STRUCT](https://bigquant.com/wiki/doc/struct-KZjPCI7ZdY) | 包含多个命名值的字典，其中每个键都是一个字符串，但每个键的值可以是不同的类型 | 每行必须具有相同的键 | {'i': 42, 'j': 'a'} | STRUCT(i INT, j VARCHAR) |
| [MAP](https://bigquant.com/wiki/doc/map-7HRchKvErS) | 包含多个命名值的字典，每个键具有相同的类型，每个值具有相同的类型。键和值可以是任何类型，也可以是彼此不同的类型 | 行可以具有不同的键。 | map([1,2],['a','b']) | MAP(INT, VARCHAR) |

- **嵌套**

`LIST`，`STRUCT`和`MAP`可以任意嵌套到任意深度，只要遵守类型规则即可。

```
%%sql
/*struct嵌套list*/
SELECT {'birds': ['duck', 'goose', 'heron'], 'aliens': NULL, 'amphibians': ['frog', 'toad']};

/*struct嵌套list, 列表中嵌套map*/
SELECT {'bigquant_table': [map([1, 5], [42.1, 45]), map([1, 5], [42.1, 45])]};
```

##### NULL
`NULL`值是用于表示 SQL 中缺失数据的特殊值。任何类型的列都可以包含`NULL`值。

```
%%sql
/*往表中插入NULL*/
CREATE TABLE bigquant_table(i INTEGER);
INSERT INTO bigquant_table VALUES (NULL);

SELECT * FROM bigquant_table;
-- 返回一张只包含NULL的表
```

`NULL`值在查询的许多部分以及许多函数中具有特殊的语义：

> 任何与NULL值的比较都会返回NULL，包括NULL=NULL。

您可以使用`IS NOT DISTINCT FROM`执行相等比较，其中`NULL`值彼此相等。`IS (NOT) NULL`用于检查值是否为`NULL`。

```
%%sql
SELECT NULL=NULL;
-- 返回NULL

SELECT NULL IS NOT DISTINCT FROM NULL;
-- 返回true
SELECT NULL IS NULL;

-- 返回true
```

- **NULL和函数**

如果函数以`NULL`作为输入参数，其**通常**会返回`NULL`。

```
%%sql
SELECT COS(NULL);
-- NULL
```

`COALESCE`是一个例外。`COALESCE`接受任意数量的参数，并为每一行返回第一个不是`NULL`的参数。如果所有参数都是`NULL`，则`COALESCE`也返回`NULL`。

```
%%sql
SELECT COALESCE(NULL, NULL, 1);
-- 1

SELECT COALESCE(10, 20);
-- 10

SELECT COALESCE(NULL, NULL);
-- NULL
```

- **NULL和连接词**

`NULL`值在`AND`/`OR`连词中具有特殊的语义。有关三元逻辑真值表，请参阅[Boolean文档](https://bigquant.com/wiki/doc/dai-PLSbc1SbZX#h-boolean)。

- **NULL和聚合函数**

`NULL`在大多数聚合函数中是被忽略的值。

不忽略`NULL`值的聚合函数包括：`FIRST`、`LAST`、`LIST`和`ARRAY_AGG`。若要从这些聚合函数中排除`NULL`值，可以使用[FILTER子句](https://bigquant.com/wiki/doc/dai-PLSbc1SbZX#h-filter)。

```
%%sql
CREATE TABLE bigquant_table(i INTEGER);
INSERT INTO bigquant_table VALUES (1), (10), (NULL);

SELECT MIN(i) FROM bigquant_table;
-- 1

SELECT MAX(i) FROM bigquant_table;
-- 10
```

##### boolean
| 名称 | 别名 | 描述 |
|---|---|---|
| `BOOLEAN` | bool | 逻辑布尔值 (true/false) |

`BOOLEAN`类型表示真值陈述（“true”或“false”）。在 SQL 中，布尔字段还可以具有第三个状态“unknown”，该状态由 SQL `NULL`值表示。

```
%%sql
/*bool类型的三个状态*/
SELECT TRUE, FALSE, NULL::BOOLEAN;
-- 依次返回true, false, NULL
```

可以使用字面上的`TRUE`和`FALSE`显式地创建布尔值。但是，它们通常是在比较或连词中创建的。比如`i > 10`的结果为布尔值。布尔值可用于 SQL 语句的`WHERE`和`HAVING`子句，以从结果中筛选出元组。在这种情况下，谓词计算结果为`TRUE`的元组将通过筛选器，谓词计算结果为`FALSE`或`NULL`的元组将被筛选掉。请参考以下示例：

```
%%sql
/*创建一个包含5, 15, NULL三个值的表格*/
CREATE TABLE bigquant_table(i INTEGER);
INSERT INTO bigquant_table VALUES (5), (15), (NULL);

/*查询所有值大于10的行, NULL会被过滤掉*/
SELECT * FROM bigquant_table WHERE i > 10;
```

- **连词**

`AND`/`OR`连词可用于组合布尔值。

下面是`x AND y`的真值表。

| X | X AND TRUE | X AND FALSE | X AND NULL |
|---|---|---|---|
| TRUE | TRUE | FALSE | NULL |
| FALSE | FALSE | FALSE | FALSE |
| NULL | NULL | FALSE | NULL |

下面是`x OR y`的真值表。

| X | X OR TRUE | X OR FALSE | X OR NULL |
|---|---|---|---|
| TRUE | TRUE | TRUE | TRUE |
| FALSE | TRUE | FALSE | NULL |
| NULL | TRUE | NULL | NULL |

- **表达式**

请参阅[逻辑表达式](https://bigquant.com/wiki/doc/dai-PLSbc1SbZX#h-%E9%80%BB%E8%BE%91%E8%A1%A8%E8%BE%BE%E5%BC%8F)和[比较表达式](https://bigquant.com/wiki/doc/dai-PLSbc1SbZX#h-%E6%AF%94%E8%BE%83%E8%A1%A8%E8%BE%BE%E5%BC%8F)。

##### enum
| 名称 | 描述 |
|---|---|
| ENUM | 字典编码，表示列的所有可能的字符串值 |

- **枚举**

`ENUM`类型表示具有列的所有可能的唯一值的字典数据结构。比如，存储星期几的列可以是包含所有可能日期的枚举。枚举对于具有高基数的字符串列尤其有用。这是因为该列仅在`ENUM`字典中存储对字符串的数字引用，从而大大节省了存储空间并提高了查询性能。

- **枚举定义**

`ENUM`类型是从一组硬编码的值或从返回varchar单列的`SELECT`语句中创建的。`SELECT`语句中的值集将被删除重复数据，但如果枚举是从硬编码集创建的，则可能没有任何重复项。

```
-- Create enum using hardcoded values
CREATE TYPE ${enum_name} AS ENUM ([${value_1},${value_2},...])

-- Create enum using a select statement that returns a single column of varchars
CREATE TYPE ${enum_name} AS ENUM (${SELECT expression})
```

例如:

```
%%sql
/*创建一个名为mood的枚举*/
CREATE TYPE mood AS ENUM ('sad', 'ok', 'happy');

/*由于之前存在了名为mood的枚举, 所以这里会报错*/
CREATE TYPE mood AS ENUM ('sad', 'ok', 'happy', 'anxious');

/*枚举对象不能存在NULL值*/
CREATE TYPE breed AS ENUM ('maltese', NULL);

/*这里会报错, 因为枚举对象不能存在重复值*/
CREATE TYPE breed AS ENUM ('maltese', 'maltese');

/*从查询语句中创建一个枚举对象*/
CREATE TABLE bigquant_inputs AS 
    SELECT 'duck'  AS my_varchar UNION ALL
    SELECT 'duck'  AS my_varchar UNION ALL
    SELECT 'goose' AS my_varchar;

-- 这里会自动删除重复值
CREATE TYPE birds AS ENUM (SELECT my_varchar FROM bigquant_inputs);

-- 使用enum_range函数显示鸟类枚举中的可用值
SELECT enum_range(NULL::birds) AS my_enum_range;
```

| my_enum_range |
|---|
| [duck, goose] |

- **枚举用法**

创建枚举后，可以在任何使用标准内置类型的地方使用它。例如，我们可以创建一个表，其中包含引用枚举的列。

```
%%sql
/*创建一个枚举*/
CREATE TYPE mood AS ENUM ('sad', 'ok', 'happy');

-- 创建一个表格, 其中name为字符, current_mood引用了mood枚举
CREATE TABLE bigquant_person (
    name text,
    current_mood mood
);

-- 从这个表格中插入数据
INSERT INTO bigquant_person VALUES ('Pedro','happy'), ('Mark', NULL), ('Pagliacci', 'sad'), ('Mr. Mackey', 'ok');

/*由于枚举中不存在quackity-quack, 所以抛出错误异常*/
INSERT INTO bigquant_person VALUES ('Hannes','quackity-quack');

-- 'sad' 在这里是mood枚举类型, 不是字符型
SELECT * FROM bigquant_person WHERE current_mood = 'sad';
-- 返回结果Pagliacci

/*从外部导入数据并创建枚举*/
CREATE TYPE mood AS ENUM (SELECT mood FROM 'path/to/file.csv');

-- 之后便可以创建一个包含枚举的表, 并从外部导入数据
CREATE TABLE bigquant_person_2 (name text, current_mood mood);
COPY bigquant_person_2 FROM 'path/to/file.csv' (AUTO_DETECT TRUE);
```

- **枚举与字符串**

枚举会在必要时自动强制转换为`VARCHAR`类型。此特征允许在任何`VARCHAR`函数中使用`ENUM`列。此外，它还允许在不同`ENUM`列之间或者`ENUM`和`VARCHAR`列之间进行比较。

例如:

```
%%sql
/*创建一个枚举*/
CREATE TYPE mood AS ENUM ('sad', 'ok', 'happy');

-- 创建一个表格, 其中name为字符, current_mood引用了mood枚举
CREATE TABLE bigquant_person (
    name text,
    current_mood mood
);

-- 从这个表格中插入数据
INSERT INTO bigquant_person VALUES ('Pedro','happy'), ('Mark', NULL), ('Pagliacci', 'sad'), ('Mr. Mackey', 'ok');

-- 使用regexp_matches函数将current_mood字段的值转化为字符型数据
SELECT regexp_matches(current_mood, '.*a.*') FROM person;
-- 返回结果: TRUE、NULL、 TRUE、FALSE

/*接下来建立一个新的枚举*/
CREATE TYPE new_mood AS ENUM ('happy', 'anxious');

CREATE TABLE bigquant_person_2(
    name text,
    current_mood mood,
    future_mood new_mood,
    past_mood VARCHAR
);

INSERT INTO bigquant_person_2 VALUES ('Pedro','happy', 'happy', 'ok'), ('Mark', NULL, 'anxious', 'sad'), ('Pagliacci', 'sad', 'anxious', 'sad'), ('Mr. Mackey', 'ok', 'anxious', 'anxious');

-- 即便是两个不一样的枚举, 在做判断的时候依旧转化成字符型作判断
SELECT * FROM bigquant_person_2 WHERE current_mood = future_mood;

SELECT * FROM bigquant_person_2 WHERE current_mood = past_mood;
```

- **枚举删除**

枚举类型存储在目录中，并将目录依赖项添加到使用它们的每个表中。可以使用以下命令从目录中删除枚举：

```
DROP TYPE ${enum_name}
```

注意，在删除枚举之前必须删除任何依赖项，或者使用`CASCADE`参数。

例如:

```
%%sql
/*创建一个枚举*/
CREATE TYPE mood AS ENUM ('sad', 'ok', 'happy');

-- 创建一个表格, 其中name为字符, current_mood引用了mood枚举
CREATE TABLE bigquant_person (
    name text,
    current_mood mood
);
DROP TYPE mood   -- 这样是会报错的, 因为在创建表格bigquant_person时用到了这个枚举

DROP TABLE bigquant_person;  -- 所以在删除枚举之前, 需要删除之前包含枚举的表格

DROP TYPE mood; -- 最终删除成功
```

##### numeric
- **整数类型**

`TINYINT`、`SMALLINT`、`INTEGER`、`BIGINT`和`HUGEINT`类型存储各种范围的整数，即没有小数部分的数字。尝试存储超过存储范围的值将发生错误。类型`UTINYINT`、`USMALLINT`、`UINTEGER`、`UBIGINT`存储完整的无符号数字。尝试将存储负数或超过存储范围的值将发生错误。

| 名称 | 别名 | 最小值 | 最大值 |
|---|---|---|---|
| `TINYINT` | `INT1` | -128 | 127 |
| `SMALLINT` | `INT2`, `SHORT` | -32768 | 32767 |
| `INTEGER` | `INT4`, `INT`, `SIGNED` | -2147483648 | 2147483647 |
| `BIGINT` | `INT8`, `LONG` | -9223372036854775808 | 9223372036854775807 |
| `HUGEINT` |  | -170141183460469231731687303715884105727* | 170141183460469231731687303715884105727 |
| `UTINYINT` | - | 0 | 255 |
| `USMALLINT` | - | 0 | 65535 |
| `UINTEGER` | - | 0 | 4294967295 |
| `UBIGINT` | - | 0 | 18446744073709551615 |

整数类型是常见的类型，因为它在范围、存储大小和性能之间提供了最佳平衡。`SMALLINT`类型通常仅在存储空间非常宝贵时才使用。`BIGINT`和`HUGEINT`类型为在整数类型的范围不足时设计。

比如-170141183460469231731687303715884105728 （-1 « 127）不能用内部结构表示。

- **定点小数**

数据类型`DECIMAL(WIDTH,SCALE)`表示精确的定点十进制值。创建`DECIMAL`类型的值时，可以指定`WIDTH`和`SCALE`来定义字段中可以保存的十进制值的大小。`WIDTH`字段确定可以保存多少位数，`scale`确定小数点后的位数。例如，类型`DECIMAL(3,2)`可以拟合值`1.23`，但不能拟合值`12.3`或值`1.234`。默认的`WIDTH`和`SCALE`为`DECIMAL(18,3)`。

在内部，小数根据其指定的宽度表示为整数。

| 宽度 | 内部 | 大小 (字节) |
|---|---|---|
| 1-4 | `INT16` | 2 |
| 5-9 | `INT32` | 4 |
| 10-18 | `INT64` | 8 |
| 19-38 | `INT128` | 16 |

使用太大的`DECIMAL`可能会影响性能。特别是宽度大于 19 的十进制值非常慢，因为涉及`INT128`类型的算术比涉及`INT32`或者`INT64`类型的操作要耗时得多。建议坚持宽度为`18`或以下，除非有充分的理由说明这是不够的。

- **浮点类型**

数据类型`REAL`和`DOUBLE`的精度是不精确的，也被称作可变精度数值类型。这些类型通常是二进制浮点运算（分别为单精度和双精度）的**IEEE 754标准**的实现。

| 名称 | 别名 | 描述 |
|---|---|---|
| `REAL` | `FLOAT4`, `FLOAT` | 单精度浮点数（4 字节） |
| `DOUBLE` | `FLOAT8` | 双精度浮点数（8 字节） |

不精确意味着某些值无法精确转换为内部格式，而是存储为近似值，因此存储和检索值可能会显示细微差异。管理这些错误以及它们如何通过计算传播是数学和计算机科学的一整个分支主题，这里不做讨论。除了以下几点外：

- 如果需要精确的存储和计算（例如货币金额），请改用数值类型。
- 如果要对这些类型进行复杂的计算，尤其是在边界情况下（无穷大、下溢）时，则应仔细评估实现。
- 比较两个浮点值的相等性也并不总是符合预期。

在大多数平台上，`REAL`类型的范围为 1E-37 到 1E+37，精度至少为 6 位。`DOUBLE`类型通常具有大约从 1E-307 到 1E+308 的范围，精度至少为 15 位。值过大或过小都会引发错误。如果输入数字的精度太高，则可能会进行舍入。太接近零且无法表示为与零不同的数字将导致下溢错误。

除了普通数值之外，浮点类型还具有几个特殊值：

`Infinity` `-Infinity` `NaN`

这些分别表示 IEEE 754 的几个特殊值“无穷大”、“负无穷大”和“非数字”。（在不遵循 IEEE 754 浮点运算的计算机上，这些值也会有些问题）在 SQL 命令中将这些值作为常量写入时，必须在它们两边加上引号，例如：`UPDATE table SET x = '-Infinity'`。在输入时，这些字符串以不区分大小写的方式识别。

##### text
| 名称 | 别名 | 描述 |
|---|---|---|
| `VARCHAR` | `CHAR`, `BPCHAR`, `TEXT`, `STRING` | 可变长度字符串 |
| `VARCHAR(n)` |  | 最大长度为 n 的可变长度字符串 |

通过`VARCHAR(n)`这种形式提供一个数字和类型可以进行初始化，其中`n`是一个正整数。**注意，指定长度不是必需的，对系统也没有什么影响。指定此长度不会提高性能或减少数据库中字符串的存储空间**。出于与需要为字符串指定长度的其他系统的兼容性原因，支持了此种用法。

如果出于数据完整性原因希望限制`VARCHAR`列中的字符数，则应使用`CHECK`约束，如下：

```
%%sql
CREATE TABLE strings(
	val VARCHAR CHECK(LENGTH(val) <= 10) -- val字段只能存储长度不大于10的字符型数据
);
```

`VARCHAR`字段允许存储 unicode 字符。在内部，数据会被编码为 UTF-8。

##### date
| 名称 | 别名 | 描述 |
|---|---|---|
| `DATE` |  | 日历日期（年、月、日） |

`DATE`类型是年、月和日的组合。可以使用`DATE`关键字创建日期，其中数据必须根据 ISO 8601 格式（`YYYY-MM-DD`）进行格式化。

```
%%sql
SELECT DATE '1992-09-20';
```

- **特殊值**

有三个特殊的日期值可用于输入：

| 输入字符串 | 描述 |
|---|---|
| epoch | 1970-01-01 (Unix系统零日) |
| infinity | 晚于所有其他日期 |
| -infinity | 早于所有其他日期 |

`infinity`和`-infinity`值是系统内的特定表达，显示不会有什么变化; 但`epoch`只是一个符号速记，在读取时将转换为日期值。

```
%%sql
SELECT '-infinity'::DATE, 'epoch'::DATE, 'infinity'::DATE;
```

| Negative | Epoch | Positive |
|---|---|---|
| -infinity | 1970-01-01 | infinity |

##### timestamp
时间戳表示绝对时间中的点，通常称为时刻。DAI将时刻表示为自`1970-01-01 00:00:00+00`以来的微秒数（μs）。

| 名称 | 别名 | 描述 |
|---|---|---|
| `TIMESTAMP` | datetime | 时间和日期的组合（忽略时区） |
| `TIMESTAMP WITH TIME ZONE` | `TIMESTAMPTZ` | 时间和日期的组合（使用时区） |

时间戳表示`DATE`（年、月、日）和`TIME`（小时、分钟、秒、毫秒）的组合。可以使用`TIMESTAMP`关键字创建时间戳，其中数据必须根据 ISO 8601 格式（`YYYY-MM-DD hh:mm:ss[.zzzzzz][+-TT[:tt]]`）进行格式化。

```
%%sql
SELECT TIMESTAMP '1992-09-20 11:30:00';
```

- **特殊值**

有三个特殊的日期值可用于输入：

| 输入字符串 | 有效的类型 | 描述 |
|---|---|---|
| epoch | timestamp, timestamptz | 1970-01-01 00:00:00+00 (Unix 系统时间零) |
| infinity | timestamp, timestamptz | 晚于所有其他时间戳 |
| -infinity | timestamp, timestamptz | 早于所有其他时间戳 |

跟`DATE`类型一样，`infinity`和`-infinity`是系统中的特定写法，显示不会发生改变; 但`epoch`是一个简写，在读取时会将其转换为具体的时间戳。

```
%%sql
SELECT '-infinity'::TIMESTAMP, 'epoch'::TIMESTAMP, 'infinity'::TIMESTAMP;
```

| Negative | Epoch | Positive |
|---|---|---|
| -infinity | 1970-01-01 00:00:00 | infinity |

##### interval
`INTERVAL`类型表示一段时间。这个周期可以用多种单位来衡量，比如年、天或秒。

| 名称 | 描述 |
|---|---|
| `INTERVAL` | 时间段 |

`INTERVAL`可以直接生成，也可以是函数的结果（例如，计算两个时间戳之间的差）。`INTERVAL`可用于修改`DATE`、`TIMESTAMP`或者`TIMESTAMP WITH TIME ZONE`数据类型。

```
%%sql
/*一年*/
SELECT INTERVAL 1 YEAR;
-- 你还可以这样写
SELECT INTERVAL 1 YEARS;

/*28天*/
SELECT INTERVAL '28' DAYS;
-- 你还可以这样写
SELECT INTERVAL '28 DAYS';

/*30秒*/
SELECT INTERVAL 30 SECONDS;

/*timestamp数据还可以由日期相减得到*/
SELECT '2022-01-02 01:00:00'::TIMESTAMP - '2022-01-01'::TIMESTAMP;

/*不存在小数的日期间隔, sql会自动将小数点后面抹去*/
SELECT INTERVAL '1.5' YEARS; --WARNING! This returns 1 year!
```

##### blob
| 名称 | 别名 | 描述 |
|---|---|---|
| blob | bytea | 可变长度二进制数据 |

`BLOB`(**B**inary **L**arge **OB**ject)类型表示存储在数据库系统中的任意二进制对象。`BLOB`类型可以包含任何类型的二进制数据，没有任何限制。实际字节所代表的内容对数据库系统是不透明的。

```
%%sql
-- 创建具有单个字节的二进制值
SELECT '\xAA'::BLOB;

-- 创建包含三个字节的二进制值
SELECT '\xAA\xAB\xAC'::BLOB;

-- 创建具有两个字节的二进制值
SELECT 'AB'::BLOB;
```

`BLOB`通常用于存储数据库不提供显式支持的非文本对象，例如图像。虽然`BLOB`可以容纳最大为 4GB 的对象，但通常不建议在数据库系统中存储非常大的对象。在许多情况下，最好将大文件存储在文件系统上，并将文件的路径存储在数据库系统中的`VARCHAR`字段。

##### list
- **列表数据类型**

`LIST`列可以具有不同长度的值，但它们必须具有相同的基础类型。`LIST`通常用于存放数字数组，但也能包含任何统一的数据类型，包括其他`LIST`和`STRUCT`。

- **创建列表**

```
%%sql
-- 只包含整数的列表
SELECT [1, 2, 3];

-- 包含NULL的列表
SELECT ['duck', 'goose', NULL, 'heron'];

-- 包含列表和NULL的列表
SELECT [['duck', 'goose', 'heron'], NULL, ['frog', 'toad'], []];

-- list_value函数是产生列表的函数
SELECT list_value(1, 2, 3);

-- 创建一个表格, 表格中包含两列, 第一列只能存储整数型列表, 第二列只能存放字符型列表. 
CREATE TABLE list_table (int_list INT[], varchar_list VARCHAR[]);
```

- **从列表中获取元素**

从列表中检索一个或多个值可以使用方括号和切片表示法，也可以通过列表函数（如`list_extract`）完成。

```
%%sql
-- 获取到列表中的第二个字符. 
SELECT (['a','b','c'])[2];

-- 获取到列表最后一个字符
SELECT (['a','b','c'])[-1];

-- 你还可以对索引作简单运算
SELECT (['a','b','c'])[1 + 1];

-- 你还可以利用list_extract函数传入索引参数获取列表中的元素
SELECT list_extract(['a','b','c'], 2);

-- 你还可以切片索引
SELECT (['a','b','c'])[1:2];

-- 你还可以单值切片索引
SELECT (['a','b','c'])[:2];

-- 切片索引最后两个元素
SELECT (['a','b','c'])[-2:];

-- sql中还支持切片索引函数
SELECT list_slice(['a','b','c'],2,3);
```

##### struct
- **Struct数据类型**

`STRUCT`列包含被称为“条目”的其他列的有序列表。这些条目使用字符串按名称引用。本文档将这些条目名称称为key。`STRUCT`列中的每一行必须具有相同的key。每行的每个`STRUCT`值的key都必须具有相同类型。

`STRUCT`通常用于将多个列嵌套到单个列中，嵌套列可以是任何类型，包括其他`STRUCT`和`LIST`。

`STRUCT`类似于Postgres的`ROW`类型。主要区别在于`STRUCT`列的每一行中都需要相同的key。这样能够通过充分利用向量执行引擎来提高性能，并且还强制实施类型一致性以提高正确性。DAI包含一个`row`函数作为生成`STRUCT`的特殊方法，但没有`ROW`这种数据类型。

有关各个嵌套数据类型的比较，请参考[数据类型](https://bigquant.com/wiki/doc/dai-PLSbc1SbZX#h-%E6%95%B0%E6%8D%AE%E7%B1%BB%E5%9E%8B)。

`STRUCT`可以使用`STRUCT_PACK(name := expr, ...)`函数或等效的数组表示法`{'name': expr, ...}`创建。表达式可以是常量或任意表达式。

- **创建STRUCT**

```
%%sql
-- Struct数据类型中包含整数

SELECT {'x': 1, 'y': 2, 'z': 3};
-- Struct数据类型中既有字符又有NULL
SELECT {'a': 'b', 'c': 'd', 'e': NULL, 'f': 'g'};

-- Struct数据类型中既有字符又有整数和浮点数
SELECT {'key1': 'string', 'key2': 1, 'key3': 12.345};

-- 使用struct_pack函数创建Struct数据类型
SELECT struct_pack(key1 := 'value1',key2 := 42);

-- Struct数据类型中既有Struct数据又有NULL
SELECT {'a':
            {'b': 'c', 'd': 'e', 'f': NULL, 'g': 'h'},
        'i':
            NULL,
        'j':
            {'k':'l', 'm': 'n', 'o': 'p', 'q':'r'}
        };
        
-- 使用row函数创建struct类型数据, 以下语句返回{'x': 1, 'v2': 2, 'y': a}
SELECT row(x, x + 1, y) FROM (SELECT 1 as x, 'a' as y);

-- 以下方式省略了row函数, 返回的依旧是{'x': 1, 'v2': 2, 'y': a}
SELECT (x, x + 1, y) FROM (SELECT 1 as x, 'a' as y);
```

- **向STRUCT添加字段/值**

```
%%sql
-- 使用struct_insert函数往现有的struct数据中插入新数据
SELECT struct_insert({'a': 1, 'b': 2, 'c': 3}, d := 4);
```

- **从STRUCT中检索**

从STRUCT中检索值可以使用点表示法、括号表示法或通过struct函数（如`struct_extract`）完成。

```
%%sql
-- 你可以使用: 表格名.键 的方式去访问struct中的值
SELECT a.x FROM (SELECT {'x':1, 'y':2, 'z':3} as a);

-- 你还可以这样访问值
SELECT a."x space" FROM (SELECT {'x space':1, 'y':2, 'z':3} as a);

-- 你还可以用方括号将键括起来访问它的值
SELECT a['x space'] FROM (SELECT {'x space':1, 'y':2, 'z':3} as a);

-- 你还可以通过struct_extract函数将键传入第二个参数位置访问其值
SELECT struct_extract({'x space': 1, 'y': 2, 'z': 3},'x space');
```

- **Struct.***

星号表示法（`*`）可用于将结构中的所有键作为单独的列检索，而不是从结构中检索单个键。当先前的操作创建未知形状的结构时，或者查询必须处理任何潜在的结构键时，该功能很有用。

```
%%sql
-- 使用以下方式可以访问所有的键值, 返回一个以键为列名, 以值为取值的表格
SELECT a.* FROM (SELECT {'x':1, 'y':2, 'z':3} as a);
```

| x | y | z |
|---|---|---|
| 1 | 2 | 3 |

- **点表示法的操作顺序**

使用点表示法引用`STRUCT`可能会与引用schema和table产生混淆。通常，DAI会首先查找列，然后查找列中的`STRUCT`键。DAI按照这种顺序解析引用，使用第一个匹配项进行操作：

**不用**`.`

```
SELECT part1 FROM tbl
```

1. part1是列

**一个**`.`

```
SELECT part1.part2 FROM tbl
```

1. part1是表，part2是列
2. part1是列，part2是列的属性

**两个或者更多**`.`

```
SELECT part1.part2.part3 FROM tbl
```

1. part1是schema，part2是表，part3是列
2. part1是表，part2是列，part3是列的属性
3. part1是列，part2是列的属性，part3是列的属性的属性

任何额外的部分（例如 .part4.part5 等）始终被视为属性。

- **使用row函数创建STRUCT**

`row`函数可用于自动将多个列转换为单个`STRUCT`列。每个输入列的名称用作键，每列的值将成为该键处的值。

将多个表达式转换为`STRUCT`时，`row`函数名称是可选的-只需要一对括号也可以。

**名为t1的示例数据表：**

| my_column | another_column |
|---|---|
| 1 | a |
| 2 | b |

**row函数示例：**

```
%%sql
CREATE TABLE bigquant_t1 (my_column INT, another_column VARCHAR);
INSERT INTO bigquant_t1 VALUES(1, 'a'), (2, 'b');

SELECT 
    row(my_column, another_column) as my_struct_column,
    (my_column, another_column) as identical_struct_column
FROM bigquant_t1;
```

**示例输出：**

| my_struct_column | identical_struct_column |
|---|---|
| {'my_column': 1, 'another_column': a} | {'my_column': 1, 'another_column': a} |
| {'my_column': 2, 'another_column': b} | {'my_column': 2, 'another_column': b} |

`row`函数（或简化的括号语法）也可以任意表达式作为输入而不只是列名。对于表达式的情况，将以`vN`的格式自动生成一个键，其中`N`是一个数字，表示其在`row`函数中的参数位置（例如：v1、v2 等）。这可以与列名组合使用，作为对`row`函数同一调用中的输入。此示例使用与上面相同的输入表。

**以列名、常量和表达式作为输入的row函数示例：**

```
%%sql
CREATE TABLE bigquant_t1 (my_column INT, another_column VARCHAR);
INSERT INTO bigquant_t1 VALUES(1, 'a'), (2, 'b');

SELECT 
    row(my_column, 42, my_column + 1) as my_struct_column,
    (my_column, 42, my_column + 1) as identical_struct_column
FROM t1;
```

**示例输出：**

| my_struct_column | identical_struct_column |
|---|---|
| {'my_column': 1, 'v2': 42, 'v3': 2} | {'my_column': 1, 'v2': 42, 'v3': 2} |
| {'my_column': 2, 'v2': 42, 'v3': 3} | {'my_column': 2, 'v2': 42, 'v3': 3} |

##### map
- **Map 数据类型**

`MAP`与`STRUCT`类似，它们都是“条目”的有序列表，而条目中的键映射到值。但是，`MAP`不需要在每一行上都存在相同的键。当架构事先未知时，`MAP`很有用。这两者的灵活性是一个关键的差异。

`MAP`必须对所有键具有单一类型，对于所有值也必须具有单一类型。键和值可以是任何类型，并且键的类型不需要与值的类型匹配（例如：`INT`映射到`VARCHAR`的`MAP`）。`MAP`不能有重复的键。如果未找到键，则`MAP`返回一个空列表，而不是像`STRUCT`那样抛出错误；

`STRUCT`必须具有字符串键，但每个键可以具有不同类型的值。有关嵌套数据类型之间的比较，请参阅[数据类型概述](https://bigquant.com/wiki/doc/dai-PLSbc1SbZX#h-%E6%95%B0%E6%8D%AE%E7%B1%BB%E5%9E%8B)。

要构造`MAP`，请使用`map`函数。提供键列表作为第一个参数，提供第二个参数的值列表。或者使用`map_from_entries`函数。

- **创建Map**

```
%%sql
-- 建立一个整数到字符的映射关系: {1=a, 5=e}
SELECT map([1, 5], ['a', 'e']);

-- 或者你还可以使用函数map_from_entries
SELECT map_from_entries([(1, 'a'), (5, 'e')]);

-- 建立一个从整数到浮点数的对应关系
SELECT map([1, 5], [42.001, -32.1]);

-- 建立一个从字典到字典的映射关系
SELECT map([['a', 'b'], ['c', 'd']], [[1.1, 2.2], [3.3, 4.4]]);

-- 使用具有整数键和双精度值的映射列创建表
CREATE TABLE map_table (map_col MAP(INT,DOUBLE));
```

- **查询Map**

`MAP`使用括号表示法检索值。从`MAP`中查询将返回`LIST`而不是单个值，空`LIST`表示未找到键。

```
%%sql
-- 你可以将键(原象)放入方括号中去访问值(象)
SELECT map([100, 5], [42, 43])[100];

-- 上述返回的只是映射关系中的象, 下面再套上一个索引访问象中的值
SELECT map([100, 5], [42, 43])[100][1];

-- 123不存在原象中, 所以找不到它对应的象
SELECT map([100, 5], [42, 43])[123];

-- 你还可以利用element_at函数, 将原象的值传入第二个参数
SELECT element_at(map([100, 5], [42, 43]),100);
```

##### union
- **Union数据类型**

`UNION`类型（不要与 SQL `UNION`运算符混淆）是一种嵌套类型，能够保存多个“替代”值中的一个，就像C中的`union`一样。主要区别在于这些`UNION`类型是*tagged unions*，因此总是带有一个标签*tag*，该标签指示它当前持有的替代值，即使内部值本身为空。 因此，`UNION`类型更类似于C++17的`std::variant`，Rust的`Enum`或大多数函数式语言中存在的“sum type”。

`UNION`类型必须始终至少有一个成员，虽然它们可以包含同一类型的多个成员，但tag名称必须是唯一的。`UNION`类型最多可以有 256 个成员。

在底层，`UNION`类型是在`STRUCT`类型之上实现的，只需将*tag*作为为第一个条目。

`UNION`值可以使用`UNION_VALUE(tag := expr)`函数或通过从成员类型强制转换来创建。

- **示例**

```
%%sql
/*创建一个包含字段u的表, 这个字段可以储存整数型和字符型数据, 并且给数据类型搭上了标签, 其中整数型的标签为num, 字符型标签为str*/
CREATE TABLE bigquant_table(u UNION(num INT, str VARCHAR));
INSERT INTO bigquant_table values (1) , ('two') , (union_value(str := 'three'));
SELECT u from bigquant_table;
-- returns:
--    1
--    two
--    three
-- Select all the 'str' members

/*查询出所有字符型的值, 如果不是字符串, 则输出NULL*/
SELECT union_extract(u, 'str') FROM bigquant_table;
-- 你还可以用: 变量.数据类型 的方法, 实现的功能和上一句的功能一致
SELECT u.str FROM bigquant_table;
-- returns: 
--    NULL
--    two
--    three

-- 查询所有值背后的数据类型标签
SELECT union_tag(u) FROM bigquant_table;
-- returns:
--    num
--    str
--    str
```

- **Union强制转换**

与其他嵌套类型相比，`UNION`允许一系列的隐式强制转换，以便在将其成员作为“子类型”使用。 这些强制转换的设计考虑了两个原则：避免歧义和避免可能导致信息丢失的转换。这可以防止`UNION`完全*transparent*，同时允许`UNION`类型与其成员具*supertype*关系。

`UNION`类型通常不能隐式强制转换为其任意的成员类型，因为与目标类型不匹配的其他成员中的信息将“丢失”。如果要强制将`UNION`转换成其某一个成员，则应显式使用`union_extract`函数。

唯一的例外是将`UNION`转换为`VARCHAR`时，成员都将使用其相应的`VARCHAR`强制转换。由于一切都可以强制转换到`VARCHAR`，这在某种程度上是安全的。

- **强制转换成Union**如果类型可以隐式强制转换为`UNION`其中一个成员类型，那么该类型始终可以隐式强制转换为`UNION`。如果有多个候选项，则内置的隐式强制转换优先级规则将确定目标类型。例如，`FLOAT -> UNION(i INT, v VARCHAR)`强制转换将始终将`FLOAT`优先强制转换为`INT`而非`VARCHAR`。如果强制转换仍然不明确，即有多个候选者具有相同的隐式转换优先级，则会引发错误。这通常发生在`UNION`包含相同类型的多个成员时，例如`FLOAT -> UNION(i INT, num INT)`总是不明确的。

那么，如果我们想创建一个具有相同类型多个成员的`UNION`，要如何消除歧义呢？

通过使用`union_value`函数，该函数使用一个参数用来指定tag。例如，`union_value(num := 2::INT)`将创建一个带有标签`num`的类型为`INT`单成员`UNION`。这可以用来消除`UNION`到`UNION`的显式（或隐式）强制转换，比如`CAST(union_value(b := 2) AS UNION(a INT, b INT))`。

- **Union间的强制转换**

如果源类型是目标类型的“子集”，则`UNION`类型可以在彼此之间强制转换类型。换句话说，源`UNION`中的所有tag都必须存在于目标`UNION`中，并且所有匹配tag的类型必须在源和目标之间隐式转换。实质上，这意味着`UNION`类型相对于其成员是协变的。

| Ok | 源 | 目标 | 注释 |
|---|---|---|---|
| ✅ | UNION(a A, b B) | UNION(a A, b B, c C) |  |
| ✅ | UNION(a A, b B) | UNION(a A, b C) | 如果B可以隐式转换到C |
| ❌ | UNION(a A, b B, c C) | UNION(a A, b B) |  |
| ❌ | UNION(a A, b B) | UNION(a A, b C) | 如果B不能隐式转换到C |
| ❌ | UNION(A, B, D) | UNION(A, B, C) |  |

#### 表达式
##### 逻辑表达式
有以下三种可用的逻辑运算符：`AND`、`OR`和`NOT`。SQL 使用`TRUE`、`FALSE`和`NULL`的三值逻辑系统。注意，涉及`NULL`的逻辑运算符并不总是计算为`NULL`。例如，`NULL AND FALSE`的计算结果为`FALSE`，`NULL OR TRUE`的计算结果为`TRUE`。以下是完整的真值表：

| `a` | `b` | `a AND b` | `a OR b` |
|---|---|---|---|
| `TRUE` | `TRUE` | `TRUE` | `TRUE` |
| `TRUE` | `FALSE` | `FALSE` | `TRUE` |
| `TRUE` | `NULL` | `NULL` | `TRUE` |
| `FALSE` | `FALSE` | `FALSE` | `FALSE` |
| `FALSE` | `NULL` | `FALSE` | `NULL` |
| `NULL` | `NULL` | `NULL` | `NULL` |

| `a` | `NOT a` |
|---|---|
| `TRUE` | `FALSE` |
| `FALSE` | `TRUE` |
| `NULL` | `NULL` |

`AND`和`OR`运算符是可交换的，即可以在不影响结果的情况下切换左右操作数。

##### 比较表达式
- **比较运算符**

下表展示了所有的标准比较运算符。只要输入参数中的任何一个为`NULL`，则比较的输出为`NULL`。

| 算子 | 描述 | 例子 | 结果 |
|---|---|---|---|
| `<` | 小于 | `2 < 3` | `TRUE` |
| `>` | 大于 | `2 > 3` | `FALSE` |
| `<=` | 小于等于 | `2 <= 3` | `TRUE` |
| `>=` | 大于等于 | `4 >= NULL` | `NULL` |
| `=` | 等于 | `NULL = NULL` | `NULL` |
| `<>` 或 `!=` | 不等于 | `2 <> 2` | `FALSE` |

下表展示了标准区分运算符。这些运算符将`NULL`值视为相等。

| 运算符 | 描述 | 例子 | 结果 |
|---|---|---|---|
| `IS DISTINCT FROM` | 相等，包括`NULL` | `2 IS DISTINCT FROM NULL` | `TRUE` |
| `IS NOT DISTINCT FROM` | 不相等，包括`NULL` | `NULL IS NOT DISTINCT FROM NULL` | `TRUE` |

- **BETWEENIS和(NOT) NULL**

除了标准的比较运算符之外，还有`BETWEEN`和`IS (NOT) NULL`运算符。它们的行为与标准运算符非常相似，但具有 SQL 标准要求的特殊语法。如下表所示：

| 谓词 | 描述 |
|---|---|
| `a BETWEEN x AND y` | 等价于 `a >= x AND a <= y` |
| `a NOT BETWEEN x AND y` | 等价于 `a < x OR a > y` |
| `expression IS NULL` | 如果表达式为`NULL`返回`TRUE`, 否则返回`FALSE` |
| `expression ISNULL` | `IS NULL`的别名 |
| `expression IS NOT NULL` | 如果表达式为`NULL`返回`FALSE`, 否则返回`TRUE` |
| `expression NOTNULL` | `IS NOT NULL`的别名 |

##### 类型转换表达式
强制类型转换是指将行的类型从一种类型更改为另一种类型的过程。标准 SQL 语法是`CAST(expr AS typename)`。DAI还支持更容易缩写方式`expr::typename`。

```
%%sql
/*产生一个整数型序列, 并将该序列的值全部转化为字符型*/
SELECT CAST(i AS VARCHAR) FROM generate_series(1, 3) bigquant_table(i);
-- "1", "2", "3"

/*产生一个整数型序列, 并将该序列的值全部转化为浮点型*/
SELECT i::DOUBLE FROM generate_series(1, 3) bigquant_table(i);
-- 1.0, 2.0, 3.0

/*你不能将一个字符型的数据转化为整数型的数据, 否则程序报错*/
SELECT CAST('hello' AS INTEGER);

/* 在数据类型转化前, 你可以使用函数TRY_CAST来判断是否能转化成功, 如果不成功则返回NULL*/
SELECT TRY_CAST('hello' AS INTEGER);
-- NULL
```

强制转换的行为取决于源和目标类型，并非所有`CAST`都可以。例如，无法将`INTEGER`转换为`DATE`。当无法成功执行强制转换时，强制转换也可能引发错误。例如，尝试将字符串`'hello'`强制转换为`INTEGER`将导致引发错误。`TRY_CAST`则不会抛出错误，而是返回`NULL`。

- **隐式强制转换**

在许多情况下，系统将自行添加强制转换，这称为隐式强制转换。例如，当使用与函数参数类型不匹配的参数调用函数时，就会发生这种情况。

考虑函数`SIN(DOUBLE)`。此函数将类型`DOUBLE`的列作为输入参数，但是，也可以使用整数调用：`SIN(1)`。整数在传递给`SIN`函数之前被转换为`DOUBLE`。

通常，隐式强制转换仅向上转换。也就是说，我们可以隐式地将`INTEGER`转换为`BIGINT`，但不能反过来。

##### 条件表达式
`CASE`语句根据条件执行切换。基本形式与许多编程语言中使用的三元条件相同（`CASE WHEN cond THEN a ELSE b END`等效于`cond ? a : b`），该语句也可以简单的表示成 `IF(cond, a, b)`  。

```
%%sql
CREATE OR REPLACE TABLE bigquant_table as SELECT UNNEST([1, 2, 3]) as i;

SELECT i, CASE WHEN i>2 THEN 1 ELSE 0 END AS test FROM bigquant_table;
-- 1, 2, 3
-- 0, 0, 1

-- 等价于
SELECT i, IF(i > 2, 1, 0) AS test FROM bigquant_table;
-- 1, 2, 3
-- 0, 0, 1
```

`CASE`语句的`WHEN cond THEN expr`部分可以链接，每当某个元组有任何条件返回 true时，都会计算并返回相应的表达式。

```
%%sql
CREATE OR REPLACE TABLE bigquant_table as SELECT UNNEST([1, 2, 3]) as i;
SELECT i, CASE WHEN i=1 THEN 10 WHEN i=2 THEN 20 ELSE 0 END AS test FROM bigquant_table;
-- 1, 2, 3
-- 10, 20, 0
```

`CASE`语句的`ELSE`部分是可选的。如果未提供 else 语句并且没有任何条件匹配，则`CASE`语句将返回`NULL`。

```
%%sql
CREATE OR REPLACE TABLE bigquant_table as SELECT UNNEST([1, 2, 3]) as i;
SELECT i, CASE WHEN i=1 THEN 10 END AS test FROM bigquant_table;
-- 1, 2, 3
-- 10, NULL, NULL
```

在`CASE`之后`WHEN`之前也可以提供单个表达式，`CASE`语句实质上将转换为 switch 语句。

```
%%sql
CREATE OR REPLACE TABLE bigquant_table as SELECT UNNEST([1, 2, 3]) as i;
SELECT i, CASE i WHEN 1 THEN 10 WHEN 2 THEN 20 WHEN 3 THEN 30 END AS test FROM bigquant_table;
-- 1, 2, 3
-- 10, 20, 30

-- 等价于
SELECT i, CASE WHEN i=1 THEN 10 WHEN i=2 THEN 20 WHEN i=3 THEN 30 END AS test FROM bigquant_table;
```

##### in
`IN`操作符检查右侧表达式集（RHS）中是否包含左侧表达式。如果表达式存在于RHS中，则`IN`操作符返回true；如果表达式不在RHS中且RHS没有`NULL`值返回false，或者如果表达式不在RHS中且RHS具有`NULL`值，则运算符返回`NULL`。

```
%%sql
SELECT 'Math' IN ('CS', 'Math');
-- true

SELECT 'English' IN ('CS', 'Math');
-- false

SELECT 'Math' IN ('CS', 'Math', NULL);
-- true

SELECT 'English' IN ('CS', 'Math', NULL);
-- NULL
```

`NOT IN`可用于检查集合中是否存在元素。`X NOT IN Y`等效于`NOT(X IN Y)`。

`IN`操作符还可以与返回单个列的子查询一起使用。

##### *
`*`表达式可用于`SELECT`语句中以选择`FROM`子句中投影的所有列。

```
%%sql
/*取出表格cn_stock_bar1d中所有的字段*/
SELECT * FROM cn_stock_bar1de;
```

可以使用`EXCLUDE`和`REPLACE`修改`*`表达式。

- **EXCLUDE子句**

`EXCLUDE`让我们可以从`*`表达式中排除特定列。

```
%%sql
/*取出表格中除了换手率以外的所有字段*/
SELECT * EXCLUDE (turn) FROM cn_stock_bar1d;
```

- **REPLACE子句**

`REPLACE`让我们可以用不同的表达式替换特定的列。

```
%%sql
/*换手率乘以100的值替换原来的换手率*/
SELECT * REPLACE (turn / 1000 AS turn) FROM bigquant_table;
```

- **COLUMNS**

`COLUMNS`表达式可用于在多个列上执行相同的表达式。与`*`表达式一样，它只能在`SELECT`子句中使用。

```
%%sql
CREATE TABLE bigquant_numbers(id int, number int);
INSERT INTO bigquant_numbers VALUES (1, 10), (2, 20), (3, NULL);
SELECT MIN(COLUMNS(*)), COUNT(COLUMNS(*)) from bigquant_numbers;
```

| min(numbers.id) | min(numbers.number) | count(numbers.id) | count(numbers.number) |
|---|---|---|---|
| 1 | 10 | 3 | 2 |

`COLUMNS`语句中的`*`表达式也可以包含`EXCLUDE`或`REPLACE`，类似于常规的`*`表达式。

```
%%sql
CREATE TABLE bigquant_numbers(id int, number int);
INSERT INTO bigquant_numbers VALUES (1, 10), (2, 20), (3, NULL);

SELECT MIN(COLUMNS(* REPLACE (number + id AS number))), COUNT(COLUMNS(* EXCLUDE (number))) from bigquant_numbers;
```

| min(numbers.id) | min(number := (number + id)) | count(numbers.id) |
|---|---|---|
| 1 | 11 | 3 |

`COLUMNS`表达式也可以组合，只要`COLUMNS`包含相同的（*）表达式：

```
%%sql
CREATE TABLE bigquant_numbers(id int, number int);
INSERT INTO bigquant_numbers VALUES (1, 10), (2, 20), (3, NULL);

SELECT COLUMNS(*) + COLUMNS(*) FROM bigquant_numbers;
```

| (numbers.id + numbers.id) | (numbers.number + numbers.number) |
|---|---|
| 2 | 20 |
| 4 | 40 |
| 6 | NULL |

最后，`COLUMNS`支持将正则表达式作为字符串常量传入：

```
%%sql
CREATE TABLE bigquant_numbers(id int, number int);
INSERT INTO bigquant_numbers VALUES (1, 10), (2, 20), (3, NULL);

SELECT COLUMNS('(id|numbers?)') FROM bigquant_numbers ;
```

| id | number |
|---|---|
| 1 | 10 |
| 2 | 20 |
| 3 | NULL |

- **Struct.***

`*`表达式还可用于从`STRUCT`中检索所有键作为单独的列。当先前的操作创建了未知形状的`STRUCT`时，或者查询必须处理任何潜在的`STRUCT`键时，这特别有用。

```
%%sql
/*如果查询的是struct数据, 利用: 表名.*的规则即可获取所有的键和值*/
SELECT bigquant_t.* FROM (SELECT {'x':1, 'y':2, 'z':3} as bigquant_t);
```

| x | y | z |
|---|---|---|
| 1 | 2 | 3 |

##### 子查询
- **标量子查询**

标量子查询是返回单个值的子查询。它们可以在任何可以使用常规表达式的地方使用。如果标量子查询返回多个值，则将使用返回的第一个值。

以下表作为示例：

- **分数**

| grade | course |
|---|---|
| 7 | Math |
| 9 | Math |
| 8 | CS |

```
%%sql
CREATE TABLE bigquant_grades(grade INTEGER, course VARCHAR);
INSERT INTO bigquant_grades VALUES (7, 'Math'), (9, 'Math'), (8, 'CS');
```

我们可以运行以下查询来获取最低分数：

```
%%sql
CREATE TABLE bigquant_grades(grade INTEGER, course VARCHAR);
INSERT INTO bigquant_grades VALUES (7, 'Math'), (9, 'Math'), (8, 'CS');

SELECT MIN(grade) FROM bigquant_grades ;
-- 返回{7}
```

通过在`WHERE`子句中使用标量子查询，我们可以找出某个分数是哪门课程的：

```
%%sql
CREATE TABLE bigquant_grades(grade INTEGER, course VARCHAR);
INSERT INTO bigquant_grades VALUES (7, 'Math'), (9, 'Math'), (8, 'CS');

SELECT course FROM bigquant_grades WHERE grade = (SELECT MIN(grade) FROM bigquant_grades);
-- 返回{Math}
```

- **Exists**

`EXISTS`运算符用于测试子查询中是否存在任何行。当子查询返回一条或多条记录时，它返回true，否则返回false。

例如，我们可以使用它来确定给定课程是否存在分数：

```
%%sql
CREATE TABLE bigquant_grades(grade INTEGER, course VARCHAR);
INSERT INTO bigquant_grades VALUES (7, 'Math'), (9, 'Math'), (8, 'CS');

SELECT EXISTS(SELECT * FROM bigquant_grades WHERE course='Math');
-- 返回true

SELECT EXISTS(SELECT * FROM grades WHERE course='History');
-- 返回false
```

- **In运算符**

`IN`运算符检查由子查询或右侧表达式集（RHS）定义的结果中是否包含左侧表达式。如果表达式存在于RHS中，则运算符返回true；如果表达式不在RHS中且RHS没有`NULL`值，则返回false；如果表达式不在RHS中且RHS具有`NULL`值，则运算符返回false。

我们可以像使用`EXISTS`运算符一样使用`IN`运算符：

```
%%sql
CREATE TABLE bigquant_grades(grade INTEGER, course VARCHAR);
INSERT INTO bigquant_grades VALUES (7, 'Math'), (9, 'Math'), (8, 'CS');

SELECT 'Math' IN (SELECT course FROM bigquant_grades);
-- true
```

- **相关子查询**

到目前为止，这里介绍的所有子查询都是不相关的子查询，其中子查询本身是完全独立的，可以在没有父查询的情况下运行。存在第二种类型的子查询，称为相关子查询。对于相关子查询，子查询使用父子查询中的值。

子查询对父查询中的每一行运行一次。也许设想这一点的一种简单方法是，相关子查询是一个应用于源数据集中每一行的函数。

例如，假设我们想找到每门课程的最低分数。我们可以按如下方式进行操作：

```
%%sql
CREATE TABLE bigquant_grades(grade INTEGER, course VARCHAR);
INSERT INTO bigquant_grades VALUES (7, 'Math'), (9, 'Math'), (8, 'CS');
CREATE TABLE bigquant_grades_parent(grade INTEGER, course VARCHAR);
INSERT INTO bigquant_grades_parent VALUES (7, 'Math'), (10, 'Math'), (8, 'CS');

SELECT *
FROM bigquant_grades bigquant_grades_parent
WHERE grade=
    (SELECT MIN(grade)
     FROM bigquant_grades
     WHERE bigquant_grades.course=bigquant_grades_parent.course);
-- {7, Math}, {8, CS}
```

子查询使用父查询（`grades_parent.course`）中的列。从概念上，我们可以将子查询视为一个函数，其中相关列是该函数的参数：

```
%%sql
CREATE TABLE bigquant_grades(grade INTEGER, course VARCHAR);
INSERT INTO bigquant_grades VALUES (7, 'Math'), (9, 'Math'), (8, 'CS');

-- 返回7
SELECT MIN(grade) FROM grades WHERE course='Math';

-- 返回8
SELECT MIN(grade) FROM grades WHERE course='CS';
```

现在，当我们为每一行执行此函数时，我们可以看到对于`Math`将返回`7`，而对于`CS`则返回`8`。我们将它与该行实际的分数进行比较，结果`(Math, 9)`这一行将被过滤掉，因为`9 <> 7`。

#### 函数
参见

[https://bigquant.com/wiki/doc/dai-sql-Rceb2JQBdS](https://bigquant.com/wiki/doc/dai-sql-Rceb2JQBdS)

### 进阶 DataSource
#### DataSource
`dai.DataSource`提供了数据表创建、读取、删除、更新等操作。

如果你主要是使用数据，可以不用关注本节类容。学习数据使用可以参考[SQL入门指南](https://bigquant.com/wiki/doc/dai-PLSbc1SbZX#h-sql-%E5%85%A5%E9%97%A8%E6%8C%87%E5%8D%97)。

##### 读取
使用DataSource访问数据：

```
import dai
import pandas as pd

ds = dai.DataSource("holidays")
df = ds.read_bdb(as_type=pd.DataFrame)

# 查看metadata
print(ds.metadata)
```

使用SQL语言访问数据：

```
# 分区的表不能读全表，如果读全表，就需要传入full_db_scan参数
dai.query("select * from 'holidays' ", full_db_scan=True).df()  
```

##### 创建
使用 dai.DataSource.write_bdb 创建新表

- 如果表存在，dai.DataSource.write_bdb 支持做插入操作
- 写入数据不能为空（未来会增加空数据支持）。

```
import numpy as np
import pandas as pd

import dai

instruments = ["000001.SZ", "000002.SZ", "000003.SZ"]
dates = list(pd.date_range("2021-12-29", "2022-01-02"))

df = pd.DataFrame({"instrument": instruments * len(dates), "date": dates * len(instruments), "value1": np.random.random(len(dates) * len(instruments))})
# 可选：定义分区，可以用于数据访问加速
df[dai.DEFAULT_PARTITION_FIELD] = df["date"].apply(lambda x: f"{x.year}")

dai.DataSource.write_bdb(
    data=df,
    # datasource id是全局唯一的，支持小写字母、数字、下划线，以字母开始
    id="test_data_for_fun",
    # 数据插入时，根据unique_together如果有重复的，会去重.如果有分区,则需要传入索引参数indexes
    unique_together=["date", "instrument"],
    indexes=["date"],
)
```

##### 更新
- **更新和插入行**
- dai.DataSource.insert_bdb 支持插入行数据
- 如果数据表指定了 unique_together，对于重复的数据会去重，保留插入的数据

```
import pandas as pd
import dai

ds = dai.DataSource("test_data_for_demo")

instruments = ["000001.SZ", "000002.SZ", "000003.SZ"]
dates = list(pd.date_range("2021-01-03", "2022-01-05"))

df = pd.DataFrame({"instrument": instruments * len(dates), "date": dates * len(instruments), "value": np.random.random(len(dates) * len(instruments))})
df[dai.DEFAULT_PARTITION_FIELD] = df["date"].apply(lambda x: f"{x.year}")

ds.insert_bdb(df)
```

- **删除行**
- dai.DataSource.apply_bdb：支持对数据按分区做维护
- apply_bdb 会处理所有分区。未来会增加分区裁剪优化。

```
import pandas as pd
import dai

ds = dai.DataSource("test_data_for_demo")

def delete_000001(df):
    df = df[df["instrument"] != "000001.SZ"]
    return df

ds.apply_bdb(delete_000001,as_type=pd.DataFrame)
```

- **插入列**

```
import pandas as pd
import dai

ds = dai.DataSource("test_data_for_demo")

def insert_value2(df):
    df["value2"] = np.random.random(len(df))
    return df

ds.apply_bdb(insert_value2,as_type=pd.DataFrame)
```

- **删除列**

```
import pandas as pd
import dai

ds = dai.DataSource("test_data_for_demo")

def remove_value2(df):
    del df["value2"]
    return df

ds.apply_bdb(remove_value2,as_type=pd.DataFrame)
```

##### 删除表
删除DataSource。只有数据表创建者可以删除。

```
import dai

ds = dai.DataSource("test_data_for_demo")

ds.delete()
```

##### 文档
进入[我的数据](https://bigquant.com/data/categories/my-data?target=true)，选择要编辑的DataSource，点击编辑，可以编写数据文档。

##### 上架
数据上架后，可以在数据平台展示，供其他用户免费或者付费订阅使用：

- 进入 我的数据，可以看到我创建的数据；
- 点击发布，申请上架到数据平台，让其他用户订阅使用；
- 平台审核通过后，其他用户可以订阅使用。

##### 权限
- 数据表开发者任何用户都可以创建开发数据；数据表创建者有数据全部的权限，可以修改、删除数据，也可以为数据编写文档和上架到[数据平台](https://bigquant.com/data/home)。
- 数据表使用者使用者可以订阅数据平台的数据；使用者可以读取订阅的数据。

#### DataSource - zero
DataSource zero是用于完全自定义的DataSource。

通过 dai.DataSource.write_zero 创建一个新的 DataSource zero，mnt = dai.DataSource(id=xxx).mount() 可以把 DataSource zero 挂载到用户 AIStudio，mnt.path 为挂载后的目录，可以像本地目录一样读写（只有创建者有权限写）。

##### #create_zero

- **dai.DataSource.write_zero**

```
class DataSource:
    @classmethod
    def write_zero(cls, id: str) -> "DataSource":
        """创建一个空的DataSource，并由用户自己管理

        Args:
            id (str): datasource id

        Returns:
            DataSource: datasource
        """
```

- **创建DataSource zero**

```
ds = dai.DataSource.write_zero("testzero001")
```

- **在数据平台查看**

创建后，可以在 [数据平台 > 我的](https://bigquant.com/data/categories/my-data?target=true) 看到这个DataSource，并完善文档，也可以申请上架到数据平台。

##### mount和使用
- **自动方式**

```
with ds.mount() as path:
    # mount到本地 path，并自动 unmount
    print(f"{path=}")
```

- **手动方式**

```
# 手动unmount

mnt = ds.mount()

print(f"{mnt.path=}")

# 用完后 unmount
mnt.unmount()
```

##### 相关代码
#### DataSource - pickle
主要用于存取 picklable 的数据。

##### 创建数据
```
dai.DataSource.write_pickle(picklable, id="your-datasource-id")
```

##### 读取数据
```
dai.DataSource("your-datasource-id").read_pickle()
```

##### 管理数据
创建成功后，可到数据平台 → 我的数据，进行管理。

#### DataSource - text & binary
主要用于存取文本和二进制数据。

##### 创建数据
```
# 创建文本数据
dai.DataSource.write_text(text, id="your-datasource-id")

# 创建二进制数据
dai.DataSource.write_binary(bytes, id="your-datasource-id")
```

##### 读取数据
```
# 读取文本数据
dai.DataSource("your-datasource-id").read_text()

# 读取二进制数据
dai.DataSource("your-datasource-id").read_binary()
```

##### 管理数据
创建成功后，可到数据平台 → 我的数据，进行管理。

### 进阶 View
### #DAI 接口文档

#### #dai.udf.functional

- **UDFType**UDFType.NATIVE: python函数类型。UDFType.ARROW: pyarrow表函数类型。
- **FunctionNullHandling**FunctionNullHandling.DEFAULT: 输入为null值，则直接返回null。FunctionNullHandling.SPECIAL: 输入为null值，也继续按照函数逻辑处理。
- **ExceptionHandling**ExceptionHandling.DEFAULT: 遭遇异常，直接抛出异常。ExceptionHandling.RETURN_NULL: 遭遇异常，返回null。

#### #dai.udf.typing

**自定义函数参数和返回值的数据类型：**

- **DaiType**
- **BIGINT**
- **BIT**
- **BLOB**
- **BOOLEAN**
- **DATE**
- **DOUBLE**
- **FLOAT**
- **HUGEINT**
- **INTEGER**
- **INTERVAL**
- **SMALLINT**
- **SQLNULL**
- **TIME**
- **TIMESTAMP**
- **TIMESTAMP_MS**
- **TIMESTAMP_NS**
- **TIMESTAMP_S**
- **TIMESTAMP_TZ**
- **TIME_TZ**
- **TINYINT**
- **UBIGINT**
- **UINTEGER**
- **USMALLINT**
- **UTINYINT**
- **UUID**
- **VARCHAR**

#### #dai.DaiUDF

**dai.DaiUDF** *(name, function, parameters=None, return_type=None, type=UDFType.NATIVE, null_handling=FunctionNullHandling.DEFAULT, exception_handling=ExceptionHandling.DEFAULT, side_effects=False)*

DAI Python UDF类。

**参数：**

- **name: str**，SQL语句。
- **function: Callable**，函数体。
- **parameters: List[DaiPyType]**，参数列表，默认为空。
- **return_type: DaiPyType**，返回值类型，默认为空。
- **type: UDFType**，函数类型，默认为UDFType.NATIVE。
- **null_handling: FunctionNullHandling**，是否处理空值，默认为FunctionNullHandling.DEFAULT。
- **exception_handling: ExceptionHandling**，是否处理异常，默认为ExceptionHandling.DEFAULT。
- **side_effects: bool**，是否产生副作用，默认为False。

**示例：**

```
# 添加自定义函数，带类型声明
def in_instruments_pool_with_type_annotation(instrument: str) -> bool:
    instruments_pool = [
        "000001.SZ",
        "000002.SZ",
        "600519.SH"
    ]
    return instrument in instruments_pool
# 自定义函数，不带类型声明
def in_instruments_pool(instrument):
    instruments_pool = [
        "000001.SZ",
        "000002.SZ",
        "600519.SH"
    ]
    return instrument in instruments_pool
# 如果自定义python函数有类型声明，一般可以不用指定参数类型和返回值
bar1d_my_instruments_pool_df = dai.query(
    "select * from cn_stock_bar1d where in_instruments_pool(instrument) and date> '2023-01-01'",
    udf_list=[
        dai.DaiUDF(
            name="in_instruments_pool",
            function=in_instruments_pool_with_type_annotation,
        )
    ]
).df()
# 如果使用不带类型声明的函数，则会抛出错误
# bar1d_my_instruments_pool_df = dai.query(
#     "select * from cn_stock_bar1d where in_instruments_pool(instrument) and date> '2023-01-01'",
#     udf_list=[
#         dai.DaiUDF(
#             name="in_instruments_pool",
#             function=in_instruments_pool,
#         )
#     ]
# ).df()
# InvalidInputException: Invalid Input Error: Could not infer the return type,
# please set it explicitly
# 需要指明函数的参数和返回值类型
bar1d_my_instruments_pool_df = dai.query(
    "select * from cn_stock_bar1d where in_instruments_pool(instrument) and date> '2023-01-01'",
    udf_list=[
        dai.DaiUDF(
            name="in_instruments_pool",
            function=in_instruments_pool,
            parameters=[dai.udf.typing.VARCHAR],
            return_type=dai.udf.typing.BOOLEAN
        )
    ]
).df()
```

#### #UDF 持久化管理

##### #dai.create_function

**dai.create_function** *(name, function, parameters, return_type, type=UDFType.NATIVE, null_handling=FunctionNullHandling.DEFAULT, exception_handling=ExceptionHandling.DEFAULT, side_effects=False, description=None, overwrite=False) -> dict*

创建并持久化 UDF 函数到数据库，保存后的函数可以在后续查询中自动加载使用。

**参数：**

- **name: str**，UDF 函数名称（必填）。函数名必须以字母开头，只能包含字母、数字和下划线。
- **function: Callable**，Python 函数对象（必填）。
- **parameters: List[DaiType]**，参数类型列表（必填）。
- **return_type: DaiType**，返回值类型（必填）。
- **type: UDFType**，UDF 类型，默认为 UDFType.NATIVE。
- **null_handling: FunctionNullHandling**，NULL 值处理方式，默认为 FunctionNullHandling.DEFAULT。
- **exception_handling: ExceptionHandling**，异常处理方式，默认为 ExceptionHandling.DEFAULT。
- **side_effects: bool**，是否有副作用，默认为 False。
- **description: Dict[str, Any]**，函数说明信息（可选），支持存储结构化数据，例如: {"description": "函数描述", "author": "作者", "version": "1.0"}。
- **overwrite: bool**，是否覆盖已有函数，默认为 False。如果为 True，当函数名已存在时会更新；如果为 False，函数名已存在时会报错。

**返回值：** **dict** - 包含创建状态的字典

**重要说明：**

- 函数中使用的**第三方库（如 numpy、pandas 等）必须在函数内部导入**，不要在函数外部导入
- typing 模块的类型（如 `Iterable`, `Optional` 等）可以直接使用，无需导入

**示例：**

```
import dai
from dai.udf.typing import INTEGER, DOUBLE
from typing import Iterable, Optional

# 简单函数示例
def add_one(x):
    return x + 1

# 创建并持久化函数
result = dai.create_function(
    "add_one",
    add_one,
    parameters=[INTEGER],
    return_type=INTEGER,
    description={
        "description": "给输入值加1",
        "author": "张三",
        "version": "1.0"
    }
)
print(result)  # {'name': 'add_one', 'message': '函数创建成功'}

# 使用第三方库的函数（必须在函数内部导入）
def calculate_mean(values: Iterable[float]) -> float:
    import numpy as np  # 在函数内部导入 numpy
    arr = np.array(list(values))
    return float(np.mean(arr))

dai.create_function(
    "calculate_mean",
    calculate_mean,
    parameters=[Iterable[float]],
    return_type="double",
)

# 使用已保存的函数进行查询（需要设置 auto_load_udf=True）
result_df = dai.query(
    "select instrument, add_one(close) as close_plus_one from cn_stock_bar1d where date='2023-01-01'",
    auto_load_udf=True
).df()

# 更新已有函数（使用 overwrite=True）
def add_one_v2(x):
    return x + 1.5

dai.create_function(
    "add_one",
    add_one_v2,
    parameters=[INTEGER],
    return_type=INTEGER,
    overwrite=True  # 覆盖已有函数
)
```

**注意：** 已保存的 UDF 函数需要在调用 `dai.query()` 时设置 `auto_load_udf=True` 才会自动加载。默认情况下不会自动加载，以避免不必要的性能开销。

##### #dai.list_functions

**dai.list_functions** *() -> List[str]*

列出所有已保存的 UDF 函数名称。

**返回值：** **List[str]** - UDF 函数名称列表

**示例：**

```
import dai

# 列出所有已保存的函数
function_names = dai.list_functions()
print(function_names)  # ['add_one', 'multiply_by_two', 'custom_transform']
```

##### #dai.delete_function

**dai.delete_function** *(name) -> dict*

删除已保存的 UDF 函数。

**参数：**

- **name: str**，UDF 函数名称。

**返回值：** **dict** - 包含删除状态的字典

**示例：**

```
import dai

# 删除已保存的函数
result = dai.delete_function("add_one")
print(result)  # {'name': 'add_one', 'message': '函数删除成功'}
```

#### #dai.query

**dai.query** *(sql, udf_list=[], full_db_scan=False, filters={}, bind_relations=None, params=None, compression=False, auto_load_udf=False) -> QueryResult*

通过SQL语句读取并处理数据。

**参数：**

- **sql: str**，SQL语句。
- **udf_list: List[DaiUDF]**，python自定义函数，默认为空。
- **full_db_scan: bool**，是否允许全表扫描，默认不允许，即为False。
- **filters: Dict[str, List[Any]]**，过滤条件，可用于优化查询速度，默认为空。
- **bind_relations: Dict[str, Any]**，绑定关系，用于注册临时表或关系对象，默认为None。
- **params: Dict[str, Any]**，SQL中的命名参数，例如SQL中使用$a，则params应为{"a": "value"}，默认为None。
- **compression: bool**，是否启用压缩，默认为False。
- **auto_load_udf: bool**，是否自动加载已持久化的UDF函数，默认为False。设置为True时，会自动加载所有通过`dai.create_function()`保存的UDF函数。

**返回值：** **QueryResult**

- **QueryResult.arrow** *() -> pyarrow.Table*返回查询结果的Arrow格式。
- **QueryResult.df** *() -> pandas.DataFrame*返回查询结果的DataFrame格式。
- **QueryResult.explain** *(explain_type="standard") -> str***explain_type: str**，解释类型，"standard"或者"analyze"，默认为"standard"，analyze会做时间估算。返回查询结果的执行计划。
- **QueryResult.fetchall** *() -> list*返回查询结果的所有行，列表格式。
- **[QueryResult.pl](http://queryresult.pl/)** *() -> polars.DataFrame*返回查询结果的polars DataFrame格式。

**示例：**

```
import dai
# 查询日线数据
bar1d_000001_df = dai.query(
    "select * from cn_stock_bar1d where instrument= '000001.SZ' and date >= '2023-01-01'").df()
# 过滤条件也可以写到filters参数中
bar1d_000001_df = dai.query(
    "select * from cn_stock_bar1d",
    filters={"instrument": ["000001.SZ"], "date": ["2023-01-01", "2024-01-01"]}).df()
# 如果要查询全表数据会抛错
# bar1d_full_df = dai.query("select * from cn_stock_bar1d").df()
# Error: Permission Error: Can not full scan bdb table cn_stock_bar1d,
# please add partition filters in query function or set full_db_scan=true; in sql
# 可以设置 limit 以避免读取全表数据
bar1d_limit_df = dai.query("select * from cn_stock_bar1d limit 10").df()
# 一些特殊情况的limit也会读取全表数据，比如 order，可以添加 full_db_scan 参数以查询全表数据
# bar1d_order_limit_df = dai.query("select * from cn_stock_bar1d order by close desc limit 10").df()
bar1d_order_limit_df = dai.query(
    "select * from cn_stock_bar1d order by close desc limit 10", full_db_scan=True).df()
# 或者可以选择在sql中设置 full_db_scan
bar1d_order_limit_df = dai.query("""
set full_db_scan=true;
select * from cn_stock_bar1d order by close desc limit 10""").df()
# 如果您所在在开发环境内存很小可以用set memory_limit='1GB'; 设置内存限制
# 默认会使用环境75%的内存
bar1d_full_df = dai.query("""
set full_db_scan=true;
set memory_limit='1GB';
select * from cn_stock_bar1d""").df()
```

#### #dai.DataSource

##### #dai.DataSource.read

自动判断DataSource的类型，获取相应的数据。

**示例：**

```
import dai

dai.DataSource("test_for_fun").read()
dai.DataSource("test_for_fun_pickle").read()
dai.DataSource("test_for_fun_binary").read()
dai.DataSource("test_for_fun_text").read()
dai.DataSource("test_for_fun_json").read()
```

##### #dai.DataSource.exists

判断DataSource是否存在，存在返回True，不存在则返回False。

**返回值：** **bool**

**示例：**

```
import dai

dai.DataSource("test_for_fun").exists()
```

##### #dai.DataSource.type

获取DataSource的类型。

**示例：**

```
# 获取数据源的类型
import dai

dai.DataSource("test_for_fun").type   # bdb
dai.DataSource("test_for_fun_pickle").type   # pickle
dai.DataSource("test_for_fun_binary").type   # binary
dai.DataSource("test_for_fun_text").type   # text
dai.DataSource("test_for_fun_json").type   # json
```

##### #dai.DataSource.metadata

获取DataSource的元数据。

**示例：**

```
# 获取数据源的元数据
import dai

print(dai.DataSource("holidays").metadata)
# {'type': 'bdb', 'schema': {'date': 'timestamp[ns]', 'market_code': 'string'}, 'partitioning': None, 'indexes': None, 'unique_together': ['date', 'market_code'], 'on_duplicates': 'last', 'preserve_pandas_index': False, 'sort_by': None}
```

##### #dai.DataSource.write_bdb

**dai.DataSource.write_bdb** *(data, id=None, partitioning=None, indexes=None, excludes=None, unique_together=None, on_duplicates="last", sort_by=None, preserve_pandas_index=False, docs=None, timeout=300, extra="", overwrite=False) -> DataSource*

创建bdb新表。

**参数：**

- **data: Union[pa.Table, pd.DataFrame, ds.Dataset]**，数据。
- **id: str**，数据源ID，默认为None。
- **partitioning: List[str]**，分区字段，默认为None。
- **indexes: List[str]**，索引字段，默认为None。
- **excludes: Set[str]**，排除字段，默认为None。
- **unique_together: List[str]**，唯一约束字段，默认为None。
- **on_duplicates: str**，重复数据处理策略，默认为last。
- **sort_by: List[Tuple[str, str]]**，排序字段，默认为None。
- **preserve_pandas_index: bool**，是否保留pandas索引，默认为False。
- **docs: Dict[str, Any]**，数据源文档，默认为None。
- **timeout: int**，锁超时时间，默认为300秒。
- **extra: str**，写入元数据的额外信息，默认为空字符串。
- **overwrite: bool**，覆盖已有数据，分区数据不支持覆盖。

**返回值：** **DataSource**

**示例：**

```
import numpy as np
import pandas as pd

import dai

instruments = ["000001.SZ", "000002.SZ", "000003.SZ"]
dates = list(pd.date_range("2021-12-29", "2022-01-02"))

df = pd.DataFrame({"instrument": instruments * len(dates), "date": dates * len(instruments), "value1": np.random.random(len(dates) * len(instruments))})
# 可选：定义分区，可以用于数据访问加速
df[dai.DEFAULT_PARTITION_FIELD] = df["date"].dt.year

# 如果这里抛出 ArrowInvalid: Object is not allowed to access 的错误，请您修改id
dai.DataSource.write_bdb(
    data=df,
    # datasource id是全局唯一的，支持小写字母、数字、下划线，以字母开始
    id="test_for_fun",
    # 数据插入时，根据unique_together如果有重复的，会去重.如果有分区,则需要传入索引参数indexes
    unique_together=["date", "instrument"],
    indexes=["date"],
)
```

##### #dai.DataSource.read_bdb

**dai.DataSource.read_bdb** *(as_type=pa.Table, partition_filter=None, columns=None) -> pa.Table | pd.DataFrame | ds.Dataset*

读取bdb表。

**参数：**

- **as_type: Union[pa.Table, pd.DataFrame, ds.Dataset]**，返回类型，默认为pa.Table。
- **partition_filter: Dict[str, Union[tuple, set]]**，分区过滤条件，默认为None。
- **columns: List[str]**，返回部分列，默认为None。

**返回值：**

- **pa.Table**，当as_type为pa.Table时返回。
- **pd.DataFrame**，当as_type为pd.DataFrame时返回。
- **ds.Dataset**，当as_type为ds.Dataset时返回。

**示例：**

```
import pandas as pd

import dai

df_result = dai.DataSource("test_for_fun").read_bdb(as_type=pd.DataFrame)
df_result_with_filter = dai.DataSource("test_for_fun").read_bdb(as_type=pd.DataFrame, partition_filter={
    "date": ("2023-01-01", "2023-01-15"),
    "instrument": {"000002.SZ"}
})
df_result_with_columns = dai.DataSource("test_for_fun").read_bdb(as_type=pd.DataFrame, partition_filter={
    "date": ("2023-01-01", "2023-01-15"),
    "instrument": {"000002.SZ"}
}, columns=["instrument", "date"])
```

##### #dai.DataSource.insert_bdb

**dai.DataSource.insert_bdb** *(data, excludes=None, timeout=300)*

更新和插入数据行到bdb表。

**参数：**

- **data: Union[pa.Table, pd.DataFrame, ds.Dataset]**，数据，支持类型为pa.Table、pd.DataFrame、ds.Dataset。
- **excludes: Set[str]**，需要排除的字段，默认为None。
- **timeout: int**，锁超时时间，默认为300秒。

**返回值：** **DataSource**

**示例：**

```
import numpy as np
import pandas as pd
import dai

ds = dai.DataSource("test_for_fun")

instruments = ["000001.SZ", "000002.SZ", "000003.SZ"]
dates = list(pd.date_range("2022-01-05", "2022-01-15"))

df = pd.DataFrame({"instrument": instruments * len(dates), "date": dates * len(instruments), "value1": np.random.random(len(dates) * len(instruments))})
df[dai.DEFAULT_PARTITION_FIELD] = df["date"].dt.year

ds.insert_bdb(df)
```

##### #dai.DataSource.apply_bdb

**dai.DataSource.apply_bdb** *(func=None, as_type=pa.Table, partition_filter=None, timeout=300) -> DataSource*

按partition处理数据，可以用于数据增删查改。

**参数：**

- **func: Callable[[Union[pa.Table, pd.DataFrame, ds.Dataset]], Optional[Union[pa.Table, pd.DataFrame, ds.Dataset]]]**，数据处理函数。输入为当前分区的数据。返回数据，如果长度大于0，则使用返回数据更新分区；如果长度为0，则删除当前分区；如果为None，则不对分区做处理。
- **as_type: Union[pa.Table, pd.DataFrame, ds.Dataset]**，数据插入类型，默认为pa.Table。
- **partition_filter: Dict[str, Union[tuple, set]]**，分区过滤条件，默认为None。
- **timeout: int**，锁超时时间，默认为300秒。

**返回值：** **DataSource**

**示例：**

```
import numpy as np
import pandas as pd
import dai

ds = dai.DataSource("test_for_fun")

def delete_000001(df):
    df = df[df["instrument"] != "000001.SZ"]
    return df

def insert_value2(df):
    df["value2"] = np.random.random(len(df))
    return df

def remove_value2(df):
    del df["value2"]
    return df

def delete_all(df):
    return pd.DataFrame()

# 删除行
ds.apply_bdb(delete_000001, as_type=pd.DataFrame)
# 插入列
ds.apply_bdb(insert_value2, as_type=pd.DataFrame)
# 删除列
ds.apply_bdb(remove_value2, as_type=pd.DataFrame)
# 指定 partition_filter 可以只处理某些分区的数据以提高效率，例如删除 2022 分区的所有数据
ds.apply_bdb(
    delete_all,
    as_type=pd.DataFrame,
    partition_filter={
        "date": ("2022-01-01", "2023-01-01")
    }
)
```

##### #dai.DataSource.check_bdb

**dai.DataSource.check_bdb** *(delete_invalid_data=False)*

检查数据源是否存在异常。

**参数：**

- **delete_invalid_data: bool**，是否删除异常数据，默认为False。

**示例：**

```
import dai
dai.DataSource("test_for_fun").check_bdb()
# 删除异常数据，后续再补充数据
dai.DataSource("test_for_fun").check_bdb(delete_invalid_data=True)
```

##### #dai.DataSource.write_pickle

**dai.DataSource.write_pickle** *(data, id=None, overwrite=False) -> DataSource*

写入pickle数据。

**参数：**

- **data: PyObject**，数据。
- **id: str**，数据id，默认为None，写入到cache数据。
- **overwrite: bool**，覆盖已有数据。

**返回值：** **DataSource**

**示例：**

```
import dai

pyobject = {"a": 1, "b": 2}
dai.DataSource.write_pickle(pyobject, id="test_for_fun_pickle")
```

##### #dai.DataSource.read_pickle

**dai.DataSource.read_pickle** *() -> PyObject*

读取pickle数据。

**返回值：** **PyObject**

**示例：**

```
import dai

dai.DataSource("test_for_fun_pickle").read_pickle()
# {'a': 1, 'b': 2}
```

##### #dai.DataSource.write_text

**dai.DataSource.write_text** *(data, id=None, overwrite=False) -> DataSource*

写入文本数据。

**参数：**

- **data: str**，数据。
- **id: str**，数据id，默认为None，写入到cache数据。
- **overwrite: bool**，覆盖已有数据。

**返回值：** **DataSource**

**示例：**

```
import dai

text = "Hello, world!"
dai.DataSource.write_text(text, id="test_for_fun_text")
```

##### #dai.DataSource.read_text

**dai.DataSource.read_text** *() -> str*

读取文本数据。

**返回值：** **str**

**示例：**

```
import dai

dai.DataSource("test_for_fun_text").read_text()
# 'Hello, world!'
```

##### #dai.DataSource.write_json

**dai.DataSource.write_json** *(data, id=None, overwrite=False) -> DataSource*

写入json数据。

**参数：**

- **data: any**，json数据。
- **id: str**，数据id，默认为None，写入到cache数据。
- **overwrite: bool**，覆盖已有数据。

**返回值：** **DataSource**

**示例：**

```
import dai

json = {"a": 1, "b": 2, "c": [1, 2, 3]}
dai.DataSource.write_json(json, id="test_for_fun_json")
```

##### #dai.DataSource.read_json

**dai.DataSource.read_json** *() -> any*

读取json数据。

**返回值：** **any**

**示例：**

```
import dai

dai.DataSource("test_for_fun_json").read_json()
# {"a": 1, "b": 2, "c": [1, 2, 3]}
```

##### #dai.DataSource.write_binary

**dai.DataSource.write_binary** *(data, id=None, overwrite=False) -> DataSource*

写入字节数据。

**参数：**

- **data: bytes**，数据。
- **id: str**，数据id，默认为None，写入到cache数据。
- **overwrite: bool**，覆盖已有数据。

**返回值：** **DataSource**

**示例：**

```
import dai

binary = b"Hello, world!"
dai.DataSource.write_binary(binary, id="test_for_fun_binary")
```

##### #dai.DataSource.read_binary

**dai.DataSource.read_binary** *() -> bytes*

读取字节数据。

**返回值：** **bytes**

**示例：**

```
import dai

dai.DataSource("test_for_fun_binary").read_binary()
# b'Hello, world!'
```

##### #dai.DataSource.delete

**dai.DataSource.delete** *()*

删除数据。

**示例：**

```
import dai

dai.DataSource("test_for_fun_binary").delete()
```

##### #dai.DataSource.write_zero

**dai.DataSource.write_zero** *(id) -> DataSource*

创建一个空的DataSource，并由您自己管理。

**参数：**

- **id: str**，数据id。

**返回值：** **DataSource**

**示例：**

```
import dai

ds = dai.DataSource.write_zero("test_for_fun_zero")
```

##### #dai.DataSource.mount

**dai.DataSource.mount** *(with_write=False, symlink_to=None, symlink_force=False) -> DataSourceMount*

挂载DataSource目录，只支持 zero DataSource挂载。

**参数：**

- **with_write: bool**，可写模式挂载，只有DataSource创建者可以执行此操作，默认为False。
- **symlink_to: str**，创建软链到指定地址，默认为None。
- **symlink_force: bool**，强制创建软链，如果目标地址文件存在，则删除，默认为False。

**返回值：** **DataSourceMount**

**示例：**

```
import dai

with dai.DataSource("test_for_fun_zero").mount(with_write=True) as path:
    # mount到本地 path，并自动 unmount
    print(f"{path=}")
    # 往挂载目录可以写入数据
    with open(f"{path}/test_for_fun.txt", "w") as f:
        f.write("Hello, world!")
```

##### #dai.DataSource.unmount

**dai.DataSource.unmount** *(path)*

卸载挂载的DataSource目录。

**参数：**

- **path: str**，挂载目录。

**示例：**

```
import dai

ds = dai.DataSource("test_for_fun_zero")
mnt = ds.mount()
print(f"{mnt.path=}")
with open(f"{mnt.path}/test_for_fun.txt", "r") as f:
    print(f.read())
ds.unmount(mnt.path)
```

##### #dai.DataSource.save_view

**dai.DataSource.save_view** *(id, sql, update_if_exists=True, docs=None, timeout=300) -> DataSource*

保存视图类DataSource。

**参数：**

- **id: str**，数据id。
- **sql: str**，视图sql。
- **update_if_exists: bool**，如果视图存在，则更新，默认为True。
- **docs: Dict[str, Any]**，视图文档，默认为None。
- **timeout: int**，锁超时时间，默认为300秒。

**返回值：** **DataSource**

**示例：**

```
import dai

sql = """
select * from cn_stock_bar1d prune join cn_stock_valuation using (instrument, date)
"""
dai.DataSource.save_view("test_for_fun_view", sql)
result_df = dai.query("select * from test_for_fun_view where date > '2023-01-01' order by instrument, date").df()
```

##### #dai.DataSource.persist

**dai.DataSource.persist** *(id, overwrite=False) -> DataSource*

持久化缓存DataSource。

**参数：**

- **id: str**，数据id。
- **overwrite: bool**，是否覆盖已有数据源。

**返回值：** **DataSource**

**示例：**

```
import dai

text = "Hello, world!"
cached_datasource = dai.DataSource.write_text(text)
cached_datasource.persist("test_for_persist")
```

### #

标签：

因子数据

金融数据平台

金融数据获取

[bqay3f0b](https://bigquant.com/u/529a234d-3cff-4edd-b919-35c444452887)Lv3 · 一月 07,2024

[bqqjwa9o](https://bigquant.com/u/913856cd-0812-41af-bffb-625d125d39c0)Lv1 · 六月 15,2024

[阿土伯](https://bigquant.com/u/182ed910-da7c-4edc-9dfd-9dfb5807560e)Lv14 · 九月 10,2024

[量化养家](https://bigquant.com/u/f84d4307-d163-4340-8d2f-b2a6fe6f3aca)Lv13 · 一月 18,2026
