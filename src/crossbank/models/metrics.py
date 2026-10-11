import numpy as np
from sklearn.metrics import precision_score, recall_score, f1_score, average_precision_score, roc_auc_score, confusion_matrix, precision_recall_curve


def select_threshold(y, probabilities):
    """Maximise validation F1; require both classes for meaningful selection."""
    y, probabilities = np.asarray(y), np.asarray(probabilities)
    if y.ndim != 1 or probabilities.shape != y.shape or len(y) == 0:
        raise ValueError("Expected nonempty labels and matching probabilities")
    if set(np.unique(y)) != {0, 1} or not np.isfinite(probabilities).all():
        raise ValueError("Threshold selection requires both classes and finite probabilities")
    precision, recall, thresholds = precision_recall_curve(y, probabilities)
    f1 = 2 * precision[:-1] * recall[:-1] / (precision[:-1] + recall[:-1] + 1e-12)
    return float(thresholds[np.argmax(f1)])

def evaluate(y, probabilities, threshold=.5):
    y = np.asarray(y).astype(int)
    pred = (np.asarray(probabilities)>=threshold).astype(int)
    tn,fp,fn,tp = confusion_matrix(y,pred,labels=[0,1]).ravel()
    return {
        "precision": float(precision_score(y,pred,zero_division=0)),
        "recall": float(recall_score(y,pred,zero_division=0)),
        "f1": float(f1_score(y,pred,zero_division=0)),
        "pr_auc": float(average_precision_score(y,probabilities)) if len(set(y))==2 else None,
        "roc_auc": float(roc_auc_score(y,probabilities)) if len(set(y))==2 else None,
        "false_positive_rate": float(fp/(fp+tn)) if fp+tn else None,
        "tp": int(tp), "fp": int(fp), "fn": int(fn), "tn": int(tn)
    }
