import numpy as np
import pytest
import rasterio as rio
import torch


@pytest.fixture
def mock_site_data(tmp_path):
    """Create mock site data for testing."""
    # create site directory structure
    site_id = "test_site"
    site_dir = tmp_path / site_id / "s2"
    site_dir.mkdir(parents=True)

    # create a mock S2 composite
    # 12 bands, 448x448
    data = np.random.rand(12, 448, 448).astype(np.float32)

    # save as GeoTIFF
    tif_path = site_dir / "2023-01-15.tif"
    with rio.open(
        tif_path,
        "w",
        driver="GTiff",
        height=448,
        width=448,
        count=12,
        dtype=rio.float32,
        crs="EPSG:4326",
        transform=rio.transform.from_bounds(0, 0, 1, 1, 448, 448),
    ) as dst:
        dst.write(data)

    return tmp_path, site_id, tif_path


def test_tiled_predictor_with_mock_terramind(mock_site_data):
    """test tiled predictor works with mock TerraMind-like model"""
    from terramind_ad.io import read_raster

    from terramind_ad.tiling import TiledPredictor

    tmp_path, site_id, tif_path = mock_site_data

    # create mock TerraMind encoder
    class MockTerraMindEncoder:
        def __call__(self, inputs: dict[str, torch.Tensor]) -> list[torch.Tensor]:
            modality_key = list(inputs.keys())[0]
            batch = inputs[modality_key]
            b, c, h, w = batch.shape

            # simulate encoder: downsample by 16, output 768-dim embeddings
            h_out, w_out = h // 16, w // 16
            embed_dim = 768

            features = torch.rand(b, embed_dim, h_out, w_out, device=batch.device)
            return [features]

    model = MockTerraMindEncoder()

    # load image
    img = read_raster(tif_path)  # (12, 448, 448)
    img_tensor = torch.from_numpy(img).float()

    # create predictor
    predictor = TiledPredictor(tile_size=224, overlap=32, batch_size=4, downsample_factor=16, device="cpu")

    # define prediction function
    def predict_fn(batch: dict[str, torch.Tensor]) -> torch.Tensor:
        outputs = model(batch)
        return outputs[-1]

    # run inference
    with torch.no_grad():
        embeddings = predictor(img_tensor, predict_fn)

    # verify output
    assert embeddings.shape == (768, 448 // 16, 448 // 16)
    assert not torch.isnan(embeddings).any()


def test_tiled_predictor_handles_different_sizes(mock_site_data):
    """test tiled predictor handles various image sizes"""
    from terramind_ad.tiling import TiledPredictor

    class SimpleModel:
        def __call__(self, inputs: dict[str, torch.Tensor]) -> list[torch.Tensor]:
            batch = list(inputs.values())[0]
            b, c, h, w = batch.shape
            # simple downsampling
            features = torch.rand(b, 64, h // 16, w // 16)
            return [features]

    model = SimpleModel()
    predictor = TiledPredictor(tile_size=224, overlap=32, batch_size=4, downsample_factor=16, device="cpu")

    def predict_fn(batch: dict[str, torch.Tensor]) -> torch.Tensor:
        return model(batch)[-1]

    # test different sizes
    for h, w in [(224, 224), (448, 448), (512, 512), (300, 400)]:
        img = torch.rand(3, h, w)
        with torch.no_grad():
            result = predictor(img, predict_fn)
        expected_shape = (64, h // 16, w // 16)
        assert result.shape == expected_shape, f"Failed for size {h}x{w}"


def test_predictor_memory_efficiency():
    """test that tiled predictor is memory efficient"""
    from terramind_ad.tiling import TiledPredictor

    # create a predictor for large images
    predictor = TiledPredictor(tile_size=224, overlap=32, batch_size=8, downsample_factor=16, device="cpu")

    # simulate a very large image
    large_image = torch.rand(12, 1024, 1024)

    def simple_encoder(batch: dict[str, torch.Tensor]) -> torch.Tensor:
        b = batch["default"]
        bs, c, h, w = b.shape
        return torch.rand(bs, 768, h // 16, w // 16)

    # should complete without memory error
    with torch.no_grad():
        result = predictor(large_image, simple_encoder)

    assert result.shape == (768, 1024 // 16, 1024 // 16)


def test_multimodal_tiling():
    """test multi-modal tiling with S2 + S1 fusion using clean dict API"""
    from terramind_ad.tiling import TiledPredictor

    # simulate S2 and S1 data
    s2_image = torch.rand(12, 448, 448)
    s1_image = torch.rand(2, 448, 448)

    modality_arrays = {"S2L2A": s2_image, "S1GRD": s1_image}

    # mock model that accepts dict and returns fused embeddings
    class MockFusionModel:
        def __call__(self, inputs: dict[str, torch.Tensor]) -> list[torch.Tensor]:
            s2_batch = inputs["S2L2A"]
            b, _, h, w = s2_batch.shape

            # simulate fusion: concatenate channels then downsample
            h_out, w_out = h // 16, w // 16
            fused = torch.rand(b, 768, h_out, w_out)
            return [fused]

    model = MockFusionModel()

    # create tiled predictor
    predictor = TiledPredictor(tile_size=224, overlap=32, batch_size=4, downsample_factor=16, device="cpu")

    # define prediction function that accepts dict
    def predict_fn(batch: dict[str, torch.Tensor]) -> torch.Tensor:
        outputs = model(batch)
        return outputs[-1]

    # run tiled inference with dict input
    with torch.no_grad():
        embeddings = predictor(modality_arrays, predict_fn)

    # verify output shape
    assert embeddings.shape == (768, 448 // 16, 448 // 16)
    assert not torch.isnan(embeddings).any()
