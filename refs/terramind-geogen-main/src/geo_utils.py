# Source: https://github.com/LukasHaas/PIGEON/blob/main/preprocessing/geo_utils.py#L23

import torch
from torch import Tensor


# Constant
rad_torch = torch.tensor(6378137.0, dtype=torch.float64)


def haversine(x: Tensor, y: Tensor) -> Tensor:
    """Computes the haversine distance between two sets of points

    Args:
        x (Tensor): points 1 (lon, lat)
        y (Tensor): points 2 (lon, lat)

    Returns:
        Tensor: haversine distance in km
    """
    x_rad, y_rad = torch.deg2rad(x), torch.deg2rad(y)
    delta = y_rad - x_rad
    a = torch.sin(delta[:, 1] / 2)**2 + torch.cos(x_rad[:, 1]) * torch.cos(y_rad[:, 1]) * torch.sin(delta[:, 0] / 2)**2
    c = 2 * torch.arcsin(torch.sqrt(a))
    distance_km = (rad_torch * c) / 1000
    return distance_km
