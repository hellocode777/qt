# TDR-009: APScheduler

> Technology Decision Record — 任务调度

## 选择

**APScheduler** — Python 进程内任务调度器。

## 理由

- 进程内调度，无需外部依赖（无 Airflow/Celery 运维负担）
- 支持 Cron 表达式
- 支持持久化作业存储
- 与 systemd timer 配合：systemd 触发 → CLI → APScheduler 执行

## 使用方式

```python
from qp.platform.scheduler.registry import JobRegistry

# 注册 Job
registry = JobRegistry()
registry.register(
    name="daily_pipeline",
    trigger="cron",
    hour=18, minute=0,
    func="qp.pipeline.daily_pipeline:DailyPipeline.run",
)
```

## 调度架构

```
systemd timer → qp scheduler start → APScheduler → Job.run()
```

## 五任务时间表

| 时间 | Job | 功能 |
|------|-----|------|
| 09:07 | `monitor_check` | KillSwitchPipeline 全扫描 |
| 09:17 | `retrain_notify` | 重训信号通知 |
| 16:53 | `pre_close_check` | 收盘前二次确认 |
| 18:00 | `daily_pipeline` | 策略决策管道 |
| 18:30 | `email_report` | 邮件报告 |

## 替代方案评估

| 方案 | 优点 | 缺点 |
|------|------|------|
| Airflow | DAG 可视化 | 运维重 |
| Celery | 分布式 | 需要 Redis/RabbitMQ |
| cron | 系统自带 | Python 集成弱 |
| **APScheduler** ✅ | 嵌入+轻量 | 单机 |

## 配置

```toml
[scheduler]
timezone = "Asia/Shanghai"
```
