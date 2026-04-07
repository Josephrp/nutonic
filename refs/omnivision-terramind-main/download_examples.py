import os
import urllib.request

BASE = "https://raw.githubusercontent.com/IBM/terramind/refs/heads/main/examples"

modalities = ["S2L2A", "S1RTC", "DEM", "LULC", "NDVI"]

files = [
    "38D_378R_2_3.tif",
    "282D_485L_3_3.tif",
    "433D_629L_3_1.tif",
    "637U_59R_1_3.tif",
    "609U_541L_3_0.tif",
]

os.makedirs("examples", exist_ok=True)

for m in modalities:
    os.makedirs(f"examples/{m}", exist_ok=True)
    for f in files:
        url = f"{BASE}/{m}/{f}"
        out = f"examples/{m}/{f}"
        if os.path.exists(out):
            print("skip", out)
            continue
        print("downloading", url)
        urllib.request.urlretrieve(url, out)

print("Done. Examples saved under ./examples/")