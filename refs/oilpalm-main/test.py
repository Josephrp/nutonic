import rasterio
import os
import math
import random
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import Dataset

from PIL import Image
import albumentations as A
from albumentations.pytorch import ToTensorV2

import pytorch_lightning as pl
from torch.utils.data import DataLoader

import os
import random
from pathlib import Path
import numpy as np
import torch
from torch.utils.data import Dataset, DataLoader
from PIL import Image
import albumentations as A
from albumentations.pytorch import ToTensorV2
import pytorch_lightning as pl

import terratorch
from terratorch import BACKBONE_REGISTRY
from terratorch import FULL_MODEL_REGISTRY
from terratorch.models import EncoderDecoderFactory
from terratorch.datasets import HLSBands

#from utils.dataset import CustomDataset
#from utils.dataset import CustomDataModule
#from utils.model_multi import CustomModelTiM

from pytorch_lightning import Trainer, seed_everything
from pytorch_lightning.callbacks import Callback, EarlyStopping, ModelCheckpoint
from pytorch_lightning.loggers import TensorBoardLogger, CSVLogger

class CustomDataset(Dataset):
    def __init__(
        self,
        local_path: str,
        split: str = "train",
        transform: A.Compose | None = None,
        #mask_map: dict[int, int] | None = None,
        sample_ratio: float = 1.0,
        seed: int = 0,
    ):
        assert 0 < sample_ratio <= 1.0, "sample_ratio must be in (0,1]"

        super().__init__()
        self.local_path = Path(local_path)
        self.split = split
        self.transform = transform
        #self.mask_map = mask_map

        self.img_dir = self.local_path / f"{split}_s2"
        self.mask_dir = self.local_path / f"{split}_mask"

        images = sorted([f for f in os.listdir(self.img_dir) if f.endswith(".tif")])
        masks = sorted([f for f in os.listdir(self.mask_dir) if f.endswith(".tif")])

        assert len(images) == len(masks), "Image / mask count mismatch"

        # ---- percentage-based sampling ----
        n_total = len(images)
        n_use = math.ceil(n_total * sample_ratio)

        random.seed(seed)
        idx = list(range(n_total))
        random.shuffle(idx)
        idx = idx[:n_use]

        self.images = [images[i] for i in idx]
        self.masks = [masks[i] for i in idx]

    def __len__(self):
        return len(self.images)

    def __getitem__(self, idx):
        img_name = self.images[idx]
        mask_name = self.masks[idx]

        img_path = self.img_dir / img_name
        mask_path = self.mask_dir / mask_name

        # ---- Load image with rasterio ----
        with rasterio.open(img_path) as src:
            image = src.read([1, 2, 3]).astype(np.float32)  # (C,H,W)
            image = np.transpose(image, (1, 2, 0))          # (H,W,C)

        # ---- Load mask ----
        mask = np.array(Image.open(mask_path), dtype=np.uint8)

        # ---- Apply mask remapping ----
        #if self.mask_map:
        #    mask = self.apply_mask_mapping(mask)

        # ---- Albumentations (optional) ----
        if self.transform:
            data = self.transform(image=image, mask=mask)
            image = data["image"]          # tensor (C,H,W)
            mask = data["mask"].long()
        else:
            image = torch.from_numpy(image).permute(2, 0, 1)  # (C,H,W)
            mask = torch.from_numpy(mask).long()

        return {
            "image": image,
            "mask": mask,
        }

    #def apply_mask_mapping(self, mask: np.ndarray) -> np.ndarray:
    #    mask_out = mask.copy()
    #    for old, new in self.mask_map.items():
    #        mask_out[mask == old] = new
    #    return mask_out

    def plot(self, idx: int):
        import matplotlib.pyplot as plt

        sample = self.__getitem__(idx)
        img = sample["image"]
        mask = sample["mask"]

        if img.shape[0] == 4:
            rgb = img[:3].permute(1, 2, 0)
        else:
            rgb = img.permute(1, 2, 0)

        # --- Fix for matplotlib ---
        #if rgb.dtype == torch.float32:
        #    rgb = rgb / 255.0  # ensure values are 0-1

        plt.figure(figsize=(10, 5))
        plt.subplot(1, 2, 1)
        plt.imshow(rgb)
        plt.title("RGB Image")

        plt.subplot(1, 2, 2)
        plt.imshow(mask, cmap="gray")
        plt.title("Mask")
        plt.show()


class CustomDataModule(pl.LightningDataModule):
    def __init__(
        self,
        local_path,
        batch_size=4,
        num_workers=8,
        mask_map: dict[int, int] | None = None,
        test_split="train",
        sample_ratio=1.0,
        seed=0,
    ):
        super().__init__()
        self.local_path = local_path
        self.batch_size = batch_size
        self.num_workers = num_workers
        self.mask_map = mask_map
        self.test_split = test_split
        self.sample_ratio = sample_ratio
        self.seed = seed

        # Optional augmentations (geometry only)
        self.train_transform = A.Compose([
            A.RandomRotate90(p=0.1),
            A.HorizontalFlip(p=0.1),
            A.VerticalFlip(p=0.1),
            ToTensorV2(),
        ])

        self.val_transform = A.Compose([
            ToTensorV2(),
        ])

        self.test_transform = A.Compose([
            ToTensorV2(),
        ])

    def setup(self, stage=None):
        if stage in ["fit", None]:
            self.train_dataset = CustomDataset(
                self.local_path,
                split="train",
                transform=self.train_transform,
                #mask_map=self.mask_map,
                sample_ratio=self.sample_ratio,
                seed=self.seed,
            )
            print(f"Training samples: {len(self.train_dataset)}")

        if stage in ["fit", "validate", None]:
            self.val_dataset = CustomDataset(
                self.local_path,
                split="val",
                transform=self.val_transform,
                #mask_map=self.mask_map,
            )
            print(f"Validation samples: {len(self.val_dataset)}")

        if stage in ["test", None]:
            self.test_dataset = CustomDataset(
                self.local_path,
                split=self.test_split,
                transform=self.test_transform,
                #mask_map=self.mask_map,
            )
            print(f"Test samples: {len(self.test_dataset)}")

    def train_dataloader(self):
        return DataLoader(
            self.train_dataset,
            batch_size=self.batch_size,
            shuffle=True,
            num_workers=self.num_workers,
            pin_memory=True,
        )

    def val_dataloader(self):
        return DataLoader(
            self.val_dataset,
            batch_size=self.batch_size,
            shuffle=False,
            num_workers=self.num_workers,
            pin_memory=True,
        )

    def test_dataloader(self):
        return DataLoader(
            self.test_dataset,
            batch_size=self.batch_size,
            shuffle=False,
            num_workers=self.num_workers,
            pin_memory=True,
        )


# load data
data_module = CustomDataModule(
    local_path="samples",
    batch_size=16,
    num_workers=4, # issue for num_workers > 0 is platform specific, which has been a problem in Windows (https://stackoverflow.com/questions/77174223/simplest-dataloader-fails-when-num-workers0)
    #mask_map={2: 0},
    sample_ratio=1.0 
)

#data_module.setup("fit")

#batch = next(iter(data_module.train_dataloader()))
#print(batch["image"].shape, batch["mask"].shape)

from terratorch.tasks import SemanticSegmentationTask
import torch
import torchmetrics
import pytorch_lightning as pl

class CustomModelTiM(pl.LightningModule):
    def __init__(
            self, 
            num_classes=2, 
            tim=None, 
            backbone="terramind_v1_base_tim",
            backbone_modalities=None,
            loss="ce",
            optimizer="AdamW",
            lr=2e-5,
            weight_decay=0.01,
            t_max=10,
            ignore_index=-1,
            freeze_backbone=True,
            freeze_decoder=False,
        ):
        super().__init__()
        self.save_hyperparameters()
        
        #self.num_classes = 2
        #self.tim = ["S1GRD"]
        tim = tim or ["S1GRD"]
        backbone_modalities = backbone_modalities or ["RGB"]
    
        self.model_args={
            # TerraMind backbone
            "backbone": backbone,
            "backbone_pretrained": True,
            "backbone_modalities": backbone_modalities,#["RGB"], #S2RGB
            "backbone_tim_modalities": tim,
            # Optionally, define the input bands. This is only needed if you select a subset of the pre-training bands, as explained above.
            # "backbone_bands": {"S1GRD": ["VV"]},

            # Necks
            "necks": [
                {
                    "name": "SelectIndices",
                    "indices": [2, 5, 8, 11] # indices for terramind_v1_base
                    # "indices": [5, 11, 17, 23] # indices for terramind_v1_large
                },
                {"name": "ReshapeTokensToImage",
                "remove_cls_token": False},  # TerraMind is trained without CLS token, which neads to be specified.
                {"name": "LearnedInterpolateToPyramidal"}  # Some decoders like UNet or UperNet expect hierarchical features. Therefore, we need to learn a upsampling for the intermediate embedding layers when using a ViT like TerraMind.
            ],

            # Decoder
            "decoder": "UNetDecoder",
            "decoder_channels": [512, 256, 128, 64],

            # Head
            "head_dropout": 0.1,
            "num_classes": num_classes,
        }

        self.model = SemanticSegmentationTask(
            model_factory="EncoderDecoderFactory",  # Combines a backbone with necks, the decoder, and a head
            model_args=self.model_args,
            loss=loss, # 'ce', 'dice', 'focal'
            optimizer=optimizer,
            lr=lr,
            #task='binary',
            ignore_index=ignore_index, #-1 -> don;t ignore any class
            freeze_backbone=freeze_backbone,
            freeze_decoder=freeze_decoder,
            plot_on_val=False,
            class_names=[str(i) for i in range(num_classes)]
        )

        # Metrics
        self.train_iou = torchmetrics.JaccardIndex(task="multiclass", num_classes=num_classes, ignore_index=-1) #multiclass -1
        self.val_iou = torchmetrics.JaccardIndex(task="multiclass", num_classes=num_classes, ignore_index=-1)
        self.train_acc = torchmetrics.Accuracy(task="multiclass", num_classes=num_classes, ignore_index=-1)
        self.val_acc = torchmetrics.Accuracy(task="multiclass", num_classes=num_classes, ignore_index=-1)
        self.train_f1 = torchmetrics.F1Score(task="multiclass", num_classes=num_classes, ignore_index=-1)
        self.val_f1 = torchmetrics.F1Score(task="multiclass", num_classes=num_classes, ignore_index=-1)

    def forward(self, x):
        return self.model({"RGB": x})

    def training_step(self, batch, batch_idx):
        images, masks = batch["image"], batch["mask"]

        outputs = self.model({"RGB": images})
        logits = outputs.output

        # Cross-entropy loss
        loss = torch.nn.functional.cross_entropy(logits, masks)
        preds = torch.argmax(logits, dim=1)

        self.train_iou(preds, masks)
        self.train_acc(preds, masks)
        self.train_f1(preds, masks)

        self.log('train_loss', loss, on_step=True, on_epoch=True, prog_bar=True)
        self.log('train_iou', self.train_iou, on_epoch=True, prog_bar=True)
        self.log('train_acc', self.train_acc, on_epoch=True, prog_bar=True)
        self.log('train_f1', self.train_f1, on_epoch=True, prog_bar=True)
        
        #  Add periodic cleanup:
        if batch_idx % 20 == 0:  # Every 20 batches
            del outputs, logits, preds  # Clean intermediate variables
            torch.cuda.empty_cache()

        return loss

    def validation_step(self, batch, batch_idx):
        images, masks = batch["image"], batch["mask"]

        outputs = self.model({"RGB": images})
        logits = outputs.output

        loss = torch.nn.functional.cross_entropy(logits, masks)
        preds = torch.argmax(logits, dim=1)

        self.val_iou(preds, masks)
        self.val_acc(preds, masks)
        self.val_f1(preds, masks)

        self.log('val_loss', loss, on_epoch=True, prog_bar=True)
        self.log('val_iou', self.val_iou, on_epoch=True, prog_bar=True)
        self.log('val_acc', self.val_acc, on_epoch=True, prog_bar=True)
        self.log('val_f1', self.val_f1, on_epoch=True, prog_bar=True)

        # Add cleanup for validation too:
        del outputs, logits, preds
        if batch_idx % 10 == 0:
            torch.cuda.empty_cache()

        return loss
    
    def test_step(self, batch, batch_idx):
        images, masks = batch["image"], batch["mask"]

        outputs = self.model({"RGB": images})
        logits = outputs.output

        loss = torch.nn.functional.cross_entropy(logits, masks)
        preds = torch.argmax(logits, dim=1)

        # Compute metrics
        self.val_iou(preds, masks)
        self.val_acc(preds, masks)
        self.val_f1(preds, masks)

        self.log('test_loss', loss, on_epoch=True, prog_bar=True)
        self.log('test_iou', self.val_iou, on_epoch=True, prog_bar=True)
        self.log('test_acc', self.val_acc, on_epoch=True, prog_bar=True)
        self.log('test_f1', self.val_f1, on_epoch=True, prog_bar=True)

        # Cleanup
        del outputs, logits, preds
        if batch_idx % 10 == 0:
            torch.cuda.empty_cache()

        return loss

    #def configure_optimizers(self):
        #self.model.parameters(),
        #lr=self.hparams.lr,
    #    optimizer = torch.optim.AdamW(self.model.parameters(), lr=lr, weight_decay=0.01)
    #    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=10)
    #   return [optimizer], [scheduler]
    
    def configure_optimizers(self):
        optimizer = torch.optim.AdamW(
            self.model.parameters(),
            lr=self.hparams.lr,               # dynamic
            weight_decay=self.hparams.weight_decay,
        )

        scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
            optimizer,
            T_max=self.hparams.t_max,        # dynamic
        )

        return {
            "optimizer": optimizer,
            "lr_scheduler": scheduler,
        }
        

#model = CustomModelTiM(tim=["S1GRD"], num_classes=2) #s2l2a, s1rtc, s1grd, dem, lulc, ndvi
model = CustomModelTiM(tim=["S1GRD"], #s2l2a, s1rtc, s1grd, dem, lulc, ndvi
                       num_classes=2, 
                       backbone="terramind_v1_base_tim", #"terratorch_terramind_v1_large_tim"
                       backbone_modalities=["RGB"],
                       optimizer="AdamW",
                       lr=1e-4,
                       loss="ce", 
                       freeze_backbone=True, 
                       freeze_decoder=False,)

assert isinstance(model, pl.LightningModule)

print('Using PyTorch version:', torch.__version__)
if torch.cuda.is_available():
    print('Using GPU, device name:', torch.cuda.get_device_name(0))
    device = torch.device('cuda')
else:
    print('No GPU found, using CPU instead.')
    device = torch.device('cpu')

 # define
pl.seed_everything(0)

accelerator="gpu" if torch.cuda.is_available() else "cpu"

default_root_dir = os.getcwd()

#checkpoint_callback = ModelCheckpoint(
#    monitor="val_loss", dirpath=default_root_dir, save_top_k=1, save_last=True
#)

checkpoint_callback = pl.callbacks.ModelCheckpoint(
    dirpath="output_s2_1e-4/checkpoints/",
    #mode="max",
    monitor="val_loss", #"val/mIoU"
    filename="best-loss",
    save_weights_only=True,
    save_last=True,
)


#early_stopping_callback = EarlyStopping(monitor='val_loss', min_delta=0.00, patience=5)
#logger = TensorBoardLogger(save_dir=default_root_dir, name='trial_logs')
logger = CSVLogger(save_dir=default_root_dir, name='trial_logs')

# Define trainer
trainer = Trainer( #pl.Trainer
    accelerator=accelerator,#auto
    callbacks=[checkpoint_callback],#, early_stopping_callback], pl.callbacks.RichProgressBar()
    log_every_n_steps=30,
    logger=logger,#True
    min_epochs=1,
    max_epochs=20,
    devices=1,
    precision="bf16-mixed", #16-mixed
    num_nodes=1,
    gradient_clip_val=1.0,
    enable_checkpointing=True,
    detect_anomaly=False,
    #default_root_dir="output/model/"
)

#trainer.fit(model, datamodule=data_module)

import os
import torch
import matplotlib.pyplot as plt

class BatchPlot:
    def __init__(
        self,
        model,
        dataloader,
        split_name="test",
        out_dir="viz_samples",
        mean=None,
        std=None,
    ):
        """
        Args:
            model: LightningModule (already loaded)
            dataloader: DataLoader for visualization
            split_name: "test" or "testc" (used in filenames)
            out_dir: directory to save PNGs
            mean, std: ONLY set if dataset was normalized
        """
        self.model = model
        self.dataloader = dataloader
        self.split_name = split_name
        self.out_dir = out_dir
        self.mean = mean
        self.std = std
        self.iterator = iter(dataloader)
        self.counter = 0

        os.makedirs(out_dir, exist_ok=True)

        try:
            self.device = next(model.parameters()).device
        except StopIteration:
            self.device = torch.device("cpu")

        self.model.eval()

    def maybe_unnormalize(self, img_tensor):
        img = img_tensor.clone().detach()

        if self.mean is not None and self.std is not None:
            mean = torch.tensor(self.mean).view(3, 1, 1)
            std = torch.tensor(self.std).view(3, 1, 1)
            img = img * std + mean

        img = torch.clamp(img, 0, 1)
        return img

    def save_sample(self, sample):
        fig, axes = plt.subplots(1, 3, figsize=(12, 4))

        img = self.maybe_unnormalize(sample["image"])
        axes[0].imshow(img.permute(1, 2, 0))
        axes[0].set_title("Image")

        axes[1].imshow(sample["mask"], cmap="gray")
        axes[1].set_title("Ground Truth")

        axes[2].imshow(sample["prediction"], cmap="gray")
        axes[2].set_title("Prediction")

        for ax in axes:
            ax.axis("off")

        filename = f"{self.split_name}_{self.counter:05d}.png"
        path = os.path.join(self.out_dir, filename)

        plt.savefig(path, bbox_inches="tight", dpi=150)
        plt.close(fig)

        self.counter += 1

    def next_batch(self):
        try:
            batch = next(self.iterator)
        except StopIteration:
            print(f"[{self.split_name}] End of dataset.")
            return

        images = batch["image"].to(self.device)

        with torch.no_grad():
            outputs = self.model(images)
            preds = torch.argmax(outputs.output, dim=1).cpu()

        for i in range(images.shape[0]):
            sample = {
                "image": batch["image"][i].cpu(),
                "mask": batch["mask"][i],
                "prediction": preds[i],
            }
            self.save_sample(sample)



# Let's test the fine-tuned model
best_ckpt_path = "output_s2_1e-4/checkpoints/best-loss.ckpt"

model = CustomModelTiM.load_from_checkpoint(
    best_ckpt_path,
    num_classes=2,
    tim=["S1GRD"],
    backbone="terramind_v1_base_tim", #"terratorch_terramind_v1_large_tim" v1_base
    backbone_modalities=["RGB"],
)

print(model.hparams)

for split in ["test", "testc"]:

    dm = CustomDataModule(
        local_path="samples",
        batch_size=32,
        num_workers=2,
        test_split=split,
    )

    dm.setup(stage="test")

    trainer.test(model, datamodule=dm)

    visualizer = BatchPlot(
        model=model,
        dataloader=dm.test_dataloader(),
        split_name=split,
        out_dir="vis_s2",
        mean=None,
        std=None
    )

    visualizer.next_batch()

best_ckpt_path = "output_s2c_1e-4/checkpoints/best-loss.ckpt"

model = CustomModelTiM.load_from_checkpoint(
    best_ckpt_path,
    num_classes=2,
    tim=["S1GRD"],
    backbone="terramind_v1_base_tim", #"terratorch_terramind_v1_large_tim" v1_base
    backbone_modalities=["RGB"],
)

print(model.hparams)

for split in ["test", "testc"]:

    dm = CustomDataModule(
        local_path="samples",
        batch_size=32,
        num_workers=2,
        test_split=split,
    )

    dm.setup(stage="test")

    trainer.test(model, datamodule=dm)

    visualizer = BatchPlot(
        model=model,
        dataloader=dm.test_dataloader(),
        split_name=split,
        out_dir="vis_s2c",
        mean=None,
        std=None
    )

    visualizer.next_batch()