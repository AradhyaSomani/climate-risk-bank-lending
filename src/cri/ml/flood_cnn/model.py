"""A plain U-Net in PyTorch, written from scratch for this project (Phase 2B-B).

Inputs are the channels chosen in configs/ml/flood_cnn.yaml (VV, VH, optionally DEM and
slope); the output is two-class logits (dry, water) per pixel. The loss is class-weighted
cross-entropy plus a soft Dice term on the water class, both ignoring no-data pixels (-1).
"""

from __future__ import annotations

import torch
import torch.nn.functional as F
from torch import nn


def _block(cin: int, cout: int) -> nn.Sequential:
    return nn.Sequential(
        nn.Conv2d(cin, cout, 3, padding=1, bias=False), nn.BatchNorm2d(cout), nn.ReLU(True),
        nn.Conv2d(cout, cout, 3, padding=1, bias=False), nn.BatchNorm2d(cout), nn.ReLU(True),
    )


class UNet(nn.Module):
    def __init__(self, in_channels: int = 2, n_classes: int = 2, base: int = 32,
                 depth: int = 4):
        super().__init__()
        widths = [base * 2**i for i in range(depth + 1)]
        self.down = nn.ModuleList([_block(in_channels, widths[0])])
        self.down.extend(_block(widths[i], widths[i + 1]) for i in range(depth))
        self.up = nn.ModuleList(
            nn.ConvTranspose2d(widths[i + 1], widths[i], 2, stride=2)
            for i in reversed(range(depth)))
        self.dec = nn.ModuleList(_block(widths[i] * 2, widths[i]) for i in reversed(range(depth)))
        self.head = nn.Conv2d(widths[0], n_classes, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        skips = []
        for i, block in enumerate(self.down):
            x = block(x if i == 0 else F.max_pool2d(x, 2))
            skips.append(x)
        x = skips.pop()
        for up, dec in zip(self.up, self.dec, strict=True):
            x = dec(torch.cat([up(x), skips.pop()], dim=1))
        return self.head(x)


def dice_ce_loss(logits: torch.Tensor, target: torch.Tensor, class_weights: torch.Tensor,
                 dice_weight: float = 0.5, eps: float = 1.0) -> torch.Tensor:
    """target: (n, h, w) long with -1 for no data."""
    ce = F.cross_entropy(logits, target, weight=class_weights, ignore_index=-1)
    valid = target >= 0
    p = torch.softmax(logits, dim=1)[:, 1][valid]
    t = (target[valid] == 1).float()
    dice = 1 - (2 * (p * t).sum() + eps) / (p.sum() + t.sum() + eps)
    return dice_weight * dice + (1 - dice_weight) * ce


def augment(x: torch.Tensor, y: torch.Tensor, gen: torch.Generator
            ) -> tuple[torch.Tensor, torch.Tensor]:
    """Random flips and 90-degree rotations, the same for the whole batch."""
    k = int(torch.randint(0, 4, (1,), generator=gen))
    x, y = torch.rot90(x, k, (2, 3)), torch.rot90(y, k, (1, 2))
    if torch.rand(1, generator=gen) < 0.5:
        x, y = x.flip(3), y.flip(2)
    return x, y
