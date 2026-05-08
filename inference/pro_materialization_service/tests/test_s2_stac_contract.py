import numpy as np

from pro_materialization_service.geospatial.s2_stac_load import S2PatchResult


def test_s2_patch_result_is_named_tuple_contract() -> None:
    stack = np.zeros((12, 2, 2), dtype=np.float32)
    result = S2PatchResult(stack=stack, meta={"stac_item_id": "scene-1"}, scl_patch=None)

    unpacked_stack, meta, scl_patch = result

    assert result._fields == ("stack", "meta", "scl_patch")
    assert unpacked_stack is stack
    assert meta["stac_item_id"] == "scene-1"
    assert scl_patch is None
