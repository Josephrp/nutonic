import albumentations as A
from albumentations.pytorch import ToTensorV2
import pandas as pd
import torch
import torch.nn.functional as F
from torch.utils.data import DataLoader
from torchmetrics.image import StructuralSimilarityIndexMeasure, PeakSignalNoiseRatio
from torchmetrics import JaccardIndex
import yaml

from terratorch import FULL_MODEL_REGISTRY
from src.terramesh import build_terramesh_dataset, Transpose, MultimodalTransforms
from src.geo_utils import haversine


# Configuration Variables
IN_MODALITY = 'S2L2A'
OUT_MODALITIES = ['S1GRD', 'S1RTC', 'LULC', 'DEM', 'NDVI', 'Coordinates']
MODEL_VERSION = "terramind_v1_base_generate"
LOCAL_TERRAMESH_PATH = "/dss/dsstbyfs02/pn49cu/pn49cu-dss-0020/terramesh_val/data/TerraMesh/"
DEVICE = 'cuda' if torch.cuda.is_available() else 'mps' if torch.backends.mps.is_available() else 'cpu'


def prepare_dataloader():
    """Prepares the DataLoader by defining transformations and loading the dataset."""

    modalities_to_load = [IN_MODALITY] + [m for m in OUT_MODALITIES if m != "Coordinates"]
    
    # Define image transformations
    val_transform = MultimodalTransforms(
        transforms=A.Compose([
            Transpose([1, 2, 0]),
            A.CenterCrop(224, 224),
            ToTensorV2(),
        ],
        is_check_shapes=False,
        additional_targets={m: "image" for m in modalities_to_load},
    ),
    non_image_modalities=["__key__", "__url__", "center_lon", "center_lat", "cloud_mask"] + \
        ["time_" + m for m in modalities_to_load]
    )
    
    # Build the dataset
    dataset = build_terramesh_dataset(
        path=LOCAL_TERRAMESH_PATH,
        modalities=modalities_to_load,
        split="val",
        shuffle=False,
        seed=42,
        transform=val_transform,
        batch_size=1,
        return_metadata=True,
    )
    
    return DataLoader(dataset, batch_size=None, num_workers=1)


def load_models():
    """Loads one Terramind model per output modality."""

    models = {}
    for out_modality in OUT_MODALITIES:
        model = FULL_MODEL_REGISTRY.build(
            MODEL_VERSION,
            modalities=[IN_MODALITY],
            output_modalities=[out_modality],
            pretrained=True,
            standardize=True
        ).to(DEVICE)
        models[out_modality] = model
    return models


def regression_metrics(pred, gt):
    mse = F.mse_loss(pred, gt).item()
    mae = F.l1_loss(pred, gt).item()
    rmse = torch.sqrt(torch.tensor(mse)).item()
    return {"MSE": mse, "MAE": mae, "RMSE": rmse}


def coordinates_metrics(pred, gt):
    metrics = regression_metrics(pred, gt)
    haversine_distance = haversine(pred, gt)
    metrics["Haversine_distance_km"] = haversine_distance.item()

    return metrics


def image_metrics(pred, gt, value_range):
    metrics = regression_metrics(pred, gt)
    ssim_metric = StructuralSimilarityIndexMeasure(data_range=value_range).to(DEVICE)
    metrics["SSIM"] = ssim_metric(pred, gt).item()

    psnr_metric = PeakSignalNoiseRatio(data_range=value_range).to(DEVICE)
    metrics["PSNR"] = psnr_metric(pred, gt).item()

    return metrics


def lulc_metrics(pred, gt):
    pred = pred.argmax(dim=1)
    gt = gt.squeeze(0).long()
    miou_metric = JaccardIndex(task="multiclass", num_classes=10).to(DEVICE)
    miou = miou_metric(pred, gt).item()
    return {"mIoU": miou}


@torch.no_grad()
def process_batch(batch, models, stats):
    row = {
        "Sample-Key": batch["__key__"][0],
        "Sample-URL": batch["__url__"][0],
        "Longitude": batch["center_lon"].item(),
        "Latitude": batch["center_lat"].item(),
        "Time-S2": batch["time_S2L2A"][0].item(),
    }

    input_tensor = batch[IN_MODALITY].float().to(DEVICE)

    # Extract coordinates and add to batch
    batch["Coordinates"] = torch.cat([batch["center_lon"],
                                      batch["center_lat"]], dim=0).unsqueeze(0)

    for modality in OUT_MODALITIES:
        # Skip either S1GRD or S1RTC that is missing for each sample
        if modality not in batch:
            continue
        
        if modality == "Coordinates":
            target = batch[modality].float().to(DEVICE)

            # Generate 10 predictions for averaging
            predictions = []
            for _ in range(10):
                pred = models[modality](input_tensor, timesteps=10)[modality]
                predictions.append(pred)

            # Collect valid predictions (not NaNs)
            valid_predictions = [torch.tensor(p[0], device=DEVICE) for p in predictions
                                 if isinstance(p[0][0], float)]

            if len(valid_predictions) > 0:
                # Use averaged prediction if we have at least one valid prediction
                final_prediction = torch.mean(torch.stack(valid_predictions), dim=0).unsqueeze(0)
            else:
                # Copy the NaN values from the last prediction if all 10 predictions resulted in NaNs
                final_prediction = torch.tensor(predictions[0], device=DEVICE)

            pred = torch.tensor(final_prediction).to(DEVICE)
            metrics = coordinates_metrics(pred, target)
            row.update({f"{k}_{modality}": v for k, v in metrics.items()})
            row.update({"Predicted-Longitude": pred[0, 0].item()})
            row.update({"Predicted-Latitude": pred[0, 1].item()})

        else:
            prediction = models[modality](input_tensor, timesteps=10)[modality]
            target = batch[modality].float().to(DEVICE)
            if modality == "LULC":
                row["mIoU_LULC"] = lulc_metrics(prediction, target)["mIoU"]

            else:
                vrange = (stats[modality]["min"], stats[modality]["max"])
                metrics = image_metrics(prediction, target, vrange)
                row.update({f"{k}_{modality}": v for k, v in metrics.items()})

    return row


def main():
    print(f"Using device: {DEVICE}")

    # Prepare DataLoader and models
    dataloader = prepare_dataloader()
    models = load_models()

    # Read the TerraMesh statistics yaml file for min/max values for SSIM/PSNR calculation
    with open("src/terramesh_statistics.yaml") as f:
        stats = yaml.safe_load(f)

    rows = []
    for i, batch in enumerate(dataloader):
        if IN_MODALITY in batch:
            rows.append(process_batch(batch, models, stats))
        else:
            # Using a S1 modality as input, there is no data for some samples
            continue

    df = pd.DataFrame(rows)
    output_path = f"generation_errors_{IN_MODALITY}_{MODEL_VERSION}_full_coords10averaged_haversine.csv"
    df.to_csv(output_path, index=False)
    print(f"Saved results to {output_path}")


if __name__ == "__main__":
    main()