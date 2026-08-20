# TDR-001: 数据源（AkShare → 腾讯唯一主源 + AkShare 复权因子）

> Technology Decision Record — 数据源（2026-08-14 修订，2026-08-20 更新）

## 选择

**行情主源：腾讯 Finance API**（`kline/kline`，不复权原始价）— **唯一数据源**
**复权因子：AkShare**（`stock_zh_a_daily(adjust="qfq-factor")`）— 独立因子表
**指数数据：腾讯 Finance API**（`kline/kline`，同主源）— 上证 sh000001 / 沪深300 sh000300

## 理由

- 腾讯 `kline/kline` 无复权参数返回干净原始价（已验证 600438 2015-2026 全历史无坏数据）
- AkShare qfq-factor 提供标准复权因子表（`[ex_date, qfq_factor]`，最新除权日=1.0）
- 全库统一「不复权原始价」，消除复权状态混存事故（2026-08-14）
- 免费、无 API Key 依赖
- 多源 fallback 已被废弃：新浪/akshare 行情的复权状态与腾讯不一致，
  曾污染 `daily_price_latest`（2026-08-14 事故），`--source` 仅接受 tencent

## ⛔ 废弃

- **腾讯 `fqkline/get` + `qfq` 接口**：负价格坏数据 bug（600438 2018-10 实证），禁止使用
- **akshare `adjust="qfq"/"hfq"` 写入价格表**：复权价混入原始价表，禁止
- **新浪 `getKLineData`（作为行情源）**：复权状态与腾讯不一致，2026-08-14 起废弃，
  显式 `--source=sina` 必须 FAILED（`qp/data/pipeline.py`，测试见
  `tests/unit/data/test_pipeline_non_demo.py::test_source_sina_rejected`）
- **akshare 指数拉取（`stock_zh_index_daily`）**：2026-08-20 起指数数据统一改走
  腾讯 `kline/kline`，不再保留 AkShare 网络依赖（`qp/data/dataset/index_provider.py`）

## 使用方式

通过 `BaseDataSource` 适配器封装，消费者永远不知道数据来自哪个源（ADR-013, ADR-017）。

```python
# qp/data/adapter/ 中的适配器
class TencentAdapter(BaseDataSource):   # kline/kline 无复权参数（唯一行情源）
    def fetch_raw(self, start_date, end_date, **kwargs): ...

class AKShareAdapter(BaseDataSource):   # 仅用于复权因子表，不拉行情
    def get_adjust_factor(self, symbols, ...): ...  # qfq-factor 因子表

# qp/data/dataset/index_provider.py
fetch_index_data(symbol="sh000001")  # 指数：腾讯 kline/kline，同主源

# qp/data/dataset/adjust_factor.py
close_qfq = close_raw / qfq_factor  # 公式（实测验证）
```

## 配置

```toml
[data]
default_source = "tencent"  # 唯一主源；sina/akshare 行情已废弃，不接受 fallback
```
