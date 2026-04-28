from __future__ import annotations

from lfm_vl_satellite_caption_service.models import SatelliteInferRequest, SatelliteInferResponse


def infer_stub(req: SatelliteInferRequest) -> SatelliteInferResponse:
    return SatelliteInferResponse(
        caption=(
            "Satellite orthoimagery shows mixed land-cover textures and built structure footprints "
            "(stub — no VLM weights loaded)."
        ),
        model_id="stub",
        analysis_profile=req.analysis_profile,
        contract_id=req.contract_id,
    )
