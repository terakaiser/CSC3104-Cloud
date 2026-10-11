"""Readable names and summaries for saved results and terminal output."""
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo


METRIC_NAMES = {
    "threshold": "fraud_score_threshold",
    "precision": "fraud_precision",
    "recall": "fraud_recall",
    "f1": "fraud_f1_score",
    "pr_auc": "average_precision",
    "false_positive_rate": "false_alarm_rate",
    "tp": "fraud_detected",
    "fn": "fraud_missed",
    "fp": "legitimate_transactions_flagged",
    "tn": "legitimate_transactions_cleared",
    "round": "training_round",
    "clients": "banks_responded",
    "training_rows": "training_transactions",
    "fraud_rows": "fraud_training_transactions",
    "epoch_losses": "training_loss_by_epoch",
    "train_loss": "training_loss",
    "train_seconds": "average_bank_training_seconds",
}


def readable_metrics(metrics):
    """Rename exported keys; retain numeric values and internal compatibility."""
    return {METRIC_NAMES.get(key, key): value for key, value in metrics.items()}


def create_run_directory(output_dir, name):
    stamp = datetime.now(ZoneInfo("Asia/Singapore")).strftime("%Y-%m-%d_%H-%M-%S_SGT")
    directory = Path(output_dir) / f"{name}__{stamp}__{uuid4().hex[:6]}"
    directory.mkdir(parents=True, exist_ok=False)
    return directory


def format_summary(metrics, *, title="Validation results"):
    def number(key):
        value = metrics.get(key)
        return "not available" if value is None else f"{value:.4f}"

    return "\n".join([
        title,
        f"  Fraud precision (correct flags): {100 * metrics['precision']:.2f}%",
        f"  Fraud recall (fraud caught):     {100 * metrics['recall']:.2f}%",
        f"  Fraud F1 score:                 {number('f1')}",
        f"  Average precision:              {number('pr_auc')}",
        f"  ROC-AUC:                        {number('roc_auc')}",
        f"  Fraud score threshold:          {number('threshold')}",
        f"  Fraud detected:                 {metrics['tp']:,}",
        f"  Fraud missed:                   {metrics['fn']:,}",
        f"  Legitimate transactions flagged:{metrics['fp']:>10,}",
        f"  Legitimate transactions cleared:{metrics['tn']:>10,}",
    ])


def save_summary(directory, metrics, *, title="Validation results"):
    summary = format_summary(metrics, title=title)
    note = "\n\nValidation scores guide development; they are not final test results.\n"
    Path(directory, "results_summary.txt").write_text(summary + note, encoding="utf-8")
    print(summary, flush=True)
