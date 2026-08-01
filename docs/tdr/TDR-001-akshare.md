# TDR-001: AkShare

> Technology Decision Record — 数据源

## 选择

**AkShare** — 开源 A 股金融数据接口库。

## 理由

- 免费、无 API Key 依赖（降低个人使用门槛）
- 覆盖 A 股日线、分钟线、财务数据、行业分类
- 纯 Python 实现，与项目技术栈一致
- 活跃维护，社区支持好

## 使用方式

通过 `BaseDataSource` 适配器封装，消费者永远不知道数据来自 AkShare（ADR-013, ADR-017）。

```python
# qp/data/adapter/ 中的适配器
class AkShareAdapter(BaseDataSource):
    def fetch_raw(self, start_date, end_date, **kwargs):
        # 调用 ak.stock_zh_a_hist(...)
        ...
```

## 替代方案评估

| 方案 | 优点 | 缺点 |
|------|------|------|
| Tushare | 数据质量高 | 需要积分/付费 |
| Baostock | 免费 | 数据更新慢 |
| **AkShare** ✅ | 免费、活跃 | 接口偶尔变动 |

## 配置

```toml
[data]
default_source = "akshare"
```
