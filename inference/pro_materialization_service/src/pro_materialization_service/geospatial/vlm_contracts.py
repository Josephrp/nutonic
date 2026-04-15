"""``vlm_contract_id`` → fixed canvas size and roles (`plans/...` §4.1)."""



from __future__ import annotations



from dataclasses import dataclass





@dataclass(frozen=True)

class VlmContract:

    contract_id: str

    width: int

    height: int

    roles: tuple[str, ...]





# One row per shipped bundle revision; materialization fails fast if roles cannot be filled.

VLM_CONTRACTS: dict[str, VlmContract] = {

    "nutonic.pro.vlm.v1_512": VlmContract(

        contract_id="nutonic.pro.vlm.v1_512",

        width=512,

        height=512,

        roles=("mapbox_rgb",),

    ),

    "nutonic.pro.vlm.v1_512_fc_scl": VlmContract(

        contract_id="nutonic.pro.vlm.v1_512_fc_scl",

        width=512,

        height=512,

        roles=("mapbox_rgb", "sentinel_fc", "cloud_mask_thumb"),

    ),

}





def resolve_vlm_contract(contract_id: str) -> VlmContract:

    c = VLM_CONTRACTS.get(contract_id.strip())

    if c is None:

        keys = ", ".join(sorted(VLM_CONTRACTS))

        raise ValueError(f"Unknown vlm_contract_id={contract_id!r}; known: {keys}")

    return c

