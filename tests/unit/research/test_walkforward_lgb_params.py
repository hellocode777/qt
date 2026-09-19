"""WalkForwardScorer 的 lgb_params 覆盖（#1 / TDR-005 收尾，2026-09-19）。

背景：Optuna 搜出的最优参数此前**无处落盘**（WalkForwardScorer 内部硬编码
DEFAULT_LGB_PARAMS）。为了能验证「最优参数在时间序外推下是否真的更好」，
新增可选参数 `lgb_params`，默认 None → 生产行为完全不变。
"""

from __future__ import annotations

from qp.research.model_trainer import WalkForwardScorer
from qp.research.trainer.lgb_rank import DEFAULT_LGB_PARAMS


class TestLgbParamsOverride:
    def test_default_is_none(self) -> None:
        """默认不覆盖 → 保持生产行为（用 DEFAULT_LGB_PARAMS）。"""
        scorer = WalkForwardScorer()
        assert scorer._lgb_params_override is None

    def test_custom_params_are_kept(self) -> None:
        custom = {"num_leaves": 102, "learning_rate": 0.045}
        scorer = WalkForwardScorer(lgb_params=custom)
        assert scorer._lgb_params_override == custom

    def test_override_merges_over_defaults(self) -> None:
        """合并语义：覆盖项优先，其余键回落到 DEFAULT_LGB_PARAMS。"""
        scorer = WalkForwardScorer(lgb_params={"num_leaves": 102})
        merged = {**DEFAULT_LGB_PARAMS, **(scorer._lgb_params_override or {})}
        assert merged["num_leaves"] == 102
        assert merged["max_depth"] == DEFAULT_LGB_PARAMS["max_depth"]

    def test_other_constructor_args_unchanged(self) -> None:
        """新增参数不影响既有构造签名。"""
        scorer = WalkForwardScorer(train_window_days=252, forward_window=5)
        assert scorer.train_window_days == 252
        assert scorer.forward_window == 5
