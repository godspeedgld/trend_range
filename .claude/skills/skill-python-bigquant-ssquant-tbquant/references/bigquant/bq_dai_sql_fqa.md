# DAI SQL FAQ

> 来源：https://bigquant.com/wiki/doc/C7MciptBTM（本地 HTML 快照转换；远程为最新版本，如需更新访问链接）

DAI SQL FAQ


### 列名和字符串如何区分
字符串用单引号（'）来包围，而列名通常不需要引号。如果列名中包含特殊字符（例如空格、连字符、其他符号等），您需要使用双引号（"）来引用列名。如下：

```
%%sql
select date, instrument, close/open as "con1: close/open"
from cn_stock_bar1d
where date = '2024-08-12' and "con1: close/open" > 1
```

### 如何实现自定义的带有窗口的 macro 函数
创建 macro 函数的语法可参见 [create macro](https://bigquant.com/wiki/doc/dai-PLSbc1SbZX#h-create-macro).

DAI 提供的滚动窗口函数 `m_aggregate_func` (e.g. `m_avg`, `m_median`, etc.) 有这样的模型：

```
create macro m_aggregate_func(args, win_sz, pb:=instrument, ob:=date) as
    aggregate_func(args) over (partition by pb order by ob rows win_sz-1 preceding)
```

*注意*：`args` 如果是多个参数，定义 macro 函数时需要分开指明。默认参数 `pb`, `ob` 如果有多个参数也需要分开指明。也就是说每个标识符只能传入一个参数。

类似的，时间截面窗口函数 `c_rank`, `c_avg` 实现：

```
create macro c_rank_asc(arg, pb:=date) as
    rank() over (partition by pb order by arg);

create macro c_rank_desc(arg, pb:=date) as
    rank() over (partition by pb order by arg desc);

-- 不能传入关键字作为参数，asc/desc 是关键字
-- create macro c_rank(arg, pb:=date, order_type:=asc) as
--     rank() over (partition by pb order by arg order_type);

-- workaround
create macro c_rank(arg, pb:=date, ascending:=true) as
    if (ascending, rank() over (partition by pb order by arg), 
                   rank() over (partition by pb order by arg desc));

create macro c_avg(arg, pb:=date) as
    avg(arg) over (partition by pb);
```

### #窗口函数宏传入多个 partition by/order by 项

有时候我们会需要按多个列做分区，比如求每日同一行业内所有的股票的平均收盘价：

```
select
    instrument,
    date,
    close,
    c_avg(close, pb:='date, industry_level1_code') as avg1,
    -- avg1 is equivalent to avg2
    avg(close) over (partition by date, industry_level1_code) as avg2,
    -- some factor: f(close, avg)
from cn_stock_bar1d
join cn_stock_industry_component  -- industry_level1_code
using(date, instrument)
where date >= '2023-01-01' and date < '2024-01-01' and industry = 'sw2021'
```

我们可以传入以逗号`,`分隔的字符串（单引号括起）给 `pb`参数, e.g.,  `pb:=’A, B, C, D’`，它会自动解析成 `partition by A, B, C, D`。如果某列列名含有空格，e.g., `pb:=’date, industry level name’` ，它相当于 `partition by date, “industry level name“`，即该项除去两边的空白符。`order by`可以传入类似的字符串，但由于 order 有升降序之分，可以传入前置 `-`来表示降序，否则为升序。例如，`ob:=’A,-B,C’` 则表示 `order by A asc, B desc, C asc`（亦可省略`asc`, 默认升序）。

```
df = pd.DataFrame({'A': ['a', 'b', 'c', 'a', 'b', 'c', 'a', 'b', 'c'],
                   'B': [1, 1, 1, np.nan, 2, 2, 3, 3, 3],
                   'C': [1, 2, 3, 4, 5, 6, 7, 8, 9],
                   'D': ['X', 'X', 'X', 'Y', 'Y', 'Y', 'Y', 'X', 'X']})

df2 = pd.DataFrame({'A': ['a', 'b', 'c'],
                    'E': ['apple', 'banana', 'coconut']})

select *,
    rank('A, -B') as x, -- equivalent to rAB
    rank() over (order by A, B desc) as rAB,
    rank_by(D, '-A, C') as y, -- equivalent to rDAC
    rank() over (partition by D order by A desc, C) as rDAC
from df
join df2 using (A)

-- output
   A    B  C  D        E    x  rAB    y  rDAC
0  c  1.0  3  X  coconut  8.0  8.0  1.0   1.0
1  c  3.0  9  X  coconut  6.0  6.0  2.0   2.0
2  b  1.0  2  X   banana  5.0  5.0  3.0   3.0
3  b  3.0  8  X   banana  3.0  3.0  4.0   4.0
4  a  1.0  1  X    apple  2.0  2.0  5.0   5.0
5  c  2.0  6  Y  coconut  7.0  7.0  1.0   1.0
6  b  2.0  5  Y   banana  4.0  4.0  2.0   2.0
7  a  NaN  4  Y    apple  NaN  NaN  3.0   3.0
8  a  3.0  7  Y    apple  1.0  1.0  4.0   4.0
```

当有歧义时（例如包含 join 语句），可以列名前可添加表名来消除歧义。比如上面的例子可以写成 `rank_by(D, '-A, df.C')` 如果 `df2`也含有列`C`。

```
select *,
    m_max(B, 2, pb:=D, ob:='C') as max_asc,
    m_max(B, 2, pb:=D, ob:='-C') as max_desc,
from df

-- output
   A    B  C  D  max_asc  max_desc
0  c  3.0  9  X      3.0       NaN
1  b  3.0  8  X      3.0       3.0
2  c  1.0  3  X      1.0       3.0
3  b  1.0  2  X      1.0       1.0
4  a  1.0  1  X      NaN       1.0
5  a  3.0  7  Y      3.0       NaN
6  c  2.0  6  Y      2.0       3.0
7  b  2.0  5  Y      NaN       2.0
8  a  NaN  4  Y      NaN       NaN
```

### #行业市值中性化 c_neutralize 的使用

1. 为什么求出来基本全是 NaN值呢？答：`c_neutralize(y, industry_level1_code, market_cap)` 中传入的因子值是 `y` (右端向量），通过`industry_level1_code` 获取的dummy矩阵及取对数后的市值（以及为constant添加的常向量1）共同组成 `X`，然后做的线性回归。当 `y`, `X` 中有任何元素为NaN时求线性方程时就会全部为NaN。所以算之前需要先把 NaN **过滤掉或者填充**，一般`y`很有可能含有 NaN，比如 `y = m_avg(close, 5)`。
2. `c_neutralize`采用的算法：`def process_factor(factor): median = np.median(factor) mad = np.median(abs(factor - median)) mad *= 3*1.4826 clipped = factor.clip(median - mad, median + mad) # pandas std() has ddof=1, while numpy std() has ddof=0 return (clipped - clipped.mean()) / clipped.std(ddof=1) def sm_resid(data): X = pd.get_dummies(data['industry_level1_code']).astype('float64') # X = X.reindex(columns=dummy_cols) X['log_marketcap'] = np.log(data['total_market_cap']) y = process_factor(data['pb']) X = sm.add_constant(X) # intercept term model = sm.OLS(y, X) results = model.fit(method='pinv') return pd.DataFrame(results.resid, index=data.index) def np_resid(data): X = pd.get_dummies(data['industry_level1_code']).astype('float64') # X = X.reindex(columns=dummy_cols) X['log_marketcap'] = np.log(data['total_market_cap']) y = process_factor(data['pb']) beta, _, _, _ = np.linalg.lstsq(X, y, rcond=None) y_pred = X.dot(beta) return pd.DataFrame(y - y_pred, index=data.index) t1 = time.time() df['sm_resid'] = df.groupby('date').apply(sm_resid).reset_index(level=0, drop=True)`使用例子和对比参见: https://bigquant.com/codeshare/5739e696-fd64-480c-95ec-793ea9ff889c
3. 如果想自己处理 factor 后再只算个残差， 可以使用 `c_neutralize_resid(y, industry_level1_code, log_marketcap)` 函数 （`y = processed_factor`）。

### #缺失值填充/替换

当分区后的数据含有NA值时，填充其值为前一个非NA值：

```
select 
    instrument, date, 
    last(columns(* exclude (date, instrument)) ignore nulls) 
        over (partition by instrument order by date rows between 
              unbounded preceding and current row) as 'columns(*)' 
from cn_stock_bar1d
where date >= '2023-01-01' 
order by instrument, date
```

`columns(* exclude (date, instrument))`   会依次扩展成每一个非 `date`  和 `instrument`  的列，最好减少不需要操作的数据。`as 'columns(*)’` 会保存处理后的数据成原始的列名，`as 'columns(*)_suffix_name’` 的话会把处理后的数据依次存成原列名加上后缀名（`_suffix_name`）的列名。

填充前 填充后

类似的如果想批量替换NA值为其他值，比如 0，可以把 `last` 函数替换成 `ifnull` 函数：

```
select 
    instrument, date, 
    ifnull(columns(* exclude (date, instrument, name)), 0) as 'columns(*)' 
from cn_stock_bar1d
where date >= '2023-01-01' 
order by instrument, date
```

把当天`open`, `close`为空的值填充为当天所有股票的中位数：

```
select 
    instrument, date, 
    ifnull(columns(['close', 'open']), 
           c_median(columns(['close', 'open']))) as 'columns(*)' 
from cn_stock_bar1d
where date >= '2023-01-01'
order by instrument, date
```

### #计算连续上涨天数，最近一次“xxx”至今天数

`m_consecutive_true_count(expr)`可以用于计算该类问题。该函数会计算 `expr` 从当前行起往前取连续为 `true` 的数量, `expr` 为 `NULL` 的行其对应结果为 `NULL`.

```
expr  m_consecutive_true_count(expr)
 0     0
 0     0
 0     0
 1     1
 1     2
 0     0
 1     1
 1     2
 1     3
 0     0
```

可以看出该特性可以帮助算出连续性因子，比如： **连续上涨天数**，**最近一次涨停距今天数**（通过取 `expr = not limit_up`）。

```
select instrument, date, close,
    m_consecutive_rise_count(close) as rise_count,
    m_consecutive_true_count(close > m_lag(close, 1)) as rise_count2,
    if(price_limit_status = 3, 1, 0) as limit_up,
    1 - limit_up as not_limit_up,
    m_consecutive_true_count(not_limit_up) as days_since_last_limit_up,
from cn_stock_bar1d
join cn_stock_status
using (date, instrument)
where date >= '2024-08-01' and instrument='000062.SZ'
--qualify m_cumsum(limit_up)>0
order by instrument, date

-- output
   instrument       date       close  rise_count  rise_count2  limit_up  not_limit_up  days_since_last_limit_up
0   000062.SZ 2024-08-01   71.737065           0          NaN         0             1                       1.0
1   000062.SZ 2024-08-02   69.989318           0          0.0         0             1                       2.0
2   000062.SZ 2024-08-05   67.129369           0          0.0         0             1                       3.0
3   000062.SZ 2024-08-06   68.241571           1          1.0         0             1                       4.0
4   000062.SZ 2024-08-07   67.764913           0          0.0         0             1                       5.0
5   000062.SZ 2024-08-08   68.321014           1          1.0         0             1                       6.0
6   000062.SZ 2024-08-09   68.797673           2          2.0         0             1                       7.0
7   000062.SZ 2024-08-12   67.923799           0          0.0         0             1                       8.0
8   000062.SZ 2024-08-13   68.321014           1          1.0         0             1                       9.0
9   000062.SZ 2024-08-14   69.194888           2          2.0         0             1                      10.0
-- 对于我们给定选取的数据集里面，可能不知道上一次涨停是什么时候，此时 days_since_last_limit_up 可以理解为至少隔了这么多交易日
-- 可以添加 qualify m_cumsum(limit_up)>0 来过滤掉这部分“不准确”的结果
10  000062.SZ 2024-08-15   76.106432           3          3.0         1             0                       0.0
11  000062.SZ 2024-08-16   83.732964           4          4.0         1             0                       0.0
12  000062.SZ 2024-08-19   92.074483           5          5.0         1             0                       0.0
13  000062.SZ 2024-08-20  101.289876           6          6.0         1             0                       0.0
14  000062.SZ 2024-08-21  111.458585           7          7.0         1             0                       0.0
15  000062.SZ 2024-08-22  122.580611           8          8.0         1             0                       0.0
16  000062.SZ 2024-08-23  134.814839           9          9.0         1             0                       0.0
17  000062.SZ 2024-08-26  148.320156          10         10.0         1             0                       0.0
18  000062.SZ 2024-08-27  163.176004          11         11.0         1             0                       0.0
19  000062.SZ 2024-08-28  179.461827          12         12.0         1             0                       0.0
20  000062.SZ 2024-08-29  186.293929          13         13.0         0             1                       1.0
21  000062.SZ 2024-08-30  204.963043          14         14.0         1             0                       0.0
22  000062.SZ 2024-09-02  225.459347          15         15.0         1             0                       0.0
23  000062.SZ 2024-09-03  248.021171          16         16.0         1             0                       0.0
24  000062.SZ 2024-09-04  272.807399          17         17.0         1             0                       0.0
25  000062.SZ 2024-09-05  300.056362          18         18.0         1             0                       0.0
26  000062.SZ 2024-09-06  330.085831          19         19.0         1             0                       0.0
27  000062.SZ 2024-09-09  297.116970           0          0.0         0             1                       1.0
28  000062.SZ 2024-09-10  267.405273           0          0.0         0             1                       2.0
29  000062.SZ 2024-09-11  272.330741           1          1.0         0             1                       3.0
30  000062.SZ 2024-09-12  260.175956           0          0.0         0             1                       4.0
31  000062.SZ 2024-09-13  234.198082           0          0.0         0             1                       5.0
32  000062.SZ 2024-09-18  245.320107           1          1.0         0             1                       6.0
```

注意到收盘价连续上涨天数因子也可以使用`m_consecutive_rise_count(close)`计算，但第一天的结果为0。而使用 `m_consecutive_true_count(close > m_lag(close, 1))` 计算的因子由于 `m_lag(close, 1)` 的原因导致第一天 `close > m_lag(close, 1)` 为`NULL`，从而其其第一天的结果也为`NULL`。性能上直接使用`m_consecutive_rise_count` 会快一些因为不需要算 `m_lag(close, 1)`。

### #dai.query 查分区表必须带 filters（本地实测 2026-09）

`dai.query(sql)` 不带 `filters` 查分区表（如 `cn_stock_bar1d` / `cn_stock_index_bar1d`）会直接被拒绝：

```
Permission Error: 请在查询表 xxx 时使用 filters 参数指定分区范围（一般为 date 或 instrument）：
dai.query(sql, filters={"date": ["2020-01-01", "2020-02-01"]})。
若确需全表扫描，请设置 full_db_scan 参数：dai.query(sql, full_db_scan=True)
```

- **正常做法**：所有查询都传 `filters={"date": [start, end]}`（SQL 里的 `where` 不能替代 filters，分区裁剪发生在 SQL 之外）
- `full_db_scan=True` 仅在确需全表时用，慢且占配额
- 另实测：指数日线正确表名为 `cn_stock_index_bar1d`；`cn_index_bar1d` **不存在**（Catalog Error）

