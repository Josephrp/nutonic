# 🛰️ NU:TONIC

Nu:Tonic is a post-apocalyptic, **solo-first** geo-guessing game with **async** comparison on shared **maps** (no live lobbies or synchronized opponent sessions—see `docs/SOCIAL-AND-COMPETITION.md`, `docs/GAME-ENGINE.md` §14) where:
*   Earth players (“Humans”) / (“Aliens”)
*   Stranded orbital players (“Astronauts”)
*   AI opponents - NüTonic 
…compete to identify real-world locations from fragmented memory, satellite remnants, and distorted map data.


In the aftermath of a fractured world, when sanctions severed supply lines and left orbital crews drifting beyond reach, memory became the last tether to Earth.

Cities fell silent. Networks splintered. Maps decayed into fragments of what once was.

Up above, the astronauts—cut off, rationing air and time—cling to fading recollections of coastlines, skylines, deserts, and streets they may never walk again. Down below, humans navigate a changed planet, where landmarks persist but meaning has shifted. And somewhere in between, a third presence has emerged—an artificial intelligence, piecing together the world not from memory, but from patterns, probabilities, and echoes of data.

**NU:TONIC** is born.

Three forces converge:

* **Astronauts**, recalling Earth through distortion and distance
* **Humans**, grounded yet uncertain in a transformed world
* **AI entities**, reconstructing reality without ever having lived it

Together, they compete to answer a single question:

> *What do you remember about the world?*

Players are presented with fragments—visual cues, partial signals, warped perspectives—and must place their trust in memory, intuition, or logic to locate places that once mattered. Each guess is more than a point scored; it is a reconstruction of a shared past.

Accuracy brings you closer not just to victory, but to clarity.
Distance reveals how much has been lost.

In NU:TONIC, every round is a quiet act of defiance against forgetting.

Because when the world breaks,
**memory becomes the game.**

---

## Developer documentation

How to contribute (environment, PM2 checks, CI): [`CONTRIBUTING.md`](CONTRIBUTING.md). Implementation rules live under [`rules/README.md`](rules/README.md). **Screen background music** (one loop per primary route, **music on/off in the header on every shipped screen**, bundled assets) is specified in [`docs/SCREEN-MUSIC-SPEC.md`](docs/SCREEN-MUSIC-SPEC.md) and preference keys in [`docs/CLIENT-SETTINGS-SPEC.md`](docs/CLIENT-SETTINGS-SPEC.md) §6.7.

**Inference (not the game client):** [`inference/README.md`](inference/README.md) indexes **Street View pano**, **standard LFM-VL hints**, and **specialist satellite** LFM-VL (caption / VQA / grounding, `refs/satellite-vlm/` prompts, Gradio demo). Master plan: [`plans/2026-04-07-lfm-vl-inference-spaces-satellite-and-streetview.md`](plans/2026-04-07-lfm-vl-inference-spaces-satellite-and-streetview.md). Street View drill-down: [`plans/2026-04-07-streetview-lfm-vl-hint-inference-plane.md`](plans/2026-04-07-streetview-lfm-vl-hint-inference-plane.md). Orchestration: [`docs/SERVER-AND-INFERENCE-ARCHITECTURE.md`](docs/SERVER-AND-INFERENCE-ARCHITECTURE.md).
