import time

import numpy as np
import torch
from torch import nn

from app.protocol import Weights


class FraudModel(nn.Sequential):
    def __init__(self):
        super().__init__(nn.Linear(29, 16), nn.ReLU(), nn.Linear(16, 1))


def initial_weights(seed: int) -> Weights:
    torch.manual_seed(seed)
    return get_weights(FraudModel())


def get_weights(model: nn.Module) -> Weights:
    return [p.detach().cpu().numpy().copy() for p in model.state_dict().values()]


def load_model(weights: Weights) -> FraudModel:
    model = FraudModel()
    names = model.state_dict().keys()
    model.load_state_dict(
        {k: torch.from_numpy(v.copy()) for k, v in zip(names, weights, strict=True)}
    )
    return model


def train(weights, x, y, *, epochs, batch_size, learning_rate, pos_weight, seed, expires, mu=0.0):
    model = load_model(weights)
    model.train()
    global_params = [p.detach().clone() for p in model.parameters()]
    optimizer = torch.optim.SGD(model.parameters(), lr=learning_rate)
    loss_fn = nn.BCEWithLogitsLoss(pos_weight=torch.tensor([pos_weight], dtype=torch.float32))
    features = torch.from_numpy(x)
    targets = torch.from_numpy(y.astype(np.float32)).reshape(-1, 1)
    generator = torch.Generator().manual_seed(seed)
    last_loss = 0.0
    for _ in range(epochs):
        permutation = torch.randperm(len(x), generator=generator)
        for indices in permutation.split(batch_size):
            if time.monotonic() >= expires:
                raise TimeoutError("local training exceeded its work budget")
            optimizer.zero_grad(set_to_none=True)
            loss = loss_fn(model(features[indices]), targets[indices])
            if not torch.isfinite(loss):
                raise ValueError("training produced non-finite loss")
            objective = loss
            if mu > 0:
                # FedProx: keep local weights near the global model (Li et al., 2020).
                drift = sum(
                    ((p - g) ** 2).sum()
                    for p, g in zip(model.parameters(), global_params, strict=True)
                )
                objective = loss + mu / 2 * drift
            objective.backward()
            optimizer.step()
            last_loss = float(loss.detach())
    return get_weights(model), last_loss


def predict(weights: Weights, x: np.ndarray) -> np.ndarray:
    model = load_model(weights)
    model.eval()
    with torch.no_grad():
        return torch.sigmoid(model(torch.from_numpy(x))).numpy().reshape(-1)
