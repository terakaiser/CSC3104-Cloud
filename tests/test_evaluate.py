import numpy as np

from experiments.evaluate import metrics


def test_metrics_use_fraud_as_positive_and_correct_false_positive_denominator():
    result = metrics(np.array([0, 0, 1, 1]), np.array([0.1, 0.8, 0.2, 0.9]), 0.5)
    assert result["precision"] == result["recall"] == result["f1"] == 0.5
    assert result["false_positive_rate"] == 0.5
    assert result["roc_auc"] == 0.75
