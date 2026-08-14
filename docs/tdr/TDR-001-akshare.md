# TDR-001: 数据源（AkShare → 腾讯主源 + AkShare 复权因子）

> Technology Decision Record — 数据源（2026-08-14 修订）

## 选择

**主源：腾讯 Finance API**（`kline/kline`，不复权原始价）— 长历史主源
**复权因子：AkShare**（`stock_zh_a_daily(adjust="qfq-factor")`）— 独立因子表
**辅助源：新浪**（`getKLineData`，不复权原始价）— 近期增量 + 交叉验证

## 理由

- 腾讯 `kline/kline` 无复权参数返回干净原始价（已验证 600438 2015-2026 全历史无坏数据）
- AkShare qfq-factor 提供标准复权因子表（`[ex_date, qfq_factor]`，最新除权日=1.0）
- 三源全部对齐「不复权原始价」，消除复权状态混存事故（2026-08-14）
- 免费、无 API Key 依赖

## ⛔ 废弃

- **腾讯 `fqkline/get` + `qfq` 接口**：负价格坏数据 bug（600438 2018-10 实证），禁止使用
- **akshare `adjust="qfq"/"hfq"` 写入价格表**：复权价混入原始价表，禁止

## 使用方式

通过 `BaseDataSource` 适配器封装，消费者永远不知道数据来自哪个源（ADR-013, ADR-017）。

```python
# qp/data/adapter/ 中的适配器
class TencentAdapter(BaseDataSource):   # kline/kline 无复权参数
    def fetch_raw(self, start_date, end_date, **kwargs): ...

class AKShareAdapter(BaseDataSource):   # fetch_raw 用 adjust=""
    def fetch_raw(self, start_date, end_date, **kwargs): ...
    def get_adjust_factor(self, symbols, ...): ...  # qfq-factor 因子表

# qp/data/dataset/adjust_factor.py
close_qfq = close_raw / qfq_factor  # 公式（实测验证）
```

## 配置

```toml
[data]
default_source = "tencent"  # 主源；sina/akshare 为辅助
```
