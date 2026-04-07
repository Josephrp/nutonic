# TerraMind-Flood: DEM-Enhanced Flood Detection with Physics-Aware Learning

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/R1-AK/terramind-flood/blob/main/TerraMind_Flood_Full_Implementation.ipynb)
[![HuggingFace](https://img.shields.io/badge/HuggingFace-Challenge-yellow)](https://huggingface.co/spaces/ibm-esa-geospatial/challenge)

> IBM-ESA TerraMind Blue-Sky Challenge 2025 Submission

## Overview

**TerraMind-Flood** is a flood detection system that extends TerraMind's multimodal capabilities with elevation-aware reasoning. Our approach integrates Digital Elevation Model (DEM) information through cross-attention fusion, enabling the model to understand that *water flows downhill*—a fundamental physical constraint often ignored by purely data-driven methods.

<img width="1939" height="3155" alt="evaluation_results" src="https://github.com/user-attachments/assets/96b1468b-8859-48e2-9481-19a1440be025" />
*Flood predictions on held-out validation countries (Mekong, Sri Lanka, USA)*

## Results

| Metric | Value | Description |
|--------|-------|-------------|
| **IoU** | 58.3% | Intersection over Union for flood class |
| **F1 Score** | 70.1% | Harmonic mean of precision and recall |
| **POD** | 88.2% | Probability of Detection (recall) |
| **FAR** | 39.2% | False Alarm Ratio |

<img width="1489" height="396" alt="training_curves" src="https://github.com/user-attachments/assets/c3dcd146-8ca5-4769-b6c8-b5658cb6bd44" />
*Training loss and IoU metrics over 76 epochs with early stopping*

## Quick Start

### Option 1: Google Colab (Recommended)
Click the "Open in Colab" badge above, or:
1. Upload `TerraMind_Flood_Full_Implementation.ipynb` to Google Colab
2. Select GPU runtime (T4 or better)
3. Run all cells

### Option 2: Local Installation
```bash
# Clone the repo
git clone https://github.com/R1-AK/terramind-flood.git
cd terramind-flood

# Install dependencies
pip install torch torchvision einops huggingface_hub matplotlib numpy

# Run notebook
jupyter notebook TerraMind_Flood_Full_Implementation.ipynb
```

## Repository Structure

```
terramind-flood/
├── TerraMind_Flood_Full_Implementation.ipynb  # Main notebook (run this)
├── RESULT2_TerraMind_Flood_Full_Implementation.ipynb # Notebook result (after we run it)
├── terramind_flood_sen1floods11_best.pth      # Trained model weights (run the main notebook first)
├── training_curves.png                         # Training visualization
├── evaluation_results.png                      # Sample predictions
└── README.md
```

## Architecture

1. **Frozen TerraMind Backbone (87.3M parameters):** Preserves rich geospatial representations learned during pre-training

2. **Cross-Attention DEM Fusion:** Optical features query elevation information, learning spatially-varying relationships between terrain and flood susceptibility

3. **ControlNet-Style Adapter:** Zero-initialized convolutions ensure gradual learning without disrupting pre-trained representations

4. **Physics-Aware Loss:** Gradient consistency term encouraging predictions to align with downhill water flow patterns

## Dataset

We train on [Sen1Floods11](https://github.com/cloudtostreet/Sen1Floods11) (Bonafilia et al., CVPR 2020):
- 446 hand-labeled flood events across 11 countries
- Six continents coverage
- Strict country-based train/validation split for geographic generalization

**Training:** Bolivia, Ghana, India, Nigeria, Pakistan, Paraguay, Somalia, Spain (237 samples)
**Validation:** Mekong, Sri Lanka, USA (110 samples)

## Requirements

- Python 3.8+
- PyTorch 2.0+
- CUDA-capable GPU with 16GB+ VRAM (or Google Colab T4)
- ~10GB disk space for dataset

## Key Learnings

1. **Class imbalance matters:** Floods cover only ~11% of imagery. We use 9x class weighting to address this.

2. **Geographic generalization is hard:** Country-based validation splits reveal true generalization capability.

3. **DEM integration helps:** Cross-attention fusion outperforms simple concatenation.

4. **Foundation models accelerate development:** Fine-tuning required only ~76 epochs on a single GPU.

## Future Directions

- Real DEM Integration (Copernicus DEM / SRTM)
- Temporal modeling with pre-flood imagery
- SAR fusion for cloud-penetrating detection
- Uncertainty quantification for operational deployment

## Citation

If you use this work, please cite:

```bibtex
@article{jakubik2025terramind,
  title={TerraMind: Large-Scale Generative Multimodality for Earth Observation},
  author={Jakubik, Johannes and others},
  year={2025}
}

@inproceedings{bonafilia2020sen1floods11,
  title={Sen1Floods11: A georeferenced dataset to train and test deep learning flood algorithms for Sentinel-1},
  author={Bonafilia, Derrick and others},
  booktitle={CVPR Workshops},
  year={2020}
}

@article{zhu2025earth,
  title={On the foundations of Earth foundation models},
  author={Zhu, Xiao Xiang and others},
  journal={Nature Communications Earth \& Environment},
  year={2025}
}
```

## License

MIT License

## Acknowledgments

- IBM-ESA for developing TerraMind and organizing the Blue-Sky Challenge
- Cloud to Street for the Sen1Floods11 dataset
- Google Colab for accessible GPU compute

---

**Challenge Submission:** [HuggingFace Discussion](https://huggingface.co/spaces/ibm-esa-geospatial/challenge/discussions)
