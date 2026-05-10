from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from huggingface_hub import hf_hub_download

from nutonic_pro_gradio_demo.client import NutonicServerClient
from nutonic_pro_gradio_demo.models import ProVlmModelManifest
from nutonic_pro_gradio_demo.settings import Settings


@dataclass(frozen=True)
class LoadedModel:
    manifest: ProVlmModelManifest
    model_dir: Path
    # Actual Transformers objects are loaded lazily when we know the model type.
    model: Any
    processor: Any


_LOADED: LoadedModel | None = None


def ensure_model_loaded(*, client: NutonicServerClient, settings: Settings) -> LoadedModel:
    global _LOADED
    manifest = client.get_vlm_model_manifest()

    # Space-side override: allow forcing a different bundle than what the server advertises.
    if settings.vlm_override_bundle_id.strip():
        override = settings.vlm_override_bundle_id.strip()
        manifest = ProVlmModelManifest(
            model_bundle_id=override,
            revision=(settings.vlm_override_revision.strip() or manifest.revision),
            download_url=(settings.vlm_override_download_url.strip() or manifest.download_url),
            sha256=(settings.vlm_override_sha256.strip() or ""),
            size_bytes=(int(settings.vlm_override_size_bytes) if settings.vlm_override_size_bytes else 0),
            runtime=manifest.runtime,
            contract_ids=manifest.contract_ids,
        )
    cache_key = f"{manifest.model_bundle_id}-{manifest.revision}".replace("/", "_")
    cache_dir = _resolve_cache_dir(settings=settings, cache_key=cache_key)
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Prefer pulling the full repo snapshot so Transformers can find config/tokenizer/processor files.
    model_dir, weight_file = _download_model_snapshot(manifest=manifest, client=client, cache_dir=cache_dir)
    if weight_file is not None:
        _verify_sha256(path=weight_file, expected=manifest.sha256)

    if _LOADED is not None and _LOADED.manifest.revision == manifest.revision and _LOADED.manifest.model_bundle_id == manifest.model_bundle_id:
        return _LOADED

    model, processor = _load_transformers_from_dir(model_dir=model_dir)
    _LOADED = LoadedModel(manifest=manifest, model_dir=model_dir, model=model, processor=processor)
    return _LOADED


def _resolve_cache_dir(*, settings: Settings, cache_key: str) -> Path:
    if settings.model_cache_dir.strip():
        return Path(settings.model_cache_dir).expanduser().resolve() / cache_key
    # HF Spaces may provide a persistent volume; otherwise fall back to /tmp.
    base = os.environ.get("HF_HOME") or os.environ.get("HUGGINGFACE_HUB_CACHE") or "/tmp"
    return Path(base).expanduser().resolve() / "nutonic_pro_vlm" / cache_key


def _download_model_snapshot(
    *,
    manifest: ProVlmModelManifest,
    client: NutonicServerClient,
    cache_dir: Path,
) -> tuple[Path, Path | None]:
    """
    Returns (model_dir, weight_file_if_known).

    We prefer Hub snapshot downloads so `transformers` can load configs/processors.
    If the model is only available as a raw byte stream (non-Hub URL), we stage the
    weights file and will require additional files or trust_remote_code behavior later.
    """
    from huggingface_hub import snapshot_download

    model_bundle_id = manifest.model_bundle_id.strip()
    revision = manifest.revision.strip()
    if model_bundle_id and "/" in model_bundle_id:
        local_dir = snapshot_download(
            repo_id=model_bundle_id,
            revision=revision or None,
            repo_type="model",
            cache_dir=str(cache_dir),
        )
        model_dir = Path(local_dir)
        # Best-effort: locate the main safetensors file to validate sha256 if possible.
        weight_file = model_dir / "model.safetensors"
        if not weight_file.is_file():
            weight_file = None
        return model_dir, weight_file

    url = manifest.download_url.strip()
    target = cache_dir / "model.safetensors"
    if target.is_file() and target.stat().st_size == manifest.size_bytes:
        return cache_dir, target
    data = client.get_bytes_by_url(url)
    target.write_bytes(data)
    return cache_dir, target


def _verify_sha256(*, path: Path, expected: str) -> None:
    exp = expected.strip().lower()
    if not exp:
        return
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    got = h.hexdigest().lower()
    if got != exp:
        raise ValueError(f"Model sha256 mismatch for {path.name}: expected {exp}, got {got}")


def _load_transformers_from_dir(*, model_dir: Path) -> tuple[Any, Any]:
    """
    Load Transformers model/processor.

    NOTE: We don't yet know the exact architecture of `NuTonic/lspace`. This function uses a
    conservative Auto* strategy and will be refined once we validate the model config.
    """
    import transformers
    from transformers import AutoConfig, AutoModel, AutoProcessor
    try:
        from transformers import AutoModelForVision2Seq  # type: ignore
    except Exception:
        AutoModelForVision2Seq = None  # type: ignore[assignment]

    try:
        processor = AutoProcessor.from_pretrained(str(model_dir), trust_remote_code=True)
    except ImportError as e:
        # Common: Lfm2VlImageProcessor requires torchvision.
        raise ImportError(
            "Failed to load the model processor. This model requires extra vision deps.\n"
            "For NU:TONIC PRO demo, ensure `torchvision` is installed in the Space environment."
        ) from e
    # NOTE: Do NOT pass `device_map` here.
    # Some Spaces runtimes end up without `accelerate` even when it's listed in requirements,
    # and `transformers` will crash hard if `device_map` is present. We'll instead load on the
    # default device and move to CUDA inside the `@spaces.GPU` inference call when available.
    config = AutoConfig.from_pretrained(str(model_dir), trust_remote_code=True)

    model_kwargs: dict[str, Any] = {"torch_dtype": "auto", "trust_remote_code": True}

    # Prefer exact architecture to ensure `generate()` exists.
    architectures = getattr(config, "architectures", None) or []
    model: Any | None = None
    if isinstance(architectures, list):
        for arch in architectures:
            if not isinstance(arch, str) or not arch.strip():
                continue
            cls = getattr(transformers, arch, None)
            if cls is None:
                continue
            try:
                model = cls.from_pretrained(str(model_dir), **model_kwargs)
                break
            except Exception:
                model = None
                continue

    if model is None:
        if AutoModelForVision2Seq is not None:
            try:
                model = AutoModelForVision2Seq.from_pretrained(str(model_dir), **model_kwargs)
            except Exception:
                model = AutoModel.from_pretrained(str(model_dir), **model_kwargs)
        else:
            model = AutoModel.from_pretrained(str(model_dir), **model_kwargs)
    # ZeroGPU supports a CUDA emulation mode outside @spaces.GPU. Put the model on CUDA
    # once at load time to avoid repeated transfers inside the decorated GPU call.
    try:
        import torch

        model = model.to(torch.device("cuda"))
    except Exception:
        # If CUDA emulation or `.to("cuda")` isn't supported for a remote-code model, continue.
        pass
    model.eval()
    return model, processor


def infer_caption_and_boxes(*, loaded: LoadedModel, prompt: str, image_rgb: Any, max_new_tokens: int = 512) -> str:
    """
    Runs the local VLM inference and returns raw decoded text.

    `image_rgb` may be a single PIL Image (RGB) or a sequence of PIL Images. LFM2 VL processors require
    one `<image>` placeholder per image in the prompt text.
    """
    import torch
    from PIL import Image as PILImage

    processor = loaded.processor
    model = loaded.model
    if not hasattr(model, "generate"):
        raise RuntimeError("Loaded Transformers model does not implement generate(); incompatible VLM architecture")

    if isinstance(image_rgb, PILImage.Image):
        pil_list = [image_rgb]
    elif isinstance(image_rgb, Sequence) and not isinstance(image_rgb, (str, bytes)):
        pil_list = list(image_rgb)
    else:
        raise TypeError("image_rgb must be a PIL Image or a sequence of PIL Images")

    if not pil_list:
        raise ValueError("At least one image is required for VLM inference")

    pil_list = [im.convert("RGB") if getattr(im, "mode", None) != "RGB" else im for im in pil_list]

    # Lfm2VlProcessor: count of `<image>` tokens in text must match len(images).
    image_token = getattr(processor, "image_token", "<image>")
    text_with_image = (image_token + "\n") * len(pil_list) + prompt

    inputs = processor(images=pil_list, text=text_with_image, return_tensors="pt")
    # Move tensors to the model's device when possible.
    device = getattr(model, "device", None)
    if device is not None:
        inputs = {k: v.to(device) if isinstance(v, torch.Tensor) else v for k, v in inputs.items()}

    with torch.inference_mode():
        output_ids = model.generate(**inputs, max_new_tokens=max_new_tokens)
    decoded = processor.batch_decode(output_ids, skip_special_tokens=True)
    return (decoded[0] if decoded else "").strip()


# --- ZeroGPU: decorate the actual inference call ---
try:
    import spaces  # type: ignore

    @spaces.GPU(duration=120)  # type: ignore[misc]
    def zerogpu_infer_caption_and_boxes(
        *,
        loaded: LoadedModel,
        prompt: str,
        image_rgb: Any,
        max_new_tokens: int = 512,
    ) -> str:
        return infer_caption_and_boxes(loaded=loaded, prompt=prompt, image_rgb=image_rgb, max_new_tokens=max_new_tokens)

except Exception:

    def zerogpu_infer_caption_and_boxes(
        *,
        loaded: LoadedModel,
        prompt: str,
        image_rgb: Any,
        max_new_tokens: int = 512,
    ) -> str:
        return infer_caption_and_boxes(loaded=loaded, prompt=prompt, image_rgb=image_rgb, max_new_tokens=max_new_tokens)

