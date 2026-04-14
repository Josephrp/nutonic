# `data/catalog`

Curated **maps** index (`maps.yaml`) and per-**location** YAML consumed by the shipped-cache pipeline (`data/scripts/catalog_import_poi.py`, `assemble_manifest`, etc.). Large downloads stay under `data/downloads/` (gitignored); this tree holds normalized metadata only.

Populate with:

```bash
pip install -r data/scripts/requirements.txt
python data/scripts/catalog_import_poi.py --poi-root data/downloads/geoguessr_poi_12 --force
python data/scripts/catalog_lint.py
```
