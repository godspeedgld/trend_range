# DAI SQL 函数列表

> 来源：https://bigquant.com/wiki/doc/Rceb2JQBdS（本地 HTML 快照转换；远程为最新版本，如需更新访问链接）

DAI SQL 函数列表


##### 操作符
| 函数名称 | 描述 | 例子 |
|---|---|---|
| `+` | 加法 | `1 + 2 = 3; '2023-1-1'::DATE + INTERVAL 1 MONTH = '2023-2-1'::DATE` |
| `-` | 减法 | `1 - 2 = -1; '2023-1-1'::DATE - INTERVAL 1 MONTH = '2022-12-1'::DATE` |
| `*` | 乘法 | `1 * 2 = 2` |
| `/` | 除法 | `7 / 2 = 3.5` |
| `//` | 整数除法 | `7 // 2 = 3` |
| `%` | 取模 | `26 % 3 = 2` |
| `**` | 指数 | `2 ** 3 = 8` |
| `^` | 指数, `**` 的别名 | `2 ^ 3 = 8` |
| `&` | 按位与 | `1 & 2 = 0` |
| `\|` | 按位或 | `1 \| 2 = 3` |
| `<<` | 位左移 | `1 << 3 = 8` |
| `>>` | 位右移 | `8 >> 2 = 2` |
| `~` | 按位取反 | `~15 = -16` |
| `!` | 阶乘 | `4! = 24` |
| `string ^@ search_string` | `starts_with` 的别名 | `'abc' ^@ 'a' = true` |
| `string \|\| string` | 字符串连接 | `'Big' \|\| 'Quant' = 'BigQuant'` |
| `string[index]` | `array_extract` 的别名 | `'BigQuant'[4] = 'Q'` |
| `string[begin:end]` | `array_slice` 的别名，如果没有参数则返回 `NULL` | `'BigQuant'[:4] = 'BigQ'` |
| `l1 @> l2` | A ⊃ B? 后者是否为前者子集, `list_has_all(l1, l2)` 的别名 | `[1,2,3] @> [2,null] = true` |
| `l1 <@ l2` | A ⊂ B? 前者是否为后者子集, `list_has_all(l2, l1)` 的别名 | `[1,2,null] <@ [1,2] = true` |
| `l1 && l2` | A ∩ B? 两者是否有交集, `list_has_any(l1, l2)` 的别名 | `[1, 2, 3] && [2, 3, 4] = true` |
| `string LIKE pattern` | `string` 是否匹配 `pattern`，支持通配符 `%` 和 `_` | `'hello' LIKE '%lo' = true` |
| `string NOT LIKE pattern` | `string` 是否不匹配 `pattern`，支持通配符 `%` 和 `_` | `'hello' NOT LIKE '%lo' = false` |
| `string ILIKE pattern` | `string` 是否匹配 `pattern`，支持通配符 `%` 和 `_`，忽略大小写 | `'hello' ILIKE '%LO' = true` |
| `string NOT ILIKE pattern` | `string` 是否不匹配 `pattern`，支持通配符 `%` 和 `_`，忽略大小写 | `'hello' NOT ILIKE '%LO' = false` |
| `string ~~ pattern` | Postgres-style, 等同于 `LIKE` | `'hello' ~~ '%lo' = true` |
| `string !~~ pattern` | Postgres-style, 等同于 `NOT LIKE` | `'hello' !~~ '%lo' = false` |
| `string ~~* pattern` | Postgres-style, 等同于 `ILIKE` | `'hello' ~~* '%LO' = true` |
| `string !~~* pattern` | Postgres-style, 等同于 `NOT ILIKE` | `'hello' !~~* '%LO' = false` |
| `string LIKE pattern ESCAPE escape_character` | `string` 是否匹配 `pattern`，使用 `escape_character` 转义通配符 `%` 和 `_` | `'xlo' LIKE '$_lo' ESCAPE '$' = false; '_lo' LIKE '$_lo' ESCAPE '$' = true` |
| `string NOT LIKE pattern ESCAPE escape_character` | `string` 是否不匹配 `pattern`，使用 `escape_character` 转义通配符 `%` 和 `_` | `'xlo' NOT LIKE '$_lo' ESCAPE '$' = true; '_lo' NOT LIKE '$_lo' ESCAPE '$' = false` |
| `string ILIKE pattern ESCAPE escape_character` | `string` 是否匹配 `pattern`，使用 `escape_character` 转义通配符 `%` 和 `_`，忽略大小写 | `'xlo' ILIKE '$_LO' ESCAPE '$' = false; '_lo' ILIKE '$_LO' ESCAPE '$' = true` |
| `string NOT ILIKE pattern ESCAPE escape_character` | `string` 是否不匹配 `pattern`，使用 `escape_character` 转义通配符 `%` 和 `_`，忽略大小写 | `'xlo' NOT ILIKE '$_LO' ESCAPE '$' = true; '_lo' NOT ILIKE '$_LO' ESCAPE '$' = false` |
| `string SIMILAR TO pattern` | 使用 regex 判断 `string` 是否匹配 `pattern` | `'hello' SIMILAR TO '[xh].*lo' = true` |
| `string NOT SIMILAR TO pattern` | 使用 regex 判断 `string` 是否不匹配 `pattern` | `'hello' NOT SIMILAR TO '[xh].*lo' = false` |
| `string ~ pattern` | POSIX-style, 等同于 `SIMILAR TO` | `'hello' ~ '[xh].*lo' = true` |
| `string !~ pattern` | POSIX-style, 等同于 `NOT SIMILAR TO` | `'hello' !~ '[xh].*lo' = false` |

##### 标量函数
| 函数名称 | 描述 | 例子 |
|---|---|---|
| abs | 绝对值 | abs(-17.4) |
| acos | 计算 x 的反余弦 | acos(0.5) |
| acosh | 计算 x 的反双曲余弦 | acosh(2.3) |
| age | 减去参数，得到两个时间戳之间的时间差 | age(TIMESTAMP '2001-04-10', TIMESTAMP '1992-09-20') |
| aggregate | 对列表元素执行聚合函数名称 | aggregate([1, 2, NULL], 'min') |
| alias | 返回给定表达式的名称 | alias(42 + 1) |
| apply | 返回一个列表，该列表是将 lambda 函数应用于输入列表的每个元素的结果。有关更多详细信息，请参阅 Lambda 函数部分 | apply([1, 2, 3], x -> x + 1) |
| array_aggr | 对列表元素执行聚合函数名称 | array_aggr([1, 2, NULL], 'min') |
| array_aggregate | 对列表元素执行聚合函数名称 | array_aggregate([1, 2, NULL], 'min') |
| array_apply | 返回一个列表，该列表是将 lambda 函数应用于输入列表的每个元素的结果。有关更多详细信息，请参阅 Lambda 函数部分 | array_apply([1, 2, 3], x -> x + 1) |
| array_cat | 连接两个数组, list_concat 的别名 | array_cat([1,2], [3,4]) = [1,2,3,4] |
| array_concat | 连接两个数组, list_concat 的别名 | array_concat([1,2], [3,4]) = [1,2,3,4] |
| array_contains | 判断数组是否包含元素, list_contains 的别名 | array_contains([1,2,null], 2) = true |
| array_cosine_distance | 计算两个相同大小的数组之间的余弦距离。数组元素不能为 NULL。数组可以具有任意大小，只要两个参数的大小相同即可。 | array_cosine_distance([1, 2, 3], [1, 2, 3]) |
| array_cosine_similarity | 计算两个相同大小的数组之间的余弦相似度。数组元素不能为 NULL。数组可以具有任意大小，只要两个参数的大小相同即可。 | array_cosine_similarity([1, 2, 3], [1, 2, 3]) |
| array_cross_product | 计算两个大小为 3 的数组的叉积。数组元素不能为 NULL。 | array_cross_product([1, 2, 3], [1, 2, 3]) |
| array_distance | 计算两个相同大小的数组之间的距离。数组元素不能为 NULL。数组可以具有任意大小，只要两个参数的大小相同即可。 | array_distance([1, 2, 3], [1, 2, 3]) |
| array_distinct | 从列表中删除所有重复项和 NULL。不保留原始顺序 | array_distinct([1, 1, NULL, -3, 1, 5]) |
| array_dot_product | 计算两个相同大小的数组之间的内积。数组元素不能为 NULL。数组可以具有任意大小，只要两个参数的大小相同即可。 | array_dot_product([1, 2, 3], [1, 2, 3]) |
| array_extract | 提取数组中的元素 (从 1 开始), 可缩写成 array[index] | array_extract([1,2,3], 2) = 2 |
| array_filter | 根据输入列表中 lambda 函数返回 true 的元素构造一个列表 | array_filter([3, 4, 5], x -> x > 4) |
| array_grade_up | 返回其排序位置的索引。 | array_grade_up([3, 6, 1, 2]) |
| array_has | 判断数组是否包含元素, list_contains 的别名 | array_has([1,2,null], 2) = true |
| array_has_all | 如果 l2 的所有元素都在 l1 中，则返回 true。 NULL 被忽略。 | array_has_all([1, 2, 3], [2, 3]) |
| array_has_any | 如果列表有任何共同元素，则返回 true。 NULL 被忽略。 | array_has_any([1, 2, 3], [2, 3, 4]) |
| array_indexof | 返回数组中元素的索引 (从 1 开始), list_position 的别名 | array_indexof([1,2,3], 2) = 2 |
| array_inner_product | 计算两个相同大小的数组之间的内积。数组元素不能为 NULL。数组可以具有任意大小，只要两个参数的大小相同即可。 | array_inner_product([1, 2, 3], [1, 2, 3]) |
| array_length | 返回数组长度, len 的别名 | array_length([1,2,3]) = 3 |
| array_negative_dot_product | 计算两个相同大小的数组之间的负内积。数组元素不能为 NULL。数组可以具有任意大小，只要两个参数的大小相同即可。 | array_negative_dot_product([1, 2, 3], [1, 2, 3]) |
| array_negative_inner_product | 计算两个相同大小的数组之间的负内积。数组元素不能为 NULL。数组可以具有任意大小，只要两个参数的大小相同即可。 | array_negative_inner_product([1, 2, 3], [1, 2, 3]) |
| array_position | 返回数组中元素的索引 (从 1 开始), list_position 的别名 | array_position([1,2,3], 2) = 2 |
| array_reduce | 返回单个值，该值是将 lambda 函数应用于输入列表的每个元素的结果，从第一个元素开始，然后重复将 lambda 函数应用于上一个应用程序的结果和列表的下一个元素。 | array_reduce([1, 2, 3], (x, y) -> x + y) |
| array_resize | 调整数组大小, list_resize 的别名 | array_resize([1,2,3], 5) = [1,2,3,null,null] |
| array_reverse_sort | 以相反的顺序对列表的元素进行排序 | array_reverse_sort([3, 6, 1, 2]) |
| array_select | 根据index_list选择的元素返回列表。 | array_select([10, 20, 30, 40], [1, 4]) |
| array_slice | 使用切片约定提取子列表。接受负值。 | array_slice([4, 5, 6], 2, 3) |
| array_slice | List_slice带有添加步长的功能。 | array_slice([4, 5, 6], 1, 3, 2) |
| array_sort | 对列表的元素进行排序 | array_sort([3, 6, 1, 2]) |
| array_transform | 返回一个列表，该列表是将 lambda 函数应用于输入列表的每个元素的结果。有关更多详细信息，请参阅 Lambda 函数部分 | array_transform([1, 2, 3], x -> x + 1) |
| array_unique | 计算列表中的唯一元素 | array_unique([1, 1, NULL, -3, 1, 5]) |
| array_value | 创建一个包含参数值的数组。 | array_value(4, 5, 6) |
| array_where | 返回带有booleans booleans的列表，将bask_list应用于value_list的掩码。 | array_where([10, 20, 30, 40], [true, false, false, true]) |
| array_zip | Zips K列出了一个新列表，其长度将是最长列表的长度。它的元素是每个列表list_1，…，list_k的k元素的结构，丢失的元素被null替换。如果设置了截断，所有列表均截断为最小的列表长度。 | array_zip([1, 2], [3, 4], [5, 6]) |
| ascii | 返回一个整数，表示字符串第一个字符的 Unicode 代码点 | ascii('Ω') |
| asin | 计算 x 的反正弦 | asin(0.5) |
| asinh | 计算 x 的反双曲正弦 | asinh(0.5) |
| atan | 计算 x 的反正切 | atan(0.5) |
| atan2 | 计算反正切 (y, x) | atan2(1.0, 0.0) |
| atanh | 计算 x 的反双曲 tan | atanh(0.5) |
| bar | bar(x, min, max, width)，绘制一条带，其宽度与 (x - min) 成正比，并且当 x = max 时等于宽度字符。宽度默认为80 | bar(5, 0, 20, 10) |
| base64 | 将 blob 转换为 base64 编码的字符串 | base64('A'::blob) |
| bin | 将值转换为二进制表示形式 | bin(42) |
| bit_count | 返回设置的位数 | bit_count(31) |
| bit_length | 返回字符串位长度 | bit_length('xyz') = 24 |
| bit_position | 返回位内指定子字符串的第一个起始索引，如果不存在则返回零。第一个（最左边）位索引为 1 | bit_position('010'::BIT, '1110101'::BIT) |
| bitstring | 填充位串直到指定长度 | bitstring('1010'::BIT, 7) |
| can_cast_implicitly | 是否可以从源类型隐式转换为其他类型 | can_cast_implicitly(NULL::INTEGER, NULL::BIGINT) |
| cardinality | 返回地图的大小（或地图中的条目数） | cardinality( map([4, 2], ['a', 'b']) ); |
| cbrt | 返回 x 的立方根 | cbrt(8) |
| ceil | 将数字向上舍入 | ceil(17.4) |
| ceiling | 将数字向上舍入 | ceiling(17.4) |
| century | 从日期或时间戳中提取世纪部分 | century(timestamp '2021-08-03 11:59:44.123456') |
| chr | 返回与 ASCII 代码值或 Unicode 代码点对应的字符 | chr(65) |
| concat | 连接字符串 | concat('hello', ' ', '🌎') = 'hello 🌎' |
| concat_ws | 连接字符串, 以指定分隔符分隔 | concat_ws(', ', 'apple', 'banana', 'cherry') = 'apple, banana, cherry' |
| constant_or_null | 如果arg2为null，请返回null。否则，返回arg1。 | constant_or_null(42, NULL) |
| contains | 检查map是否包含给定键。 | contains(MAP {'key1': 10, 'key2': 20, 'key3': 30}, 'key2') |
| contains | 如果列表包含元素，则返回true。 | contains([1, 2, NULL], 1) |
| contains | 如果在字符串中找到search_string，则返回true。 | contains('abc', 'a') |
| cos | 计算 x 的余弦 | cos(90) |
| cosh | 计算 x 的双曲余弦 | cosh(1) |
| cot | 计算 x 的余切 | cot(0.5) |
| create_sort_key | 基于一组输入参数和排序限定符构造二进制可比较的排序键 | create_sort_key('A', 'DESC') |
| current_database | 返回当前活动数据库的名称 | current_database() |
| current_localtime | 返回当前时间 | current_localtime() |
| current_localtimestamp | 返回当前时间戳 | current_localtimestamp() |
| current_query | 以字符串形式返回当前查询 | current_query() |
| current_schema | 返回当前活动模式的名称。默认为主 | current_schema() |
| current_schemas | 返回模式列表。传递 True 参数以包含隐式模式 | current_schemas(true) |
| current_setting | 返回配置设置的当前值 | current_setting('access_mode') |
| currval | 返回序列的当前值 | currval('my_sequence_name') |
| cut | 将 arg 的值按照 bin_cut_points 进行分桶, 返回值为 arg 所在的桶。bin_cut_points 为一个列表, 列表中的元素为分桶的边界值 | cut(close, [-inf, 70, 80, 90, inf]) |
| damerau_levenshtein | 编辑距离的扩展还包括相邻字符的换位作为允许的编辑操作。换句话说，将一个字符串更改为另一个字符串所需的最少编辑操作（插入、删除、替换或转置）次数。区分大小写 | damerau_levenshtein('hello', 'world') |
| date_diff | 时间戳之间的分区边界数 | date_diff('hour', TIMESTAMPTZ '1992-09-30 23:59:59', TIMESTAMPTZ '1992-10-01 01:58:00') |
| date_part | 获取子字段（相当于提取） | date_part('minute', TIMESTAMP '1992-09-20 20:38:40') |
| date_sub | 时间戳之间完整分区的数量 | date_sub('hour', TIMESTAMPTZ '1992-09-30 23:59:59', TIMESTAMPTZ '1992-10-01 01:58:00') |
| date_trunc | 截断至指定精度 | date_trunc('hour', TIMESTAMPTZ '1992-09-20 20:38:40') |
| datediff | 时间戳之间的分区边界数 | datediff('hour', TIMESTAMPTZ '1992-09-30 23:59:59', TIMESTAMPTZ '1992-10-01 01:58:00') |
| datepart | 获取子字段（相当于提取） | datepart('minute', TIMESTAMP '1992-09-20 20:38:40') |
| datesub | 时间戳之间完整分区的数量 | datesub('hour', TIMESTAMPTZ '1992-09-30 23:59:59', TIMESTAMPTZ '1992-10-01 01:58:00') |
| datetrunc | 截断至指定精度 | datetrunc('hour', TIMESTAMPTZ '1992-09-20 20:38:40') |
| day | 从日期或时间戳中提取日期部分 | day(timestamp '2021-08-03 11:59:44.123456') |
| dayname | 工作日的（英文）名称 | dayname(TIMESTAMP '1992-03-22') |
| dayofmonth | 从日期或时间戳中提取这是某月的第几天 | dayofmonth(timestamp '2021-08-03 11:59:44.123456') |
| dayofweek | 从日期或时间戳中提取这是某星期的第几天 | dayofweek(timestamp '2021-08-03 11:59:44.123456') |
| dayofyear | 从日期或时间戳中提取这是某年的第几天 | dayofyear(timestamp '2021-08-03 11:59:44.123456') |
| decade | 从日期或时间戳中提取十年部分 | decade(timestamp '2021-08-03 11:59:44.123456') |
| decode | 将 blob 转换为 varchar。如果 blob 不是有效的 utf-8，则失败 | decode('\xC3\xBC'::BLOB) |
| degrees | 将弧度转换为度数 | degrees(pi()) |
| editdist3 | 将一个字符串更改为另一个字符串所需的最少单字符编辑（插入、删除或替换）次数。区分大小写 | editdist3('big','db') |
| element_at | 返回包含给定键的值的列表，如果映射中不包含该键，则返回空列表。第二个参数中提供的键的类型必须与映射键的类型匹配，否则将返回错误 | element_at(map(['key'], ['val']), 'key') |
| encode | 将 varchar 转换为 blob。将 utf-8 字符转换为文字编码 | encode('my_string_with_ü') |
| ends_with | 判断字符串是否以指定后缀结尾, suffix 的别名 | ends_with('hello world', 'world') = true |
| enum_code | 返回支持给定枚举值的数值 | enum_code('happy'::mood) |
| enum_first | 返回输入枚举类型的第一个值 | enum_first(NULL::mood) |
| enum_last | 返回输入枚举类型的最后一个值 | enum_last(NULL::mood) |
| enum_range | 以数组形式返回输入枚举类型的所有值 | enum_range(NULL::mood) |
| enum_range_boundary | 以数组形式返回两个给定枚举值之间的范围。这些值必须是相同的枚举类型。当第一个参数为 NULL 时，结果从枚举类型的第一个值开始。当第二个参数为NULL时，结果以枚举类型的最后一个值结束 | enum_range_boundary(NULL, 'happy'::mood) |
| epoch | 从时间类型中提取纪元分量 | epoch(timestamp '2021-08-03 11:59:44.123456') |
| epoch_ms | 从时间类型中提取以毫秒为单位的纪元分量 | epoch_ms(timestamp '2021-08-03 11:59:44.123456') |
| epoch_ns | 从时间类型中提取纳秒级的纪元分量 | epoch_ns(timestamp '2021-08-03 11:59:44.123456') |
| epoch_us | 从时间类型中提取以微秒为单位的纪元分量 | epoch_us(timestamp '2021-08-03 11:59:44.123456') |
| equi_width_bins | 生成 min 和 max 之间的 bin_count 等宽 bin。如果启用 Nice_rounding 会使数字更具可读性/锯齿更少 | equi_width_bins(0, 10, 2, true) |
| era | 从日期或时间戳中提取时代部分 | era(timestamp '2021-08-03 11:59:44.123456') |
| error | 抛出给定的错误消息 | error('access_mode') |
| even | 通过从零舍入将 x 舍入到下一个偶数 | even(2.9) |
| exp | 计算 e 的 x 次方 | exp(1) |
| factorial | x 的阶乘。计算当前整数与其以下所有整数的乘积 | 4! |
| filter | 根据输入列表中 lambda 函数返回 true 的元素构造一个列表 | filter([3, 4, 5], x -> x > 4) |
| flatten | 将嵌套列表展平一层 | flatten([[1, 2, 3], [4, 5]]) |
| floor | 将数字向下舍入 | floor(17.4) |
| format | 使用 fmt 语法格式化字符串 | format('Benchmark "{}" took {} seconds', 'CSV', 42) |
| formatReadableDecimalSize | 将字节转换为人类可读的表示形式（例如 16000 -> 16.0 KB） | formatReadableDecimalSize(1000 * 16) |
| formatReadableSize | 将字节转换为人类可读的表示形式（例如 16000 -> 15.6 KiB） | formatReadableSize(1000 * 16) |
| format_bytes | 将字节转换为人类可读的表示形式（例如 16000 -> 15.6 KiB） | format_bytes(1000 * 16) |
| from_base64 | 将base64编码的字符串转换为字符串 | from_base64('QQ==') |
| from_binary | 将值从二进制表示形式转换为 blob | from_binary('0110') |
| from_hex | 将值从十六进制表示形式转换为 blob | from_hex('2A') |
| gamma | (x-1) 阶乘的插值（因此允许小数输入） | gamma(5.5) |
| gcd | 计算 x 和 y 的最大公约数 | gcd(42, 57) |
| gen_random_uuid | 返回类似于以下内容的随机 UUID：eeccb8c5-9943-b2bb-bb5e-222f4e14b687 | gen_random_uuid() |
| generate_series | 创建开始和停止之间的值列表 - 包含停止参数 | generate_series(2, 5, 3) |
| get_bit | 从位串中提取第 n 位；第一个（最左边）位索引为 0 | get_bit('0110010'::BIT, 2) |
| get_current_timestamp | 返回当前时间戳 | get_current_timestamp() |
| grade_up | 返回其排序位置的索引。 | grade_up([3, 6, 1, 2]) |
| greatest | 返回输入参数集的最大值 | greatest(42, 84) |
| greatest_common_divisor | 计算 x 和 y 的最大公约数 | greatest_common_divisor(42, 57) |
| hamming | 2 个长度相等的字符串中不同字符的位置数。区分大小写 | hamming('big','dog') |
| hash | 返回一个带有该值的哈希值的整数。请注意，这不是加密哈希 | hash('🌎') |
| hex | 将值转换为十六进制表示形式 | hex(42) |
| hour | 从日期或时间戳中提取小时部分 | hour(timestamp '2021-08-03 11:59:44.123456') |
| ilike_escape | 同 string ILIKE pattern ESCAPE escape_character | ilike_escape('A%c', 'a$%c', '$') = true |
| in_search_path | 返回数据库/模式是否在搜索路径中 | in_search_path('memory', 'main') |
| instr | 返回 haystack 中第一次出现的针的位置，从 1 开始计数。如果没有找到匹配则返回 0 | instr('test test','es') |
| is_histogram_other_bin | 提供的值是否是直方图“其他”bin（用于不属于任何提供的bin的值） | is_histogram_other_bin(v) |
| isfinite | 如果浮点值有限则返回 true，否则返回 false | isfinite(5.5) |
| isinf | 如果浮点值无穷大则返回 true，否则返回 false | isinf('Infinity'::float) |
| isnan | 如果浮点值不是数字，则返回 true，否则返回 false | isnan('NaN'::FLOAT) |
| isodow | 从日期或时间戳中提取 isodow 组件 | isodow(timestamp '2021-08-03 11:59:44.123456') |
| isoyear | 从日期或时间戳中提取等年部分 | isoyear(timestamp '2021-08-03 11:59:44.123456') |
| jaccard | 两个字符串之间的杰卡德相似度。不同的情况被认为是不同的。返回 0 到 1 之间的数字 | jaccard('big','dog') |
| jaro_similarity | 两个字符串之间的 Jaro 相似度。不同的情况被认为是不同的。返回 0 到 1 之间的数字 | jaro_similarity('big', 'bigdb', 0.5) |
| jaro_winkler_similarity | 两个字符串之间的 Jaro-Winkler 相似度。不同的情况被认为是不同的。返回 0 到 1 之间的数字 | jaro_winkler_similarity('big', 'bigdb', 0.5) |
| julian | 从日期或时间戳中提取儒略日数 | julian(timestamp '2006-01-01 12:00') |
| last_day | 返回该月的最后一天 | last_day(TIMESTAMP '1992-03-22 01:02:03.1234') |
| lcase | 返回小写字符串, lower 的别名 | lcase('HELLO WORLD') = 'hello world' |
| lcm | 计算 x 和 y 的最小公倍数 | lcm(42, 57) |
| least | 返回输入参数集的最小值 | least(42, 84) |
| least_common_multiple | 计算 x 和 y 的最小公倍数 | least_common_multiple(42, 57) |
| left | 提取最左边的计数字符 | left('Hello🌎', 2) |
| left_grapheme | 提取最左边的计数字素簇 | left_grapheme('🤦🏼‍♂️🤦🏽‍♀️', 1) |
| len | 返回字符串字符长度或列表长度, length 的别名 | len('hello🌎') = 6 |
| length | 返回字符串字符长度或列表长度 | length('hello🌎') = 6 |
| length_grapheme | 返回字素簇的长度 | length_grapheme('🪐🌎') = 2 |
| levenshtein | 将一个字符串更改为另一个字符串所需的最少单字符编辑（插入、删除或替换）次数。区分大小写 | levenshtein('big','db') |
| lgamma | 计算伽玛函数的对数 | lgamma(2) |
| like_escape | 同 string LIKE pattern ESCAPE escape_character | like_escape('a%c', 'a$%c', '$') = true |
| list_aggr | 对列表元素执行聚合函数名称 | list_aggr([1, 2, NULL], 'min') |
| list_aggregate | 对列表元素执行聚合函数名称 | list_aggregate([1, 2, NULL], 'min') |
| list_apply | 返回一个列表，该列表是将 lambda 函数应用于输入列表的每个元素的结果。有关更多详细信息，请参阅 Lambda 函数部分 | list_apply([1, 2, 3], x -> x + 1) |
| list_cat | 连接两个列表, list_concat 的别名 | list_cat([1,2], [3,4]) = [1,2,3,4] |
| list_concat | 连接两个列表 | list_concat([1,2], [3,4]) = [1,2,3,4] |
| list_contains | 判断列表是否包含元素 | list_contains([1,2,null], 2) = true |
| list_cosine_distance | 计算两个列表之间的余弦距离 | list_cosine_distance([1, 2, 3], [1, 2, 3]) |
| list_cosine_similarity | 计算两个列表之间的余弦相似度 | list_cosine_similarity([1, 2, 3], [1, 2, 3]) |
| list_distance | 计算两个列表之间的距离 | list_distance([1, 2, 3], [1, 2, 3]) |
| list_distinct | 从列表中删除所有重复项和 NULL。不保留原始顺序 | list_distinct([1, 1, NULL, -3, 1, 5]) |
| list_dot_product | 计算两个列表之间的内积 | list_dot_product([1, 2, 3], [1, 2, 3]) |
| list_element | 提取列表中的元素 (从 1 开始), list_extract 的别名 | list_element([1,2,3], 2) = 2 |
| list_extract | 提取列表中的元素 (从 1 开始), 可缩写成 list[index] | list_extract([1,2,3], 2) = 2 |
| list_filter | 根据输入列表中 lambda 函数返回 true 的元素构造一个列表 | list_filter([3, 4, 5], x -> x > 4) |
| list_grade_up | 返回其排序位置的索引。 | list_grade_up([3, 6, 1, 2]) |
| list_has | 判断列表是否包含元素, list_contains 的别名 | list_has([1,2,null], 2) = true |
| list_has_all | 如果 l2 的所有元素都在 l1 中，则返回 true。 NULL 被忽略。 | list_has_all([1, 2, 3], [2, 3]) |
| list_has_any | 如果列表有任何共同元素，则返回 true。 NULL 被忽略。 | list_has_any([1, 2, 3], [2, 3, 4]) |
| list_indexof | list_position 的别名 | list_indexof([1,2,null,3], 7) = 0 |
| list_inner_product | 计算两个列表之间的内积 | list_inner_product([1, 2, 3], [1, 2, 3]) |
| list_negative_dot_product | 计算两个列表之间的负内积 | list_negative_dot_product([1, 2, 3], [1, 2, 3]) |
| list_negative_inner_product | 计算两个列表之间的负内积 | list_negative_inner_product([1, 2, 3], [1, 2, 3]) |
| list_pack | 创建包含参数值的列表 | list_pack(4, 5, 6) |
| list_position | 返回元素在列表中的索引 (从 1 开始) 如果有的话; 否则返回 0 | list_position([1,2,null,3], 3) = 4 |
| list_reduce | 返回单个值，该值是将 lambda 函数应用于输入列表的每个元素的结果，从第一个元素开始，然后重复将 lambda 函数应用于上一个应用程序的结果和列表的下一个元素。 | list_reduce([1, 2, 3], (x, y) -> x + y) |
| list_resize | 调整列表大小, 如果新元素未设置则为 NULL | list_resize([1,2,3], 5, 0) = [1,2,3,0,0] |
| list_reverse_sort | 以相反的顺序对列表的元素进行排序 | list_reverse_sort([3, 6, 1, 2]) |
| list_select | 根据index_list选择的元素返回列表。 | list_select([10, 20, 30, 40], [1, 4]) |
| list_slice | List_slice带有添加步长的功能。 | list_slice([4, 5, 6], 1, 3, 2) |
| list_slice | 使用切片约定提取子列表。接受负值。 | list_slice([4, 5, 6], 2, 3) |
| list_sort | 对列表的元素进行排序 | list_sort([3, 6, 1, 2]) |
| list_transform | 返回一个列表，该列表是将 lambda 函数应用于输入列表的每个元素的结果。有关更多详细信息，请参阅 Lambda 函数部分 | list_transform([1, 2, 3], x -> x + 1) |
| list_unique | 计算列表中的唯一元素 | list_unique([1, 1, NULL, -3, 1, 5]) |
| list_value | 创建包含参数值的列表 | list_value(4, 5, 6) |
| list_where | 返回带有booleans booleans的列表，将bask_list应用于value_list的掩码。 | list_where([10, 20, 30, 40], [true, false, false, true]) |
| list_zip | Zips K列出了一个新列表，其长度将是最长列表的长度。它的元素是每个列表list_1，…，list_k的k元素的结构，丢失的元素被null替换。如果设置了截断，所有列表均截断为最小的列表长度。 | list_zip([1, 2], [3, 4], [5, 6]) |
| ln | 计算 x 的自然对数 | ln(2) |
| log | 计算 x 以 b 为底的对数。 b 可以省略，在这种情况下默认为 10 | log(2, 64) |
| log10 | 计算 x 的 10 对数 | log10(1000) |
| log2 | 计算 x 的 2-log | log2(8) |
| lower | 返回小写字符串 | lower('HELLO WORLD') = 'hello world' |
| lpad | 用左侧的字符填充字符串，直到有 count 个字符 | lpad('hello', 10, '>') |
| ltrim | 删除字符串左侧出现的任何字符 | ltrim('>>>>test<<', '><') |
| make_time | 给定部分的时间 | make_time(13, 34, 27.123456) |
| make_timestamp | 给定部分的时间戳 | make_timestamp(1992, 9, 20, 13, 34, 27.123456) |
| make_timestamp_ns | 自时代以来给定纳秒的时间戳 | make_timestamp_ns(1732117793000000000) |
| make_timestamptz | 构造当前时区的时间戳 | make_timestamptz(2023, 8, 14, 13, 9, 23.123456) = 2023-08-14 13:09:23.123456+08:00 |
| map | 从一组键和值创建映射 | map(['key1', 'key2'], ['val1', 'val2']) |
| map_concat | 返回通过合并输入映射创建的映射，在键冲突时，该值是从具有该键的最后一个映射中获取的 | map_concat(map([1,2], ['a', 'b']), map([2,3], ['c', 'd'])); |
| map_contains | 检查map是否包含给定键。 | map_contains(MAP {'key1': 10, 'key2': 20, 'key3': 30}, 'key2') |
| map_entries | 以键/值列表的形式返回映射条目 | map_entries(map(['key'], ['val'])) |
| map_extract | 返回包含给定键的值的列表，如果映射中不包含该键，则返回空列表。第二个参数中提供的键的类型必须与映射键的类型匹配，否则将返回错误 | map_extract(map(['key'], ['val']), 'key') |
| map_extract_value | 如果键未包含在地图中，则返回给定键或空的值。第二个参数中提供的密钥的类型必须匹配地图键的类型，返回错误 | map_extract_value(map(['key'], ['val']), 'key') |
| map_from_entries | 返回根据数组条目创建的映射 | map_from_entries([{k: 5, v: 'val1'}, {k: 3, v: 'val2'}]); |
| map_keys | 以列表形式返回映射的键 | map_keys(map(['key'], ['val'])) |
| map_values | 以列表形式返回映射的值 | map_values(map(['key'], ['val'])) |
| md5 | 以字符串形式返回值的 MD5 哈希值 | md5('123') |
| md5_number | 以 INT128 形式返回值的 MD5 哈希值 | md5_number('123') |
| microsecond | 从日期或时间戳中提取微秒部分 | microsecond(timestamp '2021-08-03 11:59:44.123456') |
| millennium | 从日期或时间戳中提取千年部分 | millennium(timestamp '2021-08-03 11:59:44.123456') |
| millisecond | 从日期或时间戳中提取毫秒部分 | millisecond(timestamp '2021-08-03 11:59:44.123456') |
| minute | 从日期或时间戳中提取分钟部分 | minute(timestamp '2021-08-03 11:59:44.123456') |
| mismatches | 2 个长度相等的字符串中不同字符的位置数。区分大小写 | mismatches('big','dog') |
| month | 从日期或时间戳中提取月份部分 | month(timestamp '2021-08-03 11:59:44.123456') |
| monthname | 月份的（英文）名称 | monthname(TIMESTAMP '1992-09-20') |
| nanosecond | 从日期或时间戳中提取纳秒部分 | nanosecond(timestamp_ns '2021-08-03 11:59:44.123456789') => 44123456789 |
| nextafter | 返回 x 之后 y 方向的下一个浮点值 | nextafter(1::float, 2::float) |
| nextval | 返回序列的下一个值 | nextval('my_sequence_name') |
| nfc_normalize | 返回字符串的 NFC 归一化 | nfc_normalize('café cafe\u0301') = 'café café' |
| normalized_interval | 将间隔归为等效间隔 | normalized_interval(INTERVAL '30 days') |
| not_ilike_escape | 同 string NOT ILIKE pattern ESCAPE escape_character | not_ilike_escape('A%c', 'a$%c', '$') = false |
| not_like_escape | 同 string NOT LIKE pattern ESCAPE escape_character | not_like_escape('a%c', 'a$%c', '$') = false |
| now | 返回当前时间戳 | now() |
| octet_length | 返回 blob 型字符串字节长度 | octet_length('\x4a\x7f'::BLOB) = 2 |
| ord | 返回字符串第一个字符的 unicode 代码点 | ord('ü') |
| parse_dirname | 返回顶级目录名称。分隔符选项：系统、both_slash（默认）、forward_slash、反斜杠 | parse_dirname('path/to/file.csv', 'system') |
| parse_dirpath | 返回路径的头部，类似于 Python 的 os.path.dirname。分隔符选项：系统、both_slash（默认）、forward_slash、反斜杠 | parse_dirpath('path/to/file.csv', 'system') |
| parse_filename | 返回路径的最后一个组成部分，类似于 Python 的 os.path.basename。如果trim_extension为true，文件扩展名将被删除（默认为false）。分隔符选项：系统、both_slash（默认）、forward_slash、反斜杠 | parse_filename('path/to/file.csv', true, 'forward_slash') |
| parse_path | 返回路径中的组件列表（目录和文件名），类似于 Python 的 pathlib.PurePath::parts。分隔符选项：系统、both_slash（默认）、forward_slash、反斜杠 | parse_path('path/to/file.csv', 'system') |
| pi | 返回 pi 的值 | pi() |
| position | 返回 haystack 中第一次出现的针的位置，从 1 开始计数。如果没有找到匹配则返回 0 | position('test test','es') |
| pow | 计算 x 的 y 次方 | pow(2, 3) |
| power | 计算 x 的 y 次方 | power(2, 3) |
| prefix | 判断字符串是否以指定前缀开头 | prefix('hello world', 'hello') = true |
| printf | 使用 printf 语法格式化字符串 | printf('Benchmark "%s" took %d seconds', 'CSV', 42) |
| quarter | 从日期或时间戳中提取季度部分 | quarter(timestamp '2021-08-03 11:59:44.123456') |
| radians | 将度数转换为弧度 | radians(90) |
| random | 返回 0 到 1 之间的随机数 | random() |
| range | 创建开始和停止之间的值列表 - 停止参数是独占的 | range(2, 5, 3) |
| reduce | 返回单个值，该值是将 lambda 函数应用于输入列表的每个元素的结果，从第一个元素开始，然后重复将 lambda 函数应用于上一个应用程序的结果和列表的下一个元素。 | reduce([1, 2, 3], (x, y) -> x + y) |
| regexp_escape | 转义输入字符串中所有可能有意义的正则表达式字符 | regexp_escape('[https://bigquant.com](https://bigquant.com/wiki/doc/Rceb2JQBdS)') |
| regexp_extract | 正则表达式提取首次出现的 | regexp_extract('hello_world', '([a-z ]+)_?', 1) = 'hello' |
| regexp_extract_all | 正则表达式提取全部 | regexp_extract_all('hello_world', '([a-z ]+)_?', 1) = ['hello', 'world'] |
| regexp_full_match | 正则表达式是否完全匹配 | regexp_full_match('anabanana', '(an)*') = false |
| regexp_matches | 正则表达式是否有部分匹配 | regexp_matches('anabanana', '(an)*') = true |
| regexp_replace | 正则表达式替换第一处匹配, 添加 'g' 修改全部 | regexp_replace('hello', '[lo]', '-') = 'he-lo' |
| regexp_split_to_array | 沿着正则表达式分割字符串 | regexp_split_to_array('hello␣world; 42', ';?␣') |
| repeat | 重复字符串计数次数 | repeat('A', 5) |
| replace | 将字符串中出现的任何源替换为目标 | replace('hello', 'l', '-') |
| reverse | 反转字符串 | reverse('hello') |
| right | 提取最右边的计数字符 | right('Hello🌎', 3) |
| right_grapheme | 提取最右边的计数字素簇 | right_grapheme('🤦🏼‍♂️🤦🏽‍♀️', 1) |
| round | 将 x 四舍五入到小数点后 s 位 | round(42.4332, 2) |
| row | 创建一个包含参数值的未命名结构（元组）。 | row(i, i % 4, i / 4) |
| rpad | 用从右侧开始的字符填充字符串，直到有 count 个字符 | rpad('hello', 10, '<') |
| rtrim | 删除字符串右侧出现的任何字符 | rtrim('>>>>test<<', '><') |
| second | 从日期或时间戳中提取秒部分 | second(timestamp '2021-08-03 11:59:44.123456') |
| set_bit | 将位串中的第 n 位设置为新值；第一个（最左边）位的索引为 0。返回一个新的位串 | set_bit('0110010'::BIT, 2, 0) |
| setseed | 设置用于随机函数的种子 | setseed(0.42) |
| sha1 | 返回值的 SHA1 哈希值 | sha1('hello') |
| sha256 | 返回值的 SHA256 哈希值 | sha256('hello') |
| sign | 返回 x 的符号为 -1、0 或 1 | sign(-349) |
| signbit | 返回符号位是否已设置 | signbit(-0.0) |
| sin | 计算 x 的正弦 | sin(90) |
| sinh | 计算 x 的双曲正弦 | sinh(1) |
| split | 沿分隔符分割字符串 | split('hello-world', '-') |
| sqrt | 返回 x 的平方根 | sqrt(4) |
| starts_with | 如果字符串以 search_string 开头，则返回 true | starts_with('abc','a') |
| stats | 返回一个字符串，其中包含有关表达式的统计信息。表达式可以是列、常量或 SQL 表达式 | stats(5) |
| str_split | 沿分隔符分割字符串 | str_split('hello-world', '-') |
| str_split_regex | 沿着正则表达式分割字符串 | str_split_regex('hello␣world; 42', ';?␣') |
| strftime | 根据格式字符串将日期转换为字符串。 | strftime(date '1992-01-01', '%a, %-d %B %Y') |
| string_split | 沿分隔符分割字符串 | string_split('hello-world', '-') |
| string_split_regex | 沿着正则表达式分割字符串 | string_split_regex('hello␣world; 42', ';?␣') |
| string_to_array | 沿分隔符分割字符串 | string_to_array('hello-world', '-') |
| strip_accents | 返回字符串的去重音符 | strip_accents('naïveté') = 'naivete' |
| strlen | 返回字符串字节长度 | strlen('🌎') = 4 |
| strpos | 返回 haystack 中第一次出现的针的位置，从 1 开始计数。如果没有找到匹配则返回 0 | strpos('test test','es') |
| strptime | 将字符串文本转换为时间戳，以在列表中使用格式字符串，直到成功为止。在失败上丢下错误。要在失败时返回null，请使用try_strptime。 | strptime('4/15/2023 10:56:00', ['%d/%m/%Y %H:%M:%S', '%m/%d/%Y %H:%M:%S']) |
| strptime | 根据格式字符串将字符串文本转换为时间戳。在失败上丢下错误。要在失败时返回null，请使用try_strptime。 | strptime('Wed, 1 January 1992 - 08:38:40 PM', '%a, %-d %B %Y - %I:%M:%S %p') |
| struct_concat | 将多个结构合并为单个结构。 | struct_concat(struct_pack(i := 4), struct_pack(s := 'string')) |
| struct_extract | 提取结构体中的元素, 可缩写成 struct.key | struct_extract({i: 7, s: 'string'}, 's') = 'string' |
| struct_extract_at | 按位置从结构中提取条目（从1开始！）。 | struct_extract_at({'i': 3, 'v2': 3, 'v3': 0}, 2) |
| struct_insert | 使用参数值将字段/值添加到现有 STRUCT。条目名称将是绑定变量名称 | struct_insert({'a': 1}, b := 2) |
| struct_pack | 创建一个包含参数值的结构。输入名称将是绑定的变量名称。 | struct_pack(i := 4, s := 'string') |
| substr | 返回开始于 start, 长度为 length 的子串, substring 的别名 | substr('hello world', 1, 5) = 'hello' |
| substring | 返回开始于 start, 长度为 length 的子串 | substring('hello world', 1, 5) = 'hello' |
| substring_grapheme | 返回开始于 start, 长度为 length 的子串 | substring_grapheme('🪐👽🌎🚀', 2, 2) = '👽🌎' |
| suffix | 判断字符串是否以指定后缀结尾 | suffix('hello world', 'world') = true |
| tan | 计算 x 的 tan | tan(90) |
| tanh | 计算 x 的双曲正切 | tanh(1) |
| time_bucket | 按指定的时间间隔bucket_width截断TIMESTAMPTZ。存储桶相对于原点 TIMESTAMPTZ 对齐。对于不包含月份或年份间隔的存储桶，源默认为 2000-01-03 00:00:00+00；对于月份和年份间隔，源默认为 2000-01-01 00:00:00+00 | time_bucket(INTERVAL '2 weeks', TIMESTAMP '1992-04-20 15:26:00-07', TIMESTAMP '1992-04-01 00:00:00-07') |
| timetz_byte_comparable | 将 TIME WITH TIME ZONE 转换为整数排序键 | timetz_byte_comparable('18:18:16.21-07:00'::TIME_TZ) |
| timezone | 从日期或时间戳中提取时区部分 | timezone(timestamp '2021-08-03 11:59:44.123456') |
| timezone_hour | 从日期或时间戳中提取 timezone_hour 部分 | timezone_hour(timestamp '2021-08-03 11:59:44.123456') |
| timezone_minute | 从日期或时间戳中提取 timezone_month 部分 | timezone_minute(timestamp '2021-08-03 11:59:44.123456') |
| to_base | 将值转换为给定基数的字符串，可以选择用前导零填充到最小长度 | to_base(42, 16) |
| to_base64 | 将 blob 转换为 base64 编码的字符串 | to_base64('A'::blob) |
| to_binary | 将值转换为二进制表示形式 | to_binary(42) |
| to_centuries | 构造一个世纪间隔 | to_centuries(5) |
| to_days | 构造一天间隔 | to_days(5) |
| to_decades | 构建十年间隔 | to_decades(5) |
| to_hex | 将值转换为十六进制表示形式 | to_hex(42) |
| to_hours | 构建一个小时间隔 | to_hours(5) |
| to_microseconds | 构造微秒间隔 | to_microseconds(5) |
| to_millennia | 构建千年间隔 | to_millennia(1) |
| to_milliseconds | 构造毫秒间隔 | to_milliseconds(5.5) |
| to_minutes | 构建分钟间隔 | to_minutes(5) |
| to_months | 构造一个月间隔 | to_months(5) |
| to_quarters | 构造四分之一间隔 | to_quarters(5) |
| to_seconds | 构造第二个区间 | to_seconds(5.5) |
| to_timestamp | 将纪元以来的秒数转换为带时区的时间戳 | to_timestamp(1284352323.5) |
| to_weeks | 构造一周间隔 | to_weeks(5) |
| to_years | 构建年间隔 | to_years(5) |
| transaction_timestamp | 返回当前时间戳 | transaction_timestamp() |
| translate | 将字符串中与 from 集中的字符匹配的每个字符替换为 to 集中的相应字符。如果 from 比 to 长，则删除 from 中出现的多余字符 | translate('12345', '143', 'ax') |
| trim | 从字符串的两侧卸下任何空间。 | trim(' test ') |
| trim | 删除字符串两侧出现的任何字符 | trim('>>>>test<<', '><') |
| trunc | 截断数字 | trunc(17.4) |
| try_strptime | 根据格式字符串将字符串文本转换为时间戳。失败时返回零。 | try_strptime('Wed, 1 January 1992 - 08:38:40 PM', '%a, %-d %B %Y - %I:%M:%S %p') |
| txid_current | 返回当前事务的 ID（BIGINT）。如果当前事务还没有，它将分配一个新的 | txid_current() |
| typeof | 返回表达式结果的数据类型名称 | typeof('abc') |
| ucase | 返回大写字符串, upper 的别名 | ucase('hello world') = 'HELLO WORLD' |
| unbin | 将值从二进制表示形式转换为 blob | unbin('0110') |
| unhex | 将值从十六进制表示形式转换为 blob | unhex('2A') |
| unicode | 返回字符串第一个字符的 unicode 代码点 | unicode('ü') |
| union_extract | 从联合中提取具有命名标签的值。如果当前未选择标签，则为 NULL | union_extract(s, 'k') |
| union_tag | 以 ENUM 形式检索联合体当前选定的标签 | union_tag(union_value(k := 'foo')) |
| union_value | 创建包含参数值的单个成员 UNION。值的标签将是绑定的变量名称 | union_value(k := 'hello') |
| unpivot_list | 与 list_value 相同，但作为 unpivot 的一部分生成，以便更好地显示错误消息 | unpivot_list(4, 5, 6) |
| upper | 返回大写字符串 | upper('hello world') = 'HELLO WORLD' |
| url_decode | 取消转义 URL 编码输入。 | url_decode('this%20string%20is%2BFencoded') |
| url_encode | 通过对输入字符串进行编码来转义它，以便将其包含在 URL 查询参数中。 | url_encode('this string has/ special+ characters>') |
| uuid | 返回类似于以下内容的随机 UUID：eeccb8c5-9943-b2bb-bb5e-222f4e14b687 | uuid() |
| vector_type | 返回给定列的 VectorType | vector_type(col) |
| version | 返回当前的 BigDB 版本，格式如下：v0.3.2 | version() |
| week | 从日期或时间戳中提取周部分 | week(timestamp '2021-08-03 11:59:44.123456') |
| weekday | 从日期或时间戳中提取工作日部分 | weekday(timestamp '2021-08-03 11:59:44.123456') |
| weekofyear | 从日期或时间戳中提取 weekofyear 部分 | weekofyear(timestamp '2021-08-03 11:59:44.123456') |
| write_log | 写到记录器 | write_log('Hello') |
| xor | 按位异或 | xor(17, 5) |
| year | 从日期或时间戳中提取年份部分 | year(timestamp '2021-08-03 11:59:44.123456') |
| yearweek | 从日期或时间戳中提取年周部分 | yearweek(timestamp '2021-08-03 11:59:44.123456') |

##### 聚合函数
| 函数名称 | 描述 | 例子 |
|---|---|---|
| any_value | 返回任意一个值 (实际实现为第一个非空元素) | any_value(open) |
| approx_count_distinct | 使用 HyperLogLog 计算不同元素的近似计数。 | approx_count_distinct(A) |
| approx_quantile | 使用 T-Digest 计算近似分位数。 | approx_quantile(x, 0.5) |
| approx_top_k | 查找数据集中 k 个最常出现的值 | approx_top_k(x, 5) |
| arbitrary | 返回任意一个值 (实际实现为第一个元素) | arbitrary(open) |
| arg_max | 查找具有最大值的行。计算该行的非 NULL arg 表达式。 | arg_max(A,B) |
| arg_max_null | 查找具有最大值的行。计算该行的 arg 表达式。 | arg_max_null(A,B) |
| arg_min | 查找具有最小 val 的行。计算该行的非 NULL arg 表达式。 | arg_min(A,B) |
| arg_min_null | 查找具有最小 val 的行。计算该行的 arg 表达式。 | arg_min_null(A,B) |
| argmax | 查找具有最大值的行。计算该行的非 NULL arg 表达式。 | argmax(A,B) |
| argmin | 查找具有最小 val 的行。计算该行的非 NULL arg 表达式。 | argmin(A,B) |
| array_agg | 返回包含列的所有值的 LIST。 | array_agg(A) |
| avg | 计算 x 中所有元组的平均值。 公式: SUM(x) / COUNT(*) | avg(A) |
| bit_and | 返回给定表达式中所有位的按位与。 | bit_and(A) |
| bit_or | 返回给定表达式中所有位的按位或。 | bit_or(A) |
| bit_xor | 返回给定表达式中所有位的按位异或。 | bit_xor(A) |
| bitstring_agg | 返回一个位串，其中为每个不同值设置了位。 | bitstring_agg(A) |
| bool_and | 如果每个输入值均为 TRUE，则返回 TRUE，否则返回 FALSE。 | bool_and(A) |
| bool_or | 如果任何输入值为 TRUE，则返回 TRUE，否则返回 FALSE。 | bool_or(A) |
| corr | 返回组中非空对的相关系数。 公式: COVAR_POP(y, x) / (STDDEV_POP(x) * STDDEV_POP(y)) | corr(B, A) |
| count | 返回非空值的个数 | count(open) |
| count_if | 计算布尔列的真实值总数 | count_if(A) |
| count_star | 返回总行数 | count_star(*) |
| countif | 计算布尔列的真实值总数 | countif(A) |
| covar_pop | 返回输入值的总体协方差。 公式: (SUM(x*y) - SUM(x) * SUM(y) / COUNT(*)) / COUNT(*) | covar_pop(B, A) |
| covar_samp | 返回组中非空对的样本协方差。 公式: (SUM(x*y) - SUM(x) * SUM(y) / COUNT(*)) / (COUNT(*) - 1) | covar_samp(B, A) |
| decay_linear | 当前窗口下加权平均，当前行值为 [1/sum, 2/sum, …, d/sum] * X, sum=1+2+…+d=(d+1)*d/2, X 为 arg 在当前 window 的列向量。窗口大小 d 由 over() 里面的 rows 指定 | decay_linear(close) |
| entropy | 返回 count 个输入值的 log-2 熵。 | entropy(A) |
| favg | 使用更准确的浮点求和 (Kahan Sum) 计算平均值 | favg(A) |
| first | 返回第一个值 | first(open) |
| fsum | 使用更精确的浮点求和 (Kahan Sum) 计算总和。 | fsum(A) |
| group_concat | 使用可选分隔符连接列字符串值。 | group_concat(A, '-') |
| histogram | 返回包含字段“bucket”和“count”的 STRUCT 列表。 | histogram(A) |
| histogram_exact | 返回 STRUCT 的列表，其中字段存储桶和计数与存储桶完全匹配。 | histogram_exact(A, [0, 1, 2]) |
| kahan_sum | 使用更精确的浮点求和 (Kahan Sum) 计算总和。 | kahan_sum(A) |
| kurtosis | 返回所有输入值的超额峰度（Fisher 定义），并根据样本大小进行偏差校正 | kurtosis(A) |
| kurtosis_pop | 返回所有输入值的超额峰度（Fisher 定义），不进行偏差校正 | kurtosis_pop(A) |
| last | 返回最后一个值 | last(open) |
| list | 返回包含列的所有值的 LIST。 | list(A) |
| listagg | 使用可选分隔符连接列字符串值。 | listagg(A, '-') |
| mad | 返回 x 内值的中值绝对偏差。 NULL 值将被忽略。时间类型返回正 INTERVAL。 公式: mad(x) | mad(A) |
| max | 返回 arg 中存在的最大值。 | max(A) |
| max_by | 查找具有最大值的行。计算该行的非 NULL arg 表达式。 | max_by(A,B) |
| mean | 计算 x 中所有元组的平均值。 公式: SUM(x) / COUNT(*) | mean(A) |
| median | 返回集合的中间值。 NULL 值将被忽略。对于偶数值计数，定量值将被平均，序数值将返回较低的值。 公式: median(x) | median(A) |
| min | 返回 arg 中存在的最小值。 | min(A) |
| min_by | 查找具有最小 val 的行。计算该行的非 NULL arg 表达式。 | min_by(A,B) |
| mode | 返回 x 内值的最频繁值。 NULL 值将被忽略。 | mode(A) |
| nanavg | 计算 x 中所有元组的平均值，忽略 NaN。 | nanavg(A) |
| nanmean | 计算 x 中所有元组的平均值，忽略 NaN。 | nanmean(A) |
| nanstd | 返回样本标准差，忽略 NaN。 | nanstd(A) |
| nanstd_pop | 返回总体标准差，忽略 NaN。 | nanstd_pop(A) |
| nanstd_samp | 返回样本标准差，忽略 NaN。 | nanstd_samp(A) |
| nanvar | 返回所有输入值的样本方差，忽略 NaN。 | nanvar(A) |
| nanvar_pop | 返回总体方差，忽略 NaN。 | nanvar_pop(A) |
| nanvar_samp | 返回所有输入值的样本方差，忽略 NaN。 | nanvar_samp(A) |
| product | 计算 arg 中所有元组的乘积。 | product(A) |
| quantile | 返回 0 到 1 之间的精确分位数。如果 pos 是 FLOAT 的列表，则结果是相应精确分位数的列表。 | quantile(A, 0.5) |
| quantile_cont | 返回 0 和 1 之间的插值分位数。如果 pos 是 FLOAT 的列表，则结果是相应插值分位数的列表。 | quantile_cont(A, 0.5) |
| quantile_disc | 返回 0 到 1 之间的精确分位数。如果 pos 是 FLOAT 的列表，则结果是相应精确分位数的列表。 | quantile_disc(A, 0.5) |
| regr_avgx | 返回组中非空对的自变量的平均值，其中 x 是自变量，y 是因变量。 | regr_avgx(B, A) |
| regr_avgy | 返回组中非空对的因变量的平均值，其中 x 是自变量，y 是因变量。 | regr_avgy(B, A) |
| regr_count | 返回组中非空数字对的数量。 公式: (SUM(x*y) - SUM(x) * SUM(y) / COUNT(*)) / COUNT(*) | regr_count(B, A) |
| regr_intercept | 返回组中非空对的单变量线性回归线的截距。 公式: AVG(y)-REGR_SLOPE(y,x)*AVG(x) | regr_intercept(B, A) |
| regr_r2 | 返回组中非空对的决定系数。 | regr_r2(B, A) |
| regr_slope | 返回组中非空对的线性回归线的斜率。 公式: COVAR_POP(x,y) / VAR_POP(x) | regr_slope(B, A) |
| regr_sxx | 公式: REGR_COUNT(y, x) * VAR_POP(x) | regr_sxx(B, A) |
| regr_sxy | 返回输入值的总体协方差 公式: REGR_COUNT(y, x) * COVAR_POP(y, x) | regr_sxy(B, A) |
| regr_syy | 公式: REGR_COUNT(y, x) * VAR_POP(y) | regr_syy(B, A) |
| reservoir_quantile | 使用水库采样给出近似分位数，样本大小是可选的，并使用 8192 作为默认大小。 | reservoir_quantile(A,0.5,1024) |
| sem | 返回平均值的标准误差 | sem(A) |
| skewness | 返回所有输入值的偏度。 | skewness(A) |
| stddev | 返回样本标准差 公式: sqrt(var_samp(x)) | stddev(A) |
| stddev_pop | 返回总体标准差。 公式: sqrt(var_pop(x)) | stddev_pop(A) |
| stddev_samp | 返回样本标准差 公式: sqrt(var_samp(x)) | stddev_samp(A) |
| string_agg | 使用可选分隔符连接列字符串值。 | string_agg(A, '-') |
| sum | 计算 arg 中所有元组的总和值。 | sum(A) |
| sum_no_overflow | 仅供内部使用。计算 arg 中所有元组的总和，不进行溢出检查。 | sum_no_overflow(A) |
| sumkahan | 使用更精确的浮点求和 (Kahan Sum) 计算总和。 | sumkahan(A) |
| var_pop | 返回总体方差。 | var_pop(A) |
| var_samp | 返回所有输入值的样本方差。 公式: (SUM(x^2) - SUM(x)^2 / COUNT(x)) / (COUNT(x) - 1) | var_samp(A) |
| variance | 返回所有输入值的样本方差。 公式: (SUM(x^2) - SUM(x)^2 / COUNT(x)) / (COUNT(x) - 1) | variance(A) |

##### 窗口函数
| 函数名称 | 描述 | 例子 |
|---|---|---|
| row_number | 分区中当前行的编号，从 1 开始计数 | row_number() |
| rank | 当前行的有间隙的排名;与`row_number`相同 | rank() |
| percent_rank | 当前行的相对排名：`rank() / total non-NaN partition rows` | percent_rank() |
| rank_ext | 当前行的滚动窗口排名，窗口大小由over()里面的rows指定 | rank_ext(open,’avg’,true) |
| pct_rank_ext | `rank_ext()/window` | pct_rank_ext(open,’min’,false) |
| rolling_rank | 同`rank_ext()` | rolling_rank(open,’max’,true) |
| dense_rank | 当前行的排名，没有间隙；此函数对相等的组进行计数 | dense_rank() |
| rank_dense | `dense_rank`的别名 | rank_dense() |
| cume_dist | 累积分布：（当前行之前或对等的分区行数）/分区总行数 | cume_dist() |
| ntile | 返回一个介于 1 到`num_buckets`参数值之间的整数，尽可能平均地划分分区 | ntile(4) |
| lag | 返回在分区中当前行之前的`offset`行处计算`expr`的结果；如果没有这样的行，则返回`default`（必须与`expr`的类型相同）。`offset`和`default`两者均针对当前行计算。`offset`的默认值为`1`，`default`的默认值为`null` | lag(column, 3, 0) |
| lead | 返回在分区中当前行之后的`offset`行处计算`expr`的结果；如果没有这样的行，则返回`default`（必须与`expr`的类型相同）。`offset`和`default`两者均针对当前行计算。`offset`的默认值为`1`，`default`的默认值为`null` | lead(column, 3, 0) |
| first_value | 窗口第一行计算`expr`的结果 | first_value(column) |
| last_value | 窗口最后一行计算`expr`的结果 | last_value(column) |
| nth_value | 窗口在第n（从 1 开始计数）行处计算`expr`的结果；如果没有这样的行，则返回null | nth_value(column, 2) |
| first | `first_value`的别名 | first(column) |
| last | `last_value`的别名 | last(column) |
| decay_linear | 当前窗口下加权平均，当前行值为 [1/sum, 2/sum, …, d/sum] * X, sum=1+2+…+d=(d+1)*d/2, X 为 arg 在当前 window 的列向量。窗口大小 d 由 over() 里面的 rows 指定 | decay_linear(open) |
| imax | 当前窗口下 `arg` 最大值所在的窗口索引 (从0开始) | imax(open) |
| imin | 当前窗口下 `arg` 最小值所在的窗口索引 (从0开始) | imin(open) |
| cummax | 计算 arg 在分区排序后的累计最大值 | cummax(close) |
| cummin | 计算 arg 在分区排序后的累计最小值 | cummin(close) |
| cumsum | 计算 arg 在分区排序后的累计和 | cumsum(turn) |
| cumprod | 计算 arg 在分区排序后的累计乘积 | cumprod(turn) |
| sum_greatest_k | 分区排序后滚动窗口内 val 最大 k 个数对应的 arg 的累加和 | sum_greatest_k(change_ratio, amount/deal_number, 20, 10) |
| sum_least_k | 分区排序后滚动窗口内 val 最小 k 个数对应的 arg 的累加和 | sum_least_k(change_ratio, amount/deal_number, 20, 10) |
| sum_gl_k_delta | 分区排序后滚动窗口内 val 最大 k 个数对应的 arg 的累加和与最小 k 个数对应的 arg 的累加和的差值 | sum_gl_k_delta(change_ratio, amount/deal_number, 20, 10) |
| avg_greatest_k | 分区排序后滚动窗口内 val 最大 k 个数对应的 arg 的平均值 | avg_greatest_k(sigmoid(high), turn, 15, 7) |
| avg_least_k | 分区排序后滚动窗口内 val 最小 k 个数对应的 arg 的平均值 | avg_least_k(sigmoid(high), turn, 15, 7) |
| std_samp_greatest_k | 分区排序后滚动窗口内 val 最大 k 个数对应的 arg 的样本标准差 | std_samp_greatest_k(arg, val, w, k) |
| std_samp_least_k | 分区排序后滚动窗口内 val 最小 k 个数对应的 arg 的样本标准差 | std_samp_least_k(arg, val, w, k) |
| std_pop_greatest_k | 分区排序后滚动窗口内 val 最大 k 个数对应的 arg 的总体标准差 | std_pop_greatest_k(arg, val, w, k) |
| std_pop_least_k | 分区排序后滚动窗口内 val 最小 k 个数对应的 arg 的总体标准差 | std_pop_least_k(arg, val, w, k) |
| var_samp_greatest_k | 分区排序后滚动窗口内 val 最大 k 个数对应的 arg 的样本方差 | var_samp_greatest_k(arg, val, w, k) |
| var_samp_least_k | 分区排序后滚动窗口内 val 最小 k 个数对应的 arg 的样本方差 | var_samp_least_k(arg, val, w, k) |
| var_pop_greatest_k | 分区排序后滚动窗口内 val 最大 k 个数对应的 arg 的总体方差 | var_pop_greatest_k(arg, val, w, k) |
| var_pop_least_k | 分区排序后滚动窗口内 val 最小 k 个数对应的 arg 的总体方差 | var_pop_least_k(arg, val, w, k) |
| sum_first_k | 分区排序后 arg 的前 k 个值的累加和，分区内结果相同 | sum_first_k(close, 5) |
| avg_first_k | 分区排序后 arg 的前 k 个值的平均值，分区内结果相同 | avg_first_k(close, 5) |

##### TA-Lib 函数
| 函数名称 | 描述 | 例子 |
|---|---|---|
| ta_2crows | 两只乌鸦 | ta_2crows(open, high, low, close) |
| ta_3black_crows | 三只乌鸦 | ta_3black_crows(open, high, low, close) |
| ta_3red_soldiers | 红三兵 | ta_3red_soldiers(open, high, low, close) |
| ta_ad | Chaikin A/D (累积分布) 线 | ta_ad(high, low, close, volume) |
| ta_adx | 窗口大小周期的平均趋向指数 | ta_adx(high, low, close, 5) |
| ta_adxr | 窗口大小周期的平均趋向评指数 | ta_adxr(high, low, close, 5) |
| ta_aroon | Aroon 指标: 返回有两列的 list: aroondown, aroonup | ta_aroon(high, low, 14) |
| ta_aroonosc | 窗口大小周期的 AROONOSC 指标 | ta_aroonosc(high, low, 14) |
| ta_atr | 窗口大小周期的均幅指标 | ta_atr(high, low, close, 5) |
| ta_bbands | 布林带: 返回有三列的list: upper_band, middle_band, lower_band | ta_bbands(close, 5, 2.0, 2.0, 0) |
| ta_beta | 窗口大小周期的线性回归斜率 | ta_beta(high, low, 5) |
| ta_cci | 窗口大小周期的顺势指标 | ta_cci(high, low, close, 5) |
| ta_dark_cloud_cover | 乌云盖顶 | ta_dark_cloud_cover(open, high, low, close, 0.5) |
| ta_dema | 窗口大小周期的双指数移动平均 | ta_dema(close, 5) |
| ta_ema | 窗口大小周期的指数移动平均值 | ta_ema(close, 5) |
| ta_evening_star | 黄昏之星 | ta_evening_star(open, high, low, close, 0.3) |
| ta_ewm | 指数加权移动平均: df.ewm(alpha=alpha, adjust=False).mean(). 有 NULL 则发生截断重新开始计算 | ta_ewm(close, 1/3) |
| ta_hammer | 锤 | ta_hammer(open, high, low, close) |
| ta_inverted_hammer | 倒锤 | ta_inverted_hammer(open, high, low, close) |
| ta_kama | 窗口大小周期的 Kaufman 自适应移动平均 | ta_kama(close, 5) |
| ta_macd | 移动平均收敛发散: 返回有三列的list: macd_dif (指数平滑移动平均线), macd_dea (DIF的 N 日 (默认９日) 指数平滑移动平均线), macd_hist (2 * (DIF-DEA)) | ta_macd(close, 12, 26, 9) |
| ta_mfi | 窗口大小周期的货币流量指数 | ta_mfi(high, low, close, volume, 5) |
| ta_mom | 窗口大小周期的动量指标 | ta_mom(close, 5) |
| ta_morning_star | 早晨之星 | ta_morning_star(open, high, low, close, 0.3) |
| ta_obv | 能量潮 | ta_obv(close, volume) |
| ta_roc | 窗口大小周期的变动率指标 | ta_roc(close, 5) |
| ta_rsi | 窗口大小周期的相对强弱指标 | ta_rsi(close, 5) |
| ta_sar | 抛物线转向 (SAR) 指标 | ta_sar(high, low, 0.02, 0.2) |
| ta_shooting_star | 流星线 | ta_shooting_star(open, high, low, close) |
| ta_sma | 窗口大小周期的简单移动平均值 | ta_sma(close, 5) |
| ta_stoch | 随机指标: 返回有两列的 list: K, D | ta_stoch(high, low, close, 9, 3, 0, 3, 0) |
| ta_sum | 窗口大小周期的累加和 | ta_sum(close, 5) |
| ta_tema | 窗口大小周期的三重指数移动平均 | ta_tema(close, 5) |
| ta_trima | 窗口大小周期的三角移动平均 | ta_trima(close, 5) |
| ta_trix | 窗口大小周期的三重指数平滑平均线 | ta_trix(close, 5) |
| ta_willr | 窗口大小周期的威廉指标 | ta_willr(high, low, close, 5) |
| ta_wma | 窗口大小周期的加权移动平均值 | ta_wma(close, 5) |

##### macro 函数
| 函数名称 | 描述 | 例子 |
|---|---|---|
| all_cbins | 对数据做基于全局分位数的离散化分组 | all_cbins(close, 10) |
| all_quantile_cont | x 在 pos 处的插值分位数 | all_quantile_cont(x, 0.5) |
| all_quantile_disc | x 在 pos 处的最近的确切分位数 | all_quantile_disc(x, 0.5) |
| all_wbins | 将 arg 按大小值均分成 bins 个桶并判断 arg 每行属于哪个桶（从 0 开始） | all_wbins(close, 10) |
| array_append | 把元素 el 添加到数组 arr 的末尾, list_append 的别名 | array_append([1, 2], 3) |
| array_intersect | 返回数组 l1 和 l2 的交集, list_intersect 的别名 | array_intersect([1, 2, 3], [2, 3, 4]) |
| array_pop_back | 删除数组 arr 的最后一个元素 | array_pop_back([1, 2, 3]) |
| array_pop_front | 删除数组 arr 的第一个元素 | array_pop_front([1, 2, 3]) |
| array_prepend | 把元素 el 添加到数组 arr 的开头, list_prepend 的别名 | array_prepend(3, [1, 2]) |
| array_push_back | 把元素 e 添加到数组 arr 的末尾 | array_push_back([1, 2], 3) |
| array_push_front | 把元素 e 添加到数组 arr 的开头 | array_push_front([1, 2], 3) |
| array_reverse | 返回数组 l 的逆序, list_reverse 的别名 | array_reverse([1, 2, 3]) |
| array_to_string | 把数组 arr 的元素用分隔符 sep 连接成字符串 | array_to_string([1, 2, 3], ',') |
| c_avg | 在时间截面上，求 x 的均值 | c_avg(close) |
| c_cbins | 在日期截面上做基于分位数的离散化。将数据离散化为尽可能相等大小的存储桶。 | c_cbins(close, 4) |
| c_count | 在时间截面上，求 x 的非空个数 | c_count(close) |
| c_fillna | 在时间截面上用分组均值填充缺失值，x 为 NULL 时返回分组均值，否则返回 grp 为分组字段，比如行业代码 | c_fillna(x, grp) |
| c_fillna_weighted | 在时间截面上用分组加权均值填充缺失值，x 为 NULL 时返回分组加权均值，否则返回 x；grp 为分组字段，比如行业代码，weight 为权重，比如市值 | c_fillna_weighted(x, grp, weight) |
| c_group_avg | 在时间截面上按 key 分组后 arg 的均值 | c_group_avg(sw2021_level2, close) |
| c_group_pct_rank | 在时间截面上按 key 分组后 arg 的百分数排名 | c_group_pct_rank(sw2021_level2, close) |
| c_group_quantile_cont | 在时间截面上按 key 分组后 x 在 pos 处的插值分位数 | c_group_quantile_cont(sw2021_level2, close, 0.3) |
| c_group_quantile_disc | 在时间截面上按 key 分组后 x 在 pos 处的确切分位数 | c_group_quantile_disc(sw2021_level2, close, 0.3) |
| c_group_std | 在时间截面上按 key 分组后 arg 的（样本）标准差 | c_group_std(sw2021_level2, close) |
| c_group_sum | 在时间截面上按 key 分组后 arg 的和 | c_group_sum(sw2021_level2, close) |
| c_indneutralize | 在时间截面上计算行业中性化值，计算前对 y 做预处理（去极值和标准化） | c_indneutralize(y, industry_level1_code) |
| c_indneutralize_resid | 在时间截面上计算行业中性化值，只做残差计算， y 不做预处理 | c_indneutralize_resid(y, industry_level1_code) |
| c_mad | 在时间截面上，求 x 的绝对中位差 | c_mad(close) |
| c_median | 在时间截面上，求 x 的中位数 | c_median(close) |
| c_min_max_scalar | 在时间截面上，将 x 缩放到 [a, b] 区间 | c_min_max_scalar(x, a:=0, b:=1) |
| c_neutralize | 在时间截面上计算行业市值中性化值，计算前对 y 和 marketcap 做预处理（ y 去极值和标准化， marketcap 取对数） | c_neutralize(y, industry_level1_code, marketcap) |
| c_neutralize_resid | 在时间截面上计算行业市值中性化值，只做残差计算， y 和 marketcap 不做预处理 | c_neutralize_resid(y, industry_level1_code, marketcap) |
| c_normalize | 在时间截面上，z-score标准化 | c_normalize(close) |
| c_ols1d_resid | 在时间截面上计算 y 与 x 的一元线性回归残差 | c_ols1d_resid(y, x) |
| c_ols2d_resid | 在时间截面上计算 y 与 [x1, x2] 的二元线性回归残差 | c_ols2d_resid(y, x1, x2) |
| c_ols3d_resid | 在时间截面上计算 y 与 [x1, x2, x3] 的三元线性回归残差 | c_ols3d_resid(y, x1, x2, x3) |
| c_pct_rank | 在时间截面上 arg 的百分数排名 | c_pct_rank(close, ascending:=true) |
| c_preprocess | 在时间截面上，x <- ifnull(x, c_avg(x)) 后 c_normalize(clip(x, median-n*mad, median+n*mad)) | c_preprocess(close, 5) |
| c_quantile_cont | 时间截面上，求 x 在 pos 处的插值分位数 | c_quantile_cont(x, 0.5) |
| c_quantile_disc | 时间截面上，求 x 在 pos 处的最近的确切分位数 | c_quantile_disc(x, 0.5) |
| c_rank | 在时间截面上 arg 的排名 | c_rank(close, ascending:=true) |
| c_regr_residual | 在时间截面上计算 y 与 x 的线性回归残差 | c_regr_residual(y, x) |
| c_scale | 时间截面上将 x 缩放使得缩放后的 x 的绝对值之和为 a: x -> x / sum(\|x\|) * a | c_scale(x, 10) |
| c_std | 在时间截面上，求 x 的（样本）标准差 | c_std(close) |
| c_sum | 在时间截面上，求 x 的和 | c_sum(close) |
| c_var | 在时间截面上，求 x 的（样本）方差 | c_var(close) |
| c_wbins | 在时间截面上，将 arg 按大小值均分成 bins 个桶并判断 arg 每行属于哪个桶（从 0 开始） | c_wbins(close, 10) |
| c_weighted_avg | 在时间截面上做分组加权平均；x 为值，grp 为分组字段，比如行业代码，weight 为权重，比如市值 | c_weighted_avg(x, grp, weight) |
| c_weighted_stddev | 在时间截面上做分组加权标准差；x 为值，grp 为分组字段，比如行业代码，weight 为权重，比如市值 | c_weighted_stddev(x, grp, weight) |
| c_winsorize | 在时间截面上对 x 做缩尾处理，lower 和 upper 为百分位数，比如 0.01 和 0.99 | c_winsorize(close, 0.01, 0.99) |
| c_winsorize_nsigma | 在时间截面上通过n-sigma规则做分组去极值；n为标准差倍数，默认为3，grp 为分组字段，比如行业代码 | c_winsorize_nsigma(x, grp, n:=3) |
| c_winsorize_weighted_nsigma | 在时间截面上通过n-sigma规则做分组去极值；n为加权标准差倍数，默认为3，grp 为分组字段，比如行业代码，weight 为权重，比如市值 | c_winsorize_weighted_nsigma(x, grp, weight, n:=3) |
| c_zscore | 在时间截面上，z-score标准化 | c_zscore(close) |
| clip | 若 a < a_min, 则返回 a_min; 若 a > a_max, 则返回 a_max; 否则返回 a | clip(close, 1, 99) |
| constant | 返回自己本身 | constant(13) |
| cume_dist | 按照参数 ob 排序后的累积分布 | cume_dist(close, ascending:=true) |
| cume_dist_by | 依据 pb 分组后并按照 ob 做组内排序后的累积分布 | cume_dist_by(date, close, ascending:=true) |
| cut_outliers | 在时间截面上去极值；m为倍数，默认为3 | cut_outliers(s) |
| date_add | 返回 date 加上 interval 后的日期 | date_add(DATE '2023-01-01', INTERVAL 5 MONTH) |
| dense_rank | 按照参数 ob 排序后的无间隙排名 | dense_rank(close, ascending:=true) |
| dense_rank_by | 依据 pb 分组后并按照 ob 做组内排序后的无间隙排名 | dense_rank_by(date, close, ascending:=true) |
| fdiv | 返回 x/y 的整数部分 | fdiv(5, 2) |
| fmod | 返回 x/y 的余数 | fmod(5, 2) |
| generate_subscripts | 返回数组 arr 的第 dim 维的下标 | generate_subscripts([1, 2, 3], 1) |
| geomean | 返回 x 的几何平均数 | geomean(open) |
| geometric_mean | 返回 x 的几何平均数, geomean 的别名 | geometric_mean(open) |
| group_neutralize | 在时间截面上对 x 做分组中性化处理， grp 为分组字段，比如行业代码 | group_neutralize(x, grp) |
| group_rank | 在时间截面基于数据字段 x 的值进行分组排名，并返回一个在 [0.0, 1.0] 范围内的值； grp 为分组字段，比如行业代码 | group_rank(x, grp) |
| group_scale | 在时间截面上对 x 做分组缩放处理， grp 为分组字段，比如行业代码 | group_scale(x, grp) |
| group_zscore | 在时间截面上对 x 做分组 z-score 标准化处理， grp 为分组字段，比如行业代码 | group_zscore(x, grp) |
| list_add_head_tail | 添加头元素和尾元素到列表 list 中 | list_add_head_tail(2017, [2018, 2019, 2020], 2021) |
| list_any_value | 返回列表 l 的任意一个值 | list_any_value([1,2,3]) |
| list_append | 把元素 e 添加到列表 l 的末尾 | list_append([1, 2], 3) |
| list_approx_count_distinct | 返回列表 l 的近似不同值的个数 | list_approx_count_distinct([1,2,3]) |
| list_avg | 返回列表 l 的平均值 | list_avg([1,2,3]) |
| list_bit_and | 返回列表 l 的与值 | list_bit_and([1,2,3]) |
| list_bit_or | 返回列表 l 的或值 | list_bit_or([1,2,3]) |
| list_bit_xor | 返回列表 l 的异或值 | list_bit_xor([1,2,3]) |
| list_bool_and | 返回列表 l 的与值 | list_bool_and([true,false]) |
| list_bool_or | 返回列表 l 的或值 | list_bool_or([true,false]) |
| list_count | 返回列表 l 的非空个数 | list_count([1,2,3,null]) |
| list_entropy | 返回列表 l 的熵 | list_entropy([1,2,3]) |
| list_first | 返回列表 l 的第一个值 | list_first([1,2,3]) |
| list_histogram | 返回列表 l 的直方图 | list_histogram([1,2,3]) |
| list_intersect | 返回列表 l1 和 l2 的交集 | list_intersect([1, 2, 3], [2, 3, 4]) |
| list_kurtosis | 返回列表 l 的峰度 | list_kurtosis([1,2,3]) |
| list_kurtosis_pop | 返回列表 l 的总体峰度 | list_kurtosis_pop([1,2,3]) |
| list_last | 返回列表 l 的最后一个值 | list_last([1,2,3]) |
| list_mad | 返回列表 l 的绝对中位差 | list_mad([1,2,3]) |
| list_max | 返回列表 l 的最大值 | list_max([1,2,3]) |
| list_median | 返回列表 l 的中位数 | list_median([1,2,3]) |
| list_min | 返回列表 l 的最小值 | list_min([1,2,3]) |
| list_mode | 返回列表 l 的众数 | list_mode([1,2,3]) |
| list_prepend | 把元素 e 添加到列表 l 的开头 | list_prepend(3, [1, 2]) |
| list_product | 返回列表 l 的乘积 | list_product([1,2,3]) |
| list_reverse | 返回列表 l 的逆序 | list_reverse([1, 2, 3]) |
| list_sem | 返回列表 l 的标准误差 | list_sem([1,2,3]) |
| list_skewness | 返回列表 l 的偏度 | list_skewness([1,2,3]) |
| list_stddev_pop | 返回列表 l 的总体标准差 | list_stddev_pop([1,2,3]) |
| list_stddev_samp | 返回列表 l 的样本标准差 | list_stddev_samp([1,2,3]) |
| list_string_agg | 返回列表 l 的字符串连接 | list_string_agg(['a','b','c']) |
| list_sum | 返回列表 l 的和 | list_sum([1,2,3]) |
| list_var_pop | 返回列表 l 的总体方差 | list_var_pop([1,2,3]) |
| list_var_samp | 返回列表 l 的样本方差 | list_var_samp([1,2,3]) |
| m_approx_count_distinct | 时间序列上 x 在该窗口内的由 HyperLogLog 得出的不同元素的近似计数 | m_approx_count_distinct(x, 5) |
| m_approx_quantile | 时间序列上 x 在该窗口内的由 T-Digest 得出的近似分位数 | m_approx_quantile(x, 0.5, 5) |
| m_arg_max | 时间序列上 val 在该窗口内取最大值时的 arg 值 | m_arg_max(arg, val, 5) |
| m_arg_min | 时间序列上 val 在该窗口内取最小值时的 arg 值 | m_arg_min(arg, val, 5) |
| m_avg | 时间序列上 arg 在该窗口内的平均值 | m_avg(arg, 5) |
| m_avg_greatest_k | 时间序列上 val 在该窗口内最大 k 个数对应的 arg 的平均值 | m_avg_greatest_k(sigmoid(high), turn, 15, 7) |
| m_avg_least_k | 时间序列上 val 在该窗口内最小 k 个数对应的 arg 的平均值 | m_avg_least_k(sigmoid(high), turn, 15, 7) |
| m_bit_and | 时间序列上 arg 在该窗口内的按位与 | m_bit_and(arg, 5) |
| m_bit_or | 时间序列上 arg 在该窗口内的按位或 | m_bit_or(arg, 5) |
| m_bit_xor | 时间序列上 arg 在该窗口内的按位异或 | m_bit_xor(arg, 5) |
| m_bool_and | 时间序列上 arg 在该窗口内的逻辑与 | m_bool_and(arg, 5) |
| m_bool_or | 时间序列上 arg 在该窗口内的逻辑或 | m_bool_or(arg, 5) |
| m_consecutive_rise_count | 时间序列上 arg 最近一次连续上涨的次数：若 arg 上涨，则连涨次数 +1; 否则为 0. arg 为 NULL 的行其对应结果为 NULL | m_consecutive_rise_count(close, count_eq:=false) |
| m_consecutive_true_count | 时间序列上 expr 从当前行起往前取连续为 true 的数量. expr 为 NULL 的行其对应结果为 NULL | m_consecutive_true_count(close > m_lag(close, 1)) |
| m_corr | 时间序列上 y 和 x 在该窗口内的相关系数 | m_corr(y, x, 5) |
| m_count | 时间序列上 arg 在该窗口内的计数 | m_count(arg, 5) |
| m_covar_pop | 时间序列上 y 和 x 在该窗口内的总体协方差 | m_covar_pop(y, x, 5) |
| m_covar_samp | 时间序列上 y 和 x 在该窗口内的样本协方差 | m_covar_samp(y, x, 5) |
| m_cummax | 时间序列上 arg 的累计最大值 | m_cummax(close) |
| m_cummin | 时间序列上 arg 的累计最小值 | m_cummin(close) |
| m_cumprod | 时间序列上 arg 的累计乘积 | m_cumprod(turn) |
| m_cumsum | 时间序列上 arg 的累计和 | m_cumsum(turn) |
| m_decay_linear | 时间序列上 arg 在该窗口内的线性衰减 | m_decay_linear(arg, 5) |
| m_delta | m_delta(x, d) = x - m_shift(x, d), 今天与d天前的差值。如果d为负数，则表示abs(d)天以后的差值 | m_delta(close, 5), m_delta(close, -5) |
| m_entropy | 时间序列上 x 在该窗口内的熵 | m_entropy(x, 5) |
| m_favg | 时间序列上 arg 在该窗口内的 Kahan 平均值 | m_favg(arg, 5) |
| m_fillna | 在时间序列上用窗口均值填充缺失值，x 为 NULL 时返回窗口均值，否则返回 x；d 为窗口大小，比如4 | m_fillna(x, 4) |
| m_fillna_weighted | 在时间序列上用窗口加权均值填充缺失值，x 为 NULL 时返回窗口加权均值，否则返回 x；d 为窗口大小，比如4，weight 为权重，比如市值 | m_fillna_weighted(x, 4, weight) |
| m_first | 时间序列上 arg 在该窗口内的第一个值 | m_first(close, 5) |
| m_first_value | 时间序列上 arg 在该窗口内的第一个值 | m_first_value(close, 5) |
| m_fsum | 时间序列上 arg 在该窗口内的 Kahan 和 | m_fsum(arg, 5) |
| m_imax | 时间序列上 arg 在该窗口内的最大值所在的窗口索引 | m_imax(arg, 5) |
| m_imin | 时间序列上 arg 在该窗口内的最小值所在的窗口索引 | m_imin(arg, 5) |
| m_kurtosis | 时间序列上 x 在该窗口内的峰度 | m_kurtosis(x, 5) |
| m_lag | 时间序列上 arg 向下偏移 n 行后的值 | m_lag(close, 5, default_val:=null) |
| m_last | 时间序列上 arg 在该窗口内的最后一个值 | m_last(close, 5) |
| m_last_value | 时间序列上 arg 在该窗口内的最后一个值 | m_last_value(close, 5) |
| m_lead | 时间序列上 arg 向上偏移 n 行后的值 | m_lead(close, 5, default_val:=null) |
| m_mad | 时间序列上 x 在该窗口内的绝对中位差 | m_mad(x, 5) |
| m_max | 时间序列上 arg 在该窗口内的最大值 | m_max(arg, 5) |
| m_median | 时间序列上 x 在该窗口内的中位数 | m_median(x, 5) |
| m_min | 时间序列上 arg 在该窗口内的最小值 | m_min(arg, 5) |
| m_mode | 时间序列上 x 在该窗口内的众数 | m_mode(x, 5) |
| m_nanavg | 时间序列上 arg 在该窗口内忽略 NaN 值后的平均值 | m_nanavg(arg, 5) |
| m_nanstd | 时间序列上 x 在该窗口内忽略 NaN 值后的（样本）标准差 | m_nanstd(x, 5) |
| m_nanstd_pop | 时间序列上 x 在该窗口内忽略 NaN 值后的总体标准差 | m_nanstd_pop(x, 5) |
| m_nanstd_samp | 时间序列上 x 在该窗口内忽略 NaN 值后的样本标准差 | m_nanstd_samp(x, 5) |
| m_nanvar | 时间序列上 x 在该窗口内忽略 NaN 值后的（样本）方差 | m_nanvar(x, 5) |
| m_nanvar_pop | 时间序列上 x 在该窗口内忽略 NaN 值后的总体方差 | m_nanvar_pop(x, 5) |
| m_nanvar_samp | 时间序列上 x 在该窗口内忽略 NaN 值后的样本方差 | m_nanvar_samp(x, 5) |
| m_nth_value | 时间序列上 arg 在该窗口内的第 n 个值 | m_nth_value(close, 2, 5) |
| m_ols1d_resid_cx | 时间序列上 y 与 x=[1..win_sz] 在该窗口内的一元线性回归残差向量的最后一个值 | m_ols1d_resid_cx(y, 5) |
| m_ols2d_intercept | 时间序列上 y 与 [x1, x2] 在该窗口内的二元线性回归截距（常数项） | m_ols2d_intercept(y, x1, x2, 5) |
| m_ols2d_last_resid | 时间序列上 y 与 [x1, x2] 在该窗口内的二元线性回归残差向量的最后一个值 | m_ols2d_last_resid(y, x1, x2, 5) |
| m_ols3d_intercept | 时间序列上 y 与 [x1, x2, x3] 在该窗口内的三元线性回归截距（常数项） | m_ols3d_intercept(y, x1, x2, x3, 5) |
| m_ols3d_last_resid | 时间序列上 y 与 [x1, x2, x3] 在该窗口内的三元线性回归残差向量的最后一个值 | m_ols3d_last_resid(y, x1, x2, x3, 5) |
| m_pct_rank | 时间序列上 arg 在该窗口内的相对（百分数）排名 | m_pct_rank(close, 5, method:='min', ascending:=true) |
| m_product | 时间序列上 arg 在该窗口内的乘积 | m_product(arg, 5) |
| m_quantile | 时间序列上 x 在该窗口内 pos 处的（最近的确切）分位数 | m_quantile(x, 0.5, 5) |
| m_quantile_cont | 时间序列上 x 在该窗口内 pos 处的插值分位数 | m_quantile_cont(x, 0.5, 5) |
| m_quantile_disc | 时间序列上 x 在该窗口内 pos 处的最近的确切分位数 | m_quantile_disc(x, 0.5, 5) |
| m_rank | 时间序列上 arg 在该窗口内的排名. O(n*w) 的时间复杂度, 适合小窗口 | m_rank(close, 5, method:='min', ascending:=true) |
| m_regr_avgx | 时间序列上 y 和 x 在该窗口内的非空对的自变量的平均值 | m_regr_avgx(y, x, 5) |
| m_regr_avgy | 时间序列上 y 和 x 在该窗口内的非空对的因变量的平均值 | m_regr_avgy(y, x, 5) |
| m_regr_count | 时间序列上 y 和 x 在该窗口内的非空个数 | m_regr_count(y, x, 5) |
| m_regr_intercept | 时间序列上 y 和 x 在该窗口内的截距 | m_regr_intercept(y, x, 5) |
| m_regr_r2 | 时间序列上 y 和 x 在该窗口内的非空对的决定系数 | m_regr_r2(y, x, 5) |
| m_regr_slope | 时间序列上 y 和 x 在该窗口内的斜率 | m_regr_slope(y, x, 5) |
| m_regr_sxx | 时间序列上 y 和 x 在该窗口内的 Sxx: REGR_COUNT(y, x) * VAR_POP(x) | m_regr_sxx(y, x, 5) |
| m_regr_sxy | 时间序列上 y 和 x 在该窗口内的总体协方差 Sxy: REGR_COUNT(y, x) * COVAR_POP(y, x) | m_regr_sxy(y, x, 5) |
| m_regr_syy | 时间序列上 y 和 x 在该窗口内的 Syy: REGR_COUNT(y, x) * VAR_POP(y) | m_regr_syy(y, x, 5) |
| m_reservoir_quantile | 时间序列上 x 在该窗口内的由 Reservoir Sampling 得出的近似分位数 | m_reservoir_quantile(x, 0.5, 1024, 5) |
| m_rolling_rank | 时间序列上 arg 在该窗口内的排名. O(n*log(w)) 的时间复杂度, 适合大窗口 | m_rolling_rank(close, 100, method:='min', ascending:=true) |
| m_shift | m_shift(x, d), d天以前的x值。如果d为负数，则表示abs(d)天以后的值 | m_shift(close, 5), m_shift(close, -5) |
| m_skewness | 时间序列上 x 在该窗口内的偏度 | m_skewness(x, 5) |
| m_std_pop_greatest_k | 时间序列上 val 在该窗口内最大 k 个数对应的 arg 的总体标准差 | m_std_pop_greatest_k(arg, val, w, k) |
| m_std_pop_least_k | 时间序列上 val 在该窗口内最小 k 个数对应的 arg 的总体标准差 | m_std_pop_least_k(arg, val, w, k) |
| m_std_samp_greatest_k | 时间序列上 val 在该窗口内最大 k 个数对应的 arg 的样本标准差 | m_std_samp_greatest_k(arg, val, w, k) |
| m_std_samp_least_k | 时间序列上 val 在该窗口内最小 k 个数对应的 arg 的样本标准差 | m_std_samp_least_k(arg, val, w, k) |
| m_stddev | 时间序列上 x 在该窗口内的（样本）标准差 | m_stddev(x, 5) |
| m_stddev_pop | 时间序列上 x 在该窗口内的总体标准差 | m_stddev_pop(x, 5) |
| m_stddev_samp | 时间序列上 x 在该窗口内的样本标准差 | m_stddev_samp(x, 5) |
| m_sum | 时间序列上 arg 在该窗口内的和 | m_sum(arg, 5) |
| m_sum_gl_k_delta | 时间序列上 val 在该窗口内最大 k 个数对应的 arg 的累加和与最小 k 个数对应的 arg 的累加和的差值 | m_sum_gl_k_delta(change_ratio, amount/deal_number, 20, 10) |
| m_sum_greatest_k | 时间序列上 val 在该窗口内最大 k 个数对应的 arg 的累加和 | m_sum_greatest_k(change_ratio, amount/deal_number, 20, 10) |
| m_sum_least_k | 时间序列上 val 在该窗口内最小 k 个数对应的 arg 的累加和 | m_sum_least_k(change_ratio, amount/deal_number, 20, 10) |
| m_ta_2crows | 时间序列上的两只乌鸦 | m_ta_2crows(open, high, low, close) |
| m_ta_3black_crows | 时间序列上的三只乌鸦 | m_ta_3black_crows(open, high, low, close) |
| m_ta_3red_soldiers | 时间序列上的红三兵 | m_ta_3red_soldiers(open, high, low, close) |
| m_ta_ad | 时间序列上的 Chaikin A/D (累积分布) 线 | m_ta_ad(high, low, close, volume) |
| m_ta_adx | 时间序列上该窗口内的平均趋向指数 | m_ta_adx(high, low, close, 5) |
| m_ta_adxr | 时间序列上该窗口内的平均趋向指数评估（⚠ 口径未证实——经典定义为 Wilder/EMA 系，BigQuant 实现可能为 SMA/其他平滑；用于策略判定前先小样本对照本地重算，见 SKILL.md 移植 checklist 第 1 条） | m_ta_adxr(high, low, close, 5) |
| m_ta_aroon | 时间序列上的阿隆 (Aroon) 指标, 返回 list: [aroon_down, aroon_up] | m_ta_aroon(high, low, 14) |
| m_ta_aroon_d | 时间序列上的阿隆 (Aroon) 指标中的 aroon_down | m_ta_aroon_d(high, low, 14) |
| m_ta_aroon_u | 时间序列上的阿隆 (Aroon) 指标中的 aroon_up | m_ta_aroon_u(high, low, 14) |
| m_ta_aroonosc | 时间序列上的阿隆振荡器 (Aroon Oscillator) 指标 | m_ta_aroonosc(high, low, 14) |
| m_ta_atr | 时间序列上该窗口内的真实波动幅度均值（= `m_avg(TR)` 即 **SMA 口径，非 Wilder RMA**——与 pandas `ewm(alpha=1/n)` 在 TR 突变期差 3~16%，吊灯止损/波动率目标类策略需 Python 兜底重算对齐，见 SKILL.md 移植 checklist） | m_ta_atr(high, low, close, 5) |
| m_ta_bbands | 时间序列上的布林带, 返回 list: [upper_band, middle_band, lower_band] | m_ta_bbands(close, timeperiod:=5, nbdevup:=2.0, nbdevdn:=2.0, matype:=0) |
| m_ta_bbands_l | 时间序列上的布林带中的 lower_band | m_ta_bbands_l(close, timeperiod:=5, nbdevup:=2.0, nbdevdn:=2.0, matype:=0) |
| m_ta_bbands_m | 时间序列上的布林带中的 middle_band | m_ta_bbands_m(close, timeperiod:=5, nbdevup:=2.0, nbdevdn:=2.0, matype:=0) |
| m_ta_bbands_u | 时间序列上的布林带中的 upper_band | m_ta_bbands_u(close, timeperiod:=5, nbdevup:=2.0, nbdevdn:=2.0, matype:=0) |
| m_ta_beta | 时间序列上 x, y 在该窗口内的贝塔系数 | m_ta_beta(open, close, 5) |
| m_ta_bias | (close - sma) / sma | m_ta_bias(close, 3) |
| m_ta_cci | 时间序列上该窗口内的顺势指标 | m_ta_cci(high, low, close, 5) |
| m_ta_dark_cloud_cover | 时间序列上的乌云盖顶 | m_ta_dark_cloud_cover(open, high, low, close, penetration:=0.5) |
| m_ta_dema | 时间序列上 arg 在该窗口内的双指数移动平均 | m_ta_dema(close, 5) |
| m_ta_ema | 时间序列上 arg 在该窗口内的指数均值（⚠ alpha 是 2/(n+1)[pandas span] 还是 1/n[Wilder] 未证实，两种相差明显） | m_ta_ema(close, 5) |
| m_ta_evening_star | 时间序列上的黄昏之星 | m_ta_evening_star(open, high, low, close, penetration:=0.3) |
| m_ta_ewm | 时间序列上 arg 在窗口大小为 m 的指数加权移动平均, alpha=n/m, 有 NULL 则发生截断重新开始计算. 对应 bigexpr 中的 ta_sma2(x,M,N) | m_ta_ewm(close, 3, 1) |
| m_ta_hammer | 时间序列上的锤 | m_ta_hammer(open, high, low, close) |
| m_ta_inverted_hammer | 时间序列上的倒锤 | m_ta_inverted_hammer(open, high, low, close) |
| m_ta_kama | 时间序列上 arg 在该窗口内的 Kaufman 自适应移动平均 | m_ta_kama(close, 5) |
| m_ta_kdj | 时间序列上的 [K, D, J] 值. slowk_period, slowd_period 做变换 x -> 2x-1 后传入 ta_stoch | m_ta_kdj(high, low, close, fastk_period:=9, slowk_period:=3, slowd_period:=3, slowk_matype:=1, slowd_matype:=1) |
| m_ta_kdj_d | 时间序列上 kdj 中的 D 值. slowk_period, slowd_period 做变换 x -> 2x-1 后传入 ta_stoch | m_ta_kdj_d(high, low, close, fastk_period:=9, slowk_period:=3, slowd_period:=3, slowk_matype:=1, slowd_matype:=1) |
| m_ta_kdj_j | 时间序列上的 J 值 (= 3K - 2D). slowk_period, slowd_period 做变换 x -> 2x-1 后传入 ta_stoch | m_ta_kdj_j(high, low, close, fastk_period:=9, slowk_period:=3, slowd_period:=3, slowk_matype:=1, slowd_matype:=1) |
| m_ta_kdj_k | 时间序列上 kdj 中的 K 值. slowk_period, slowd_period 做变换 x -> 2x-1 后传入 ta_stoch | m_ta_kdj_k(high, low, close, fastk_period:=9, slowk_period:=3, slowd_period:=3, slowk_matype:=1, slowd_matype:=1) |
| m_ta_macd | 时间序列上的移动平均收敛/发散指标, 返回 list: [macd, macd_signal, macd_hist] | m_ta_macd(close, fastperiod:=12, slowperiod:=26, signalperiod:=9) |
| m_ta_macd_dea | 时间序列上的 macd 指标的第二列: '讯号线' (DEA), DIF 的 9 日移动平均 | m_ta_macd_dea(close, fastperiod:=12, slowperiod:=26, signalperiod:=9) |
| m_ta_macd_dif | 时间序列上的 macd 指标的第一列: '差离值' (DIF) | m_ta_macd_dif(close, fastperiod:=12, slowperiod:=26, signalperiod:=9) |
| m_ta_macd_hist | 时间序列上的 macd 指标的第三列的 2 倍: 放大后的柱状图 (HIST), (DIF - DEA) * 2 | m_ta_macd_hist(close, fastperiod:=12, slowperiod:=26, signalperiod:=9) |
| m_ta_mfi | 时间序列上该窗口内的货币流量指数 | m_ta_mfi(high, low, close, volume, 5) |
| m_ta_mom | 时间序列上 arg 在该窗口内的动量 | m_ta_mom(close, 5) |
| m_ta_morning_star | 时间序列上的早晨之星 | m_ta_morning_star(open, high, low, close, penetration:=0.3) |
| m_ta_obv | 时间序列上的能量潮 | m_ta_obv(close, volume) |
| m_ta_roc | 时间序列上 arg 在该窗口内的变化率 | m_ta_roc(close, 5) |
| m_ta_rsi | 时间序列上 arg 在该窗口内的相对强弱指数（⚠ 经典定义用 Wilder RMA 平滑，BigQuant 口径未证实） | m_ta_rsi(close, 5) |
| m_ta_sar | 时间序列上的抛物线转向 (SAR) 指标 | m_ta_sar(high, low, acceleration:=0.02, maximum:=0.2) |
| m_ta_shooting_star | 时间序列上的流星线 | m_ta_shooting_star(open, high, low, close) |
| m_ta_sma | 时间序列上 arg 在该窗口内的简单平均值 | m_ta_sma(close, 5) |
| m_ta_stoch | 时间序列上的 K, D 值. slowk_period, slowd_period 做变换 x -> 2x-1 后传入 ta_stoch | m_ta_stoch(high, low, close, fastk_period:=9, slowk_period:=3, slowd_period:=3, slowk_matype:=1, slowd_matype:=1) |
| m_ta_sum | 时间序列上 arg 在该窗口内的和 | m_ta_sum(close, 5) |
| m_ta_tema | 时间序列上 arg 在该窗口内的三重指数移动平均 | m_ta_tema(close, 5) |
| m_ta_trima | 时间序列上 arg 在该窗口内的三角移动平均 | m_ta_trima(close, 5) |
| m_ta_trix | 时间序列上 arg 在该窗口内的三重指数平滑平均线（⚠ 口径未证实——经典定义为 Wilder/EMA 系，BigQuant 实现可能为 SMA/其他平滑；用于策略判定前先小样本对照本地重算，见 SKILL.md 移植 checklist 第 1 条） | m_ta_trix(close, 5) |
| m_ta_willr | 时间序列上该窗口内的威廉指标 | m_ta_willr(high, low, close, 5) |
| m_ta_wma | 时间序列上 arg 在该窗口内的加权均值 | m_ta_wma(close, 5) |
| m_var_pop | 时间序列上 x 在该窗口内的总体方差 | m_var_pop(x, 5) |
| m_var_pop_greatest_k | 时间序列上 val 在该窗口内最大 k 个数对应的 arg 的总体方差 | m_var_pop_greatest_k(arg, val, w, k) |
| m_var_pop_least_k | 时间序列上 val 在该窗口内最小 k 个数对应的 arg 的总体方差 | m_var_pop_least_k(arg, val, w, k) |
| m_var_samp | 时间序列上 x 在该窗口内的样本方差 | m_var_samp(x, 5) |
| m_var_samp_greatest_k | 时间序列上 val 在该窗口内最大 k 个数对应的 arg 的样本方差 | m_var_samp_greatest_k(arg, val, w, k) |
| m_var_samp_least_k | 时间序列上 val 在该窗口内最小 k 个数对应的 arg 的样本方差 | m_var_samp_least_k(arg, val, w, k) |
| m_variance | 时间序列上 x 在该窗口内的（样本）方差 | m_variance(x, 5) |
| m_weighted_avg | 在时间序列上做窗口加权平均；x 为值，d 为窗口大小，比如4，weight 为权重，比如市值 | m_weighted_avg(x, 4, weight) |
| m_weighted_stddev | 在时间序列上做窗口加权标准差；x 为值，d 为窗口大小，比如4，weight 为权重，比如市值 | m_weighted_stddev(x, 4, weight) |
| m_winsorize_nsigma | 在时间序列上通过n-sigma规则去极值；n为标准差倍数，默认为3，d为窗口大小，比如4 | m_winsorize_nsigma(x, 4, n:=3) |
| m_winsorize_weighted_nsigma | 在时间序列上通过n-sigma规则去极值；n为加权标准差倍数，默认为3，d为窗口大小，比如4，weight 为权重，比如市值 | m_winsorize_weighted_nsigma(x, 4, weight, n:=3) |
| map_contains_entry | 返回 map 是否包含键值对 key: value | map_contains_entry(MAP {'key1': 10, 'key2': 20, 'key3': 30}, 'key2', 20) |
| map_contains_value | 返回 map 是否包含值 value | map_contains_value(MAP {'key1': 10, 'key2': 20, 'key3': 30}, 20) |
| ntile | 按照 ob 排序后尽可能分成 num_buckets 等份, 并算出当前行所在的桶号（从 1 开始） | ntile(4, close, ascending:=true) |
| ntile_by | 依据 pb 分组后并按照 ob 排序后尽可能分成 num_buckets 等份, 并算出当前行所在的桶号（从 1 开始） | ntile_by(4, date, close, ascending:=true) |
| nullif | 若 a=b, 则返回 NULL; 否则返回 a | nullif(a, b) |
| nullifgt | 若 a > b, 则返回 NULL; 否则返回 a | nullifgt(a, b) |
| nulliflt | 若 a < b, 则返回 NULL; 否则返回 a | nulliflt(a, b) |
| pct_rank | 按照参数 ob 排序后的相对（百分数）排名 | pct_rank(close, ascending:=true) |
| pct_rank_by | 依据 pb 分组后并按照 ob 做组内排序后的相对（百分数）排名 | pct_rank_by(date, close, ascending:=true): 按 date 分组后每只股票每天在所有股票中开盘价的相对排名 |
| rank | 按照参数 ob 排序后的排名 | rank(close, ascending:=true) |
| rank_by | 依据 pb 分组后并按照 ob 做组内排序后的排名 | rank_by(date, close, ascending:=true): 按 date 分组后每只股票每天在所有股票中开盘价的排名 |
| round_even | 把 x 四舍五入到 n 位小数，如果第 n+1 位及之后刚好为 5, 则取 round(x/2, n) * 2, 否则为 round(x, n)。e.g. round_even(1.2250, 2) = 1.22, round_even(1.2350, 2) = 1.24 | round_even(1.2345, 2) = 1.23 |
| roundbankers | round_even(x, n) 的别名 | roundbankers(x, 3) |
| row_number | 按照 ob 排序后每行所处的行号 | row_number(close, ascending:=true) |
| row_number_by | 依据 pb 分组后并按照 ob 排序后每行在该分组内所处的行号 | row_number_by(date, close, ascending:=true) |
| sigmoid | sigmoid 函数: 1 / (1 + exp(-x)) | sigmoid(high) |
| signedpower | if (x > 0, 1, -1) * (\|x\| ^ a) | signedpower(-2, 4) = -16 |
| split_part | 返回字符串 string 用分隔符 delimiter 分割后的第 position 个子串 | split_part('abc,def,ghi', ',', 2) |
| ts_rank | 在时间序列上对 x 做排名，并返回一个在 [0.0, 1.0] 范围内的值，d 为窗口大小，比如4 | ts_rank(x, 4) |
| ts_scale | 在时间序列上对 x 做缩放处理，d 为窗口大小，比如4 | ts_scale(x, 4) |
| ts_zscore | 在时间序列上对 x 做 z-score 标准化处理，d 为窗口大小，比如4 | ts_zscore(x, 4) |

##### 新旧表达式差异
我们使用新版的sql语句来计算旧版预计算因子, 经统计我们发现了如下差异.

| 因子 | 含义或计算公式 | 旧版 | 新版 | 对比 |
|---|---|---|---|---|
| 成交量 | 当期成交量 | amount_0 | amount AS amount_0 | 完全一致 |
| 成交量 | 滞后五期成交量 | amount_5 | m_lag(amount, 5) AS amount_5 | 完全一致 |
| 收益率 | 收盘价除以过去一期收盘价 | return_0 | close / m_lag(close, 1) AS return_0 | 完全一致 |
| 收益率 | 收盘价除以过去五期的收盘价 | return_5 | close / m_lag(close, 6) AS return_5 | 完全一致 |
| 成交量 | 当期成交量 | avg_amount_0 | amount AS avg_amount_0 | 完全一致 |
| 成交量 | 过去五期成交量平均值 | avg_amount_5 | m_avg(amount, 6) AS avg_amount_5 | 完全一致 |
| 收益率 | 收盘价除以过去一期收盘价 | daily_return_0 | close / m_lag(close, 1) AS daily_return_0 | 完全一致 |
| 收益率 | 过去五期收盘价除以过去六期收盘价 | daily_return_5 | m_lag(close, 5) / m_lag(close, 6) AS daily_return_5 | 完全一致 |
| 成交额排名 | 当期成交额截面排名 | rank_amount_0 | c_pct_rank(amount) AS rank_amount_0 | 完全一致 |
| 成交额排名 | 过去五期成交额截面排名 | rank_amount_5 | c_pct_rank(m_lag(amount, 5)) AS rank_amount_5 | 新旧版本在某个时点上票的数量不一致, 即便换手率一致, 最后计算出的排名依旧会有细微差异. |
| 成交额排名 | 当期成交额截面排名 | rank_avg_amount_0 | c_pct_rank(amount) AS rank_avg_amount_0 | 完全一致 |
| 成交额排名 | 过去五期区间成交额截面排名 | rank_avg_amount_5 | c_pct_rank(m_avg(amount , 6)) AS rank_avg_amount_5 | 旧版计算时序移动平均时会跳过缺失值, sql会将缺失值加上, 导致某些票当日缺失, 进一步剔除缺失值后导致截面股票个数不一致, 最后影响到了排名, 所以新旧因子有略微差别. |
| 换手率 | 当期换手率 | turn_0 | turn * 100 AS turn_0 | 完全一致 |
| 换手率 | 过去五期换手率 | turn_5 | m_lag(turn, 5) * 100 AS turn_5 | 完全一致 |
| 换手率 | 当期换手率 | avg_turn_0 | turn * 100 AS avg_turn_0 | 完全一致 |
| 换手率 | 迄今为止过去五期的换手率平均值 | avg_turn_5 | m_avg(turn, 6)*100 AS avg_turn_5 | 完全一致(在没有缺失值的前提下) |
| 换手率排名 | 当期换手率截面排名 | rank_turn_0 | c_pct_rank(turn * 100) AS rank_turn_0 | 新旧版本在某个时点上票的数量不一致, 即便换手率一致, 最后计算出的排名依旧会有细微差异. |
| 换手率排名 | 过去五期换手率截面排名 | rank_turn_5 | c_pct_rank(m_lag(turn , 5) * 100) AS rank_turn_5 | 同上 |
| 换手率排名 | 当期换手率截面排名 | rank_avg_turn_0 | c_pct_rank(turn * 100) AS rank_avg_turn_0 | 完全一致 |
| 上市板块 | 主板：1，中小企业板：2，创业板：3 | list_board_0 | list_sector AS list_board_0 | 完全一致 |
| 上市天数 | 上市天数 | list_days_0 | list_days AS list_days_0 | 完全一致 |
| 股票状态 | 0-正常, 1-ST, 2-*ST, | st_status_0 | st_status AS st_status_0 | 完全一致 |
| 估值 | 当期总市值 | market_cap_0 | total_market_cap AS market_cap_0 | 完全一致 |
| 估值 | 公式=当日总市值/归母净利润TTM | pe_ttm_0 | pe_ttm AS pe_ttm_0 | 完全一致 |
| 振幅波动率 | 5日振幅的标准差，振幅为当日最高价减去最低价. | swing_volatility_5_0 | m_stddev((high-low) / close, 5) AS swing_volatility_5_0 | 完全一致 |
| 波动率 | 过去五日的return组成的样本标准差 | volatility_5_0 | m_stddev(close / m_lag(close, 1)-1, 5) AS volatility_5_0 | 完全一致 |

标签：

函数

[ac23](https://bigquant.com/u/f9695004-592f-4620-97e1-b7693810c42f)Lv2 · 五月 06,2024

[bqo4nx2d](https://bigquant.com/u/0c781771-6be3-4946-ada6-ac4916613c05)Lv11 · 六月 24,2024

[yewfei](https://bigquant.com/u/43e76516-0f38-11ed-93bb-da75731aa77c)Lv14 · 八月 20,2024

[bq0m8rec](https://bigquant.com/u/4b7d44d5-e617-424a-9628-a930c987c267)Lv9 · 七月 08,2025

[yewfei](https://bigquant.com/u/43e76516-0f38-11ed-93bb-da75731aa77c)Lv14 · 八月 21,2024

[bq0m8rec](https://bigquant.com/u/4b7d44d5-e617-424a-9628-a930c987c267)Lv9 · 七月 08,2025

[把风拥入怀](https://bigquant.com/u/8f4f5db2-9227-4a6e-b1e9-3a0db6aa23bf)Lv6 · 十月 02,2024

[bq0m8rec](https://bigquant.com/u/4b7d44d5-e617-424a-9628-a930c987c267)Lv9 · 七月 08,2025
