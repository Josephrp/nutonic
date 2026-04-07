import numpy as np
import pytest
import torch

from terramind_ad.tiling import TiledPredictor


class TestTiledPredictor:
    """Test tiled prediction interface and core functionality."""

    def test_initialization_validation(self):
        """test parameter validation"""
        # valid initialization
        predictor = TiledPredictor(tile_size=224, overlap=32, batch_size=4, downsample_factor=16)
        assert predictor.tile_size == 224

        # invalid overlap
        with pytest.raises(ValueError, match="overlap must be less than tile_size"):
            TiledPredictor(tile_size=224, overlap=224, downsample_factor=16)

        # invalid divisibility
        with pytest.raises(ValueError, match="tile_size must be divisible by downsample_factor"):
            TiledPredictor(tile_size=225, overlap=32, downsample_factor=16)
        with pytest.raises(ValueError, match="overlap must be divisible by downsample_factor"):
            TiledPredictor(tile_size=224, overlap=33, downsample_factor=16)

    def test_identity_inference(self):
        """test tiled inference with identity function"""
        predictor = TiledPredictor(tile_size=112, overlap=0, batch_size=2, downsample_factor=1, device="cpu")
        input_arr = torch.rand(3, 224, 224)

        def identity_fn(batch: dict[str, torch.Tensor]) -> torch.Tensor:
            return batch["default"]

        result = predictor(input_arr, identity_fn)
        assert result.shape == input_arr.shape
        assert torch.allclose(result, input_arr, atol=1e-5)

    def test_downsampling(self):
        """test inference with downsampling"""
        predictor = TiledPredictor(tile_size=224, overlap=32, batch_size=2, downsample_factor=16, device="cpu")
        input_arr = torch.rand(12, 448, 448)

        def downsample_fn(batch: dict[str, torch.Tensor]) -> torch.Tensor:
            b = batch["default"]
            # simulate ViT encoder: 16x downsample, 768-dim output
            bs, c, h, w = b.shape
            return torch.rand(bs, 768, h // 16, w // 16)

        result = predictor(input_arr, downsample_fn)
        assert result.shape == (768, 448 // 16, 448 // 16)

    def test_overlapping_windows(self):
        """test that overlap produces smooth blending"""
        predictor = TiledPredictor(tile_size=112, overlap=16, batch_size=2, downsample_factor=1, device="cpu")
        # constant input
        input_arr = torch.ones(1, 224, 224) * 5.0

        def identity_fn(batch: dict[str, torch.Tensor]) -> torch.Tensor:
            return batch["default"]

        result = predictor(input_arr, identity_fn)
        # center should be close to constant value
        center = result[:, 32:-32, 32:-32]
        assert torch.allclose(center, torch.ones_like(center) * 5.0, atol=0.1)

    def test_edge_cases(self):
        """test edge cases: small input, non-square, different channels"""
        predictor = TiledPredictor(tile_size=224, overlap=32, batch_size=1, downsample_factor=1, device="cpu")

        def identity_fn(batch: dict[str, torch.Tensor]) -> torch.Tensor:
            return batch["default"]

        # input smaller than tile
        small = torch.rand(3, 100, 100)
        result = predictor(small, identity_fn)
        assert result.shape == small.shape

        # non-square
        rect = torch.rand(3, 200, 400)
        result = predictor(rect, identity_fn)
        assert result.shape == rect.shape

        # many channels
        many = torch.rand(128, 224, 224)
        result = predictor(many, identity_fn)
        assert result.shape == many.shape

    def test_numpy_input(self):
        """test numpy array input"""
        predictor = TiledPredictor(tile_size=112, overlap=16, batch_size=2, downsample_factor=1, device="cpu")
        input_arr = np.random.rand(3, 224, 224).astype(np.float32)

        def identity_fn(batch: dict[str, torch.Tensor]) -> torch.Tensor:
            return batch["default"]

        result = predictor(input_arr, identity_fn)
        assert isinstance(result, torch.Tensor)
        assert result.shape == input_arr.shape

    def test_multimodal_input(self):
        """test dict input for multi-modal inference"""
        from terramind_ad.tiling.core import tiled_inference

        inputs = {"S2L2A": torch.rand(12, 224, 224), "S1GRD": torch.rand(2, 224, 224)}

        def fusion_fn(batch: dict[str, torch.Tensor]) -> torch.Tensor:
            # simple fusion: return same spatial size as input
            s2 = batch["S2L2A"]
            bs, _, h, w = s2.shape
            return torch.rand(bs, 64, h, w)

        result = tiled_inference(
            inputs,  # type: ignore
            tile_size=112,
            overlap=16,
            predict_fn=fusion_fn,
            batch_size=2,
            downsample_factor=1,
            device="cpu",
        )
        assert result.shape == (64, 224, 224)
