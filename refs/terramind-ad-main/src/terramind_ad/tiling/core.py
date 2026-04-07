from dataclasses import dataclass
from typing import Callable, cast

import numpy as np
import torch
from numpy.typing import NDArray

_WINDOW_CACHE: dict[tuple[int, int], torch.Tensor] = {}


@dataclass
class TilingParams:
    """Parameters for tiled processing."""

    n_tiles_h: int
    n_tiles_w: int
    pad_top: int
    pad_bottom: int
    pad_left: int
    pad_right: int
    required_h: int
    required_w: int

    @property
    def pad_h(self) -> int:
        """Total vertical padding."""
        return self.pad_top + self.pad_bottom

    @property
    def pad_w(self) -> int:
        """Total horizontal padding."""
        return self.pad_left + self.pad_right


def cosine_window_2d(tile_size: int, overlap: int, device: str = "cpu") -> torch.Tensor:
    """Generate 2D cosine window for smooth tile blending."""
    cache_key = (tile_size, overlap)
    if cache_key in _WINDOW_CACHE:
        return _WINDOW_CACHE[cache_key].to(device)

    if overlap == 0:
        window = torch.ones(tile_size, tile_size, device=device)
    else:
        window_1d = np.ones(tile_size)
        left = np.cos(np.linspace(np.pi, 0, overlap)) * 0.5 + 0.5
        window_1d[:overlap] = left
        right = np.cos(np.linspace(0, np.pi, overlap)) * 0.5 + 0.5
        window_1d[-overlap:] = right
        window_1d_t = torch.from_numpy(window_1d).float()
        window = torch.outer(window_1d_t, window_1d_t).to(device)

    _WINDOW_CACHE[cache_key] = window.cpu()
    return window


def compute_tiles_params(input_shape: tuple[int, int], tile_size: int, overlap: int) -> TilingParams:
    """Compute tiling parameters for a given input shape.

    Args:
        input_shape: (height, width) of input
        tile_size: size of each tile
        overlap: overlap between adjacent tiles in pixels

    Returns:
        TilingParams with number of tiles and padding information
    """
    h, w = input_shape
    step = tile_size - overlap

    if overlap >= tile_size:
        raise ValueError("overlap must be less than tile_size")

    n_tiles_h = max(1, int(np.ceil((h - overlap) / step)) + 1)
    n_tiles_w = max(1, int(np.ceil((w - overlap) / step)) + 1)

    required_h = n_tiles_h * step + overlap
    required_w = n_tiles_w * step + overlap

    # center-based padding: distribute equally on both sides
    total_pad_h = required_h - h
    total_pad_w = required_w - w

    pad_top = total_pad_h // 2
    pad_bottom = total_pad_h - pad_top
    pad_left = total_pad_w // 2
    pad_right = total_pad_w - pad_left

    return TilingParams(
        n_tiles_h=n_tiles_h,
        n_tiles_w=n_tiles_w,
        pad_top=pad_top,
        pad_bottom=pad_bottom,
        pad_left=pad_left,
        pad_right=pad_right,
        required_h=required_h,
        required_w=required_w,
    )


def pad_array(
    array: NDArray | torch.Tensor, pad_top: int, pad_bottom: int, pad_left: int, pad_right: int
) -> NDArray | torch.Tensor:
    """Pad array with center-based padding."""
    if pad_top == 0 and pad_bottom == 0 and pad_left == 0 and pad_right == 0:
        return array

    if isinstance(array, torch.Tensor):
        h, w = array.shape[-2:]
        mode = "replicate" if (pad_top + pad_bottom > h or pad_left + pad_right > w) else "reflect"
        return torch.nn.functional.pad(array, (pad_left, pad_right, pad_top, pad_bottom), mode=mode)
    else:
        pad_width = [(0, 0)] * (array.ndim - 2) + [(pad_top, pad_bottom), (pad_left, pad_right)]
        h, w = array.shape[-2:]
        mode = "edge" if (pad_top + pad_bottom > h or pad_left + pad_right > w) else "reflect"
        return np.pad(array, pad_width, mode=mode)


def unpad_array(
    array: NDArray | torch.Tensor, pad_top: int, pad_bottom: int, pad_left: int, pad_right: int
) -> NDArray | torch.Tensor:
    """Remove center-based padding from array."""
    if pad_top == 0 and pad_bottom == 0 and pad_left == 0 and pad_right == 0:
        return array

    h_start = pad_top
    h_end = -pad_bottom if pad_bottom > 0 else None
    w_start = pad_left
    w_end = -pad_right if pad_right > 0 else None

    return array[..., h_start:h_end, w_start:w_end]


def extract_tile(
    array: NDArray | torch.Tensor, row: int, col: int, tile_size: int, overlap: int
) -> NDArray | torch.Tensor:
    """Extract a single tile from array."""
    step = tile_size - overlap
    y = row * step
    x = col * step
    return array[..., y : y + tile_size, x : x + tile_size]


def place_tile(
    canvas: torch.Tensor,
    tile: torch.Tensor,
    row: int,
    col: int,
    overlap: int,
    window: torch.Tensor,
    downsample_factor: int = 1,
) -> None:
    """Place a tile on the canvas with windowing (in-place operation).

    Args:
        canvas: output canvas
        tile: tile to place
        row: tile row index
        col: tile column index
        overlap: overlap in input space
        window: cosine window for blending
        downsample_factor: downsample factor
        n_tiles_h: total number of tiles in height (for edge detection)
        n_tiles_w: total number of tiles in width (for edge detection)
    """
    tile_size_out = tile.shape[-1]
    step = (tile_size_out * downsample_factor) - overlap
    y_out = (row * step) // downsample_factor
    x_out = (col * step) // downsample_factor

    window_adjusted = window.clone()
    window_broadcast = window_adjusted.unsqueeze(0) if tile.ndim == 3 else window_adjusted
    weighted_tile = tile * window_broadcast
    canvas[..., y_out : y_out + tile_size_out, x_out : x_out + tile_size_out] += weighted_tile


def tiled_inference(
    input_array: NDArray | torch.Tensor | dict[str, NDArray | torch.Tensor],
    tile_size: int,
    overlap: int,
    predict_fn: Callable[[dict[str, torch.Tensor]], torch.Tensor],
    batch_size: int = 1,
    downsample_factor: int = 1,
    device: str = "cuda",
) -> torch.Tensor:
    """Perform tiled inference with smooth windowing.

    Args:
        input_array: (C, H, W) or dict of inputs with same spatial shape
        tile_size: size of input tiles
        overlap: overlap between adjacent tiles in pixels
        predict_fn: takes dict[str, Tensor] (B, C, H, W), returns (B, C', H', W')
        batch_size: number of tiles to process at once
        downsample_factor: factor by which output is downsampled (e.g., 16 for ViT)
        device: device for computation

    Returns:
        prediction tensor (C', H_out, W_out)
    """
    # normalize input to dict of torch tensors
    if not isinstance(input_array, dict):
        input_array = {"default": input_array}

    input_tensors: dict[str, torch.Tensor] = {}
    for key, arr in input_array.items():
        tensor = torch.from_numpy(arr).float() if isinstance(arr, np.ndarray) else arr.float()
        input_tensors[key] = tensor.to(device)

    # validate spatial shapes match
    shapes = [t.shape[-2:] for t in input_tensors.values()]
    if not all(s == shapes[0] for s in shapes):
        raise ValueError(f"All modalities must have same spatial shape, got {shapes}")

    h_in, w_in = next(iter(input_tensors.values())).shape[-2:]
    modality_keys = list(input_tensors.keys())

    # compute tiling parameters
    params = compute_tiles_params((h_in, w_in), tile_size, overlap)
    padded_inputs = {
        k: pad_array(v, params.pad_top, params.pad_bottom, params.pad_left, params.pad_right)
        for k, v in input_tensors.items()
    }

    # compute output dimensions
    tile_size_out = tile_size // downsample_factor
    overlap_out = overlap // downsample_factor
    step_out = (tile_size - overlap) // downsample_factor
    h_out = params.n_tiles_h * step_out + overlap_out
    w_out = params.n_tiles_w * step_out + overlap_out

    canvas = None
    window = cosine_window_2d(tile_size_out, overlap_out, device)
    norm_canvas = torch.zeros(h_out, w_out, device=device)

    # helper to process a batch
    def process_batch(tiles: dict[str, list[torch.Tensor]], coords: list[tuple[int, int]]) -> None:
        nonlocal canvas
        batch_dict = {k: torch.stack(tiles[k], dim=0) for k in modality_keys}
        pred_batch = predict_fn(batch_dict)

        if canvas is None:
            c_out = pred_batch.shape[1]
            canvas = torch.zeros(c_out, h_out, w_out, device=device)

        for pred, (r, c) in zip(pred_batch, coords):
            place_tile(canvas, pred, r, c, overlap, window, downsample_factor)  # type: ignore
            place_tile(
                norm_canvas.unsqueeze(0),
                window.unsqueeze(0),
                r,
                c,
                overlap,
                torch.ones_like(window),
                downsample_factor,
            )

    # process tiles in batches
    tiles_batch: dict[str, list[torch.Tensor]] = {k: [] for k in modality_keys}
    coords_batch: list[tuple[int, int]] = []

    for row in range(params.n_tiles_h):
        for col in range(params.n_tiles_w):
            for k in modality_keys:
                tile = extract_tile(padded_inputs[k], row, col, tile_size, overlap)
                tile = torch.from_numpy(tile) if isinstance(tile, np.ndarray) else tile
                tiles_batch[k].append(tile)
            coords_batch.append((row, col))

            if len(coords_batch) == batch_size:
                process_batch(tiles_batch, coords_batch)
                for k in modality_keys:
                    tiles_batch[k].clear()
                coords_batch.clear()

    # process remaining tiles
    if coords_batch:
        process_batch(tiles_batch, coords_batch)

    assert canvas is not None
    canvas = canvas / norm_canvas.unsqueeze(0).clamp(min=1e-8)

    # remove padding and ensure exact output size
    pad_top_out = params.pad_top // downsample_factor
    pad_bottom_out = params.pad_bottom // downsample_factor
    pad_left_out = params.pad_left // downsample_factor
    pad_right_out = params.pad_right // downsample_factor
    canvas = unpad_array(canvas, pad_top_out, pad_bottom_out, pad_left_out, pad_right_out)

    h_target = h_in // downsample_factor
    w_target = w_in // downsample_factor
    canvas = canvas[..., :h_target, :w_target]
    return cast(torch.Tensor, canvas)


class TiledPredictor:
    """Tiled inference with overlapping windows and smooth blending.

    Example:
        >>> predictor = TiledPredictor(tile_size=224, overlap=32, batch_size=8, downsample_factor=16)
        >>> result = predictor(image, model.forward)
    """

    def __init__(
        self,
        tile_size: int,
        overlap: int,
        batch_size: int = 1,
        downsample_factor: int = 1,
        device: str = "cuda",
    ) -> None:
        if overlap >= tile_size:
            raise ValueError("overlap must be less than tile_size")
        if tile_size % downsample_factor != 0:
            raise ValueError("tile_size must be divisible by downsample_factor")
        if overlap % downsample_factor != 0:
            raise ValueError("overlap must be divisible by downsample_factor")

        self.tile_size = tile_size
        self.overlap = overlap
        self.batch_size = batch_size
        self.downsample_factor = downsample_factor
        self.device = device

    def __call__(
        self,
        input_array: NDArray | torch.Tensor | dict[str, NDArray | torch.Tensor],
        predict_fn: Callable[[dict[str, torch.Tensor]], torch.Tensor],
    ) -> torch.Tensor:
        """Run tiled inference.

        Args:
            input_array: (C, H, W) or dict of arrays with matching spatial dims
            predict_fn: takes dict[str, Tensor] (B, C, H, W), returns (B, C', H', W')

        Returns:
            prediction (C', H//downsample, W//downsample)
        """
        return tiled_inference(
            input_array=input_array,
            tile_size=self.tile_size,
            overlap=self.overlap,
            predict_fn=predict_fn,
            batch_size=self.batch_size,
            downsample_factor=self.downsample_factor,
            device=self.device,
        )

    def __repr__(self) -> str:
        return (
            f"TiledPredictor(tile_size={self.tile_size}, overlap={self.overlap}, "
            f"batch_size={self.batch_size}, downsample_factor={self.downsample_factor}, device={self.device})"
        )
