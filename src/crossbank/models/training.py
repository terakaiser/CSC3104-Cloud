"""CPU training and batched prediction shared by every MLP experiment."""
import numpy as np
import torch
from torch.utils.data import DataLoader, TensorDataset


def seed_everything(seed: int):
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.set_num_threads(1)


def train_model(model, X, y, *, epochs=1, batch_size=1024, learning_rate=0.001, seed=42):
    """Update model in place; return sample-weighted mean loss for each epoch.

    Adam is restarted on each call, including each federated round. A single-class
    bank uses unweighted BCE rather than a zero/infinite positive-class weight.
    """
    if epochs < 1 or batch_size < 1 or not np.isfinite(learning_rate) or learning_rate <= 0:
        raise ValueError("epochs, batch_size and learning_rate must be positive")
    X, y = np.asarray(X, dtype=np.float32), np.asarray(y, dtype=np.float32)
    if X.ndim != 2 or y.ndim != 1 or len(X) != len(y) or len(y) == 0:
        raise ValueError("Expected nonempty X rows and matching one-dimensional labels")
    if not np.isfinite(X).all() or not np.isfinite(y).all() or not np.isin(y, [0, 1]).all():
        raise ValueError("Features must be finite and labels binary")
    seed_everything(seed)
    generator = torch.Generator().manual_seed(seed)
    loader = DataLoader(TensorDataset(torch.from_numpy(X), torch.from_numpy(y)),
                        batch_size=batch_size, shuffle=True, generator=generator)
    positive = float(y.sum())
    negative = len(y) - positive
    weight = negative / positive if positive > 0 and negative > 0 else 1.0
    loss_fn = torch.nn.BCEWithLogitsLoss(pos_weight=torch.tensor([weight]))
    optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)
    history = []
    model.train()
    for _ in range(epochs):
        total = 0.0
        for features, labels in loader:
            optimizer.zero_grad()
            loss = loss_fn(model(features), labels)
            if not torch.isfinite(loss):
                raise ValueError("Training produced a non-finite loss")
            loss.backward()
            optimizer.step()
            total += loss.item() * len(labels)
        history.append(total / len(y))
    return history


def scores(model, X, *, batch_size=4096):
    """Return probabilities without loading all evaluation rows into one tensor."""
    X = np.asarray(X, dtype=np.float32)
    if X.ndim != 2 or len(X) == 0 or not np.isfinite(X).all() or batch_size < 1:
        raise ValueError("Expected nonempty finite features and a positive batch size")
    model.eval()
    with torch.no_grad():
        return np.concatenate([
            torch.sigmoid(model(torch.from_numpy(X[start:start + batch_size]))).numpy()
            for start in range(0, len(X), batch_size)
        ])
