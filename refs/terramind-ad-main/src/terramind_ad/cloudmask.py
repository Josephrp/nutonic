import logging

import numpy as np
import torch
from omnicloudmask import predict_from_array
from scipy import ndimage

log = logging.getLogger(__name__)


def generate_cloud_mask(
    rgb_nir: np.ndarray,
    patch_size: int = 512,
    patch_overlap: int = 256,
    batch_size: int = 1,
    device: str = "cuda",
    inference_dtype: str = "bf16",
) -> np.ndarray:
    """Generate cloud mask from Red, Green, NIR bands using OmniCloudMask.

    Args:
        rgb_nir: array with shape (3, H, W) containing [Red, Green, NIR] bands
        patch_size: size of patches for inference
        patch_overlap: overlap between patches
        batch_size: number of patches to process in a batch
        device: device for inference ('cuda', 'cpu', or 'mps')
        inference_dtype: data type for inference ('bf16' or 'fp32')

    Returns:
        cloud mask with shape (H, W) with values:
            0 = Clear
            1 = Thick Cloud
            2 = Thin Cloud
            3 = Cloud Shadow
    """
    if rgb_nir.shape[0] != 3:
        raise ValueError(f"Expected 3 bands [Red, Green, NIR], got {rgb_nir.shape[0]}")

    # convert inference_dtype string to torch dtype
    dtype_map = {"bf16": torch.bfloat16, "fp32": torch.float32, "fp16": torch.float16}
    torch_dtype = dtype_map.get(inference_dtype, torch.float32)

    log.debug("Running OmniCloudMask with patch_size=%d, batch_size=%d, device=%s", patch_size, batch_size, device)

    mask = predict_from_array(
        input_array=rgb_nir,
        patch_size=patch_size,
        patch_overlap=patch_overlap,
        batch_size=batch_size,
        inference_device=device,
        mosaic_device=device,
        inference_dtype=torch_dtype,
        export_confidence=False,
        apply_no_data_mask=True,
        no_data_value=0,
    )

    # squeeze out any extra dimensions (OmniCloudMask may return (1, H, W) or (H, W, 1))
    mask = np.squeeze(mask)

    # ensure output is 2D
    if mask.ndim != 2:
        raise ValueError(f"Expected 2D cloud mask after squeeze, got shape {mask.shape}")

    return mask.astype(np.uint8)


def dilate_cloud_mask(mask: np.ndarray, dilation_size: int = 8) -> np.ndarray:
    """Dilate cloud mask using binary dilation.

    Args:
        mask: binary or multi-class cloud mask (H, W)
        dilation_size: size of dilation structuring element

    Returns:
        dilated mask with same shape as input
    """
    # create circular structuring element
    y, x = np.ogrid[-dilation_size : dilation_size + 1, -dilation_size : dilation_size + 1]
    structure = x**2 + y**2 <= dilation_size**2
    # dilate (any non-zero value is considered cloud)
    binary_mask = mask > 0
    dilated = ndimage.binary_dilation(binary_mask, structure=structure)
    return dilated.astype(np.uint8)


def downsample_mask(mask: np.ndarray, downsample_factor: int) -> np.ndarray:
    """Downsample mask using nearest neighbor interpolation.

    Args:
        mask: input mask (H, W)
        downsample_factor: factor to downsample by

    Returns:
        downsampled mask (H//factor, W//factor)
    """
    H, W = mask.shape
    H_new = H // downsample_factor
    W_new = W // downsample_factor
    # nearest neighbor downsampling via indexing
    downsampled = mask[::downsample_factor, ::downsample_factor]
    # ensure output size is correct
    if downsampled.shape != (H_new, W_new):
        downsampled = downsampled[:H_new, :W_new]
    return downsampled


def prepare_feature_cloud_mask(
    cloud_masks: np.ndarray,
    dilation_size: int = 8,
    downsample_factor: int = 16,
) -> np.ndarray:
    """Prepare cloud masks for feature-level masking.

    Applies morphological dilation and downsampling to match feature resolution.

    Args:
        cloud_masks: array with shape (T, H, W)
        dilation_size: size of dilation structuring element
        downsample_factor: factor to downsample by (typically 16 for TerraMind patch size)

    Returns:
        processed masks with shape (T, H//factor, W//factor)
    """
    T, H, W = cloud_masks.shape
    H_feat = H // downsample_factor
    W_feat = W // downsample_factor
    processed = np.zeros((T, H_feat, W_feat), dtype=np.uint8)
    for t in range(T):
        # dilate
        dilated = dilate_cloud_mask(cloud_masks[t], dilation_size=dilation_size)
        # downsample
        processed[t] = downsample_mask(dilated, downsample_factor=downsample_factor)
    log.info(
        "Processed cloud masks: %s -> %s (dilation=%d, downsample=%d)",
        cloud_masks.shape,
        processed.shape,
        dilation_size,
        downsample_factor,
    )
    return processed
