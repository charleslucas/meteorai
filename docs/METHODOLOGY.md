# MeteorAI — Detection Methodology

Last updated: 2026-07-01

This document summarises the approaches used in published research, their trade-offs, and
the reasoning behind the choices made for this project given the constraints of a minimal
budget and limited training data.

---

## Project scope and goals

This is a hobbyist-scale project with two practical goals:

1. **Build a general meteorite feature-recognition model** — identify meteorite-specific
   visual features (fusion crust, regmaglypts, Widmanstätten pattern, chondrules) in
   photographs from any source. "General" means terrain-agnostic and not tuned to any
   specific recovery site.

2. **Support drone-based field surveys** — fly a drone over a candidate area, process the
   video/imagery, and flag tiles that may contain a meteorite for follow-up inspection.

Unlike the most published projects (e.g. the Australian Desert Fireball Network), this
project is **not targeting a specific known terrain type**. The intent is a model general
enough to be useful in any desert or open terrain, with the option to **fine-tune it for
a specific survey site** before an actual expedition.

**Two-phase deployment strategy**:
- Phase 1 (general): train on diverse images from many sources and terrain types
- Phase 2 (site-specific): before a survey expedition, collect fresh training data at or
  near the actual site and fine-tune the model on that terrain

This mirrors how the Australian team worked — but inverts the order: we build a general
model first, then specialise it for a particular location just before going out.

---

## The two distinct sub-problems

Two different computer vision tasks are both required for the full pipeline:

### Sub-problem 1: Feature recognition in reference photos
Identifying meteorite-specific features in photos of recovered specimens — museum shots,
field documentation, collector images, dealer photos.

**Input**: Photographs at any angle, lighting, and scale. Object typically occupies a
large portion of the frame.
**Goal**: Confirm the object is a meteorite; localise distinctive features.
**This project's current pipeline** uses this approach (YOLOv8 on ~86 annotated images).

### Sub-problem 2: Field detection in drone imagery
Identifying meteorite stones lying on the ground as seen from above by a drone.

**Input**: Top-down video frames or ortho-mosaic tiles at high resolution (~2mm/pixel target).
**Goal**: Binary classification of small image patches — "meteorite here" vs "ground only".
**This project plans to implement this** as a separate model and pipeline from the
feature-recognition detector.

These two sub-problems require different training data, different architectures, and
different annotation workflows. Progress on one does not automatically transfer to the other.

---

## Published approaches

### Anderson et al. (2020) — Foundational binary tile classifier
*"Machine learning for semi-automated meteorite recovery"*
*Meteoritics & Planetary Science*, 55, 2461–2471. DOI: 10.1111/maps.13593. arXiv: 2009.13852
Desert Fireball Network / Curtin University, Australia

The paper that established the tile-based binary CNN approach used by all subsequent
Curtin/DFN drone work.

**Setup**: Drone imagery from Western Australian fall sites. Meteorites appear 18–60 pixels
across in 42MP imagery. Images are sliced into 125×125 pixel tiles with a 70-pixel stride.

**Model**: Custom binary CNN in TensorFlow/Keras, trained **from scratch** (no ImageNet
pretraining). Each tile scores 0–1; threshold at ~0.7.

**Training data**: True (positive) tiles: physical meteorite stones placed at fall sites and
imaged from above, plus library stones. False (negative) tiles: terrain imagery from the same
sites. Data collected at multiple times of day to handle lighting variation.

**Results**: 75–97% detection rate across multiple Western Australian test sites.
Successfully identified 3 meteorites at native fall sites during field tests.

**Code/data released**: No.

---

### Anderson et al. (2022) — First successful real-world drone recovery
*"Successful Recovery of an Observed Meteorite Fall Using Drones and Machine Learning"*
*The Astrophysical Journal Letters*, 930(2). DOI: 10.3847/2041-8213/ac66d4. arXiv: 2203.01466
Desert Fireball Network / Curtin University, Australia

**Setup**: DJI M300 drone, Zenmuse P1 44MP camera, 1.8 mm/pixel, 20% image overlap.
At this resolution a 2–14 cm meteorite is 11–78 pixels across. Survey area: 5.1 km².

**Model**: Same binary Keras/TF CNN from Anderson 2020, trained on Nullarbor terrain.

**Training data**: ~100K True tiles from 28 meteorite stones (on-site + DFN library);
>1M False tiles from terrain imagery. Training strategy ("rotation training"): keep 80%
of the positive pool fixed, randomly sample an equal number of negatives each run, train
5 epochs, cycle through the false-positive pool twice. This manages the severe class
imbalance without overfitting.

**Results**: 99.93% training accuracy, 91% validation accuracy (recall). From 4 flights
(5,096 images, 46.5M tiles) → 59,384 candidates ≥0.7 score → 38 after two manual sorting
stages → 4 investigated in the field → **1 meteorite recovered** (70g chondrite, confidence 1.0).
Processing time: ~65 minutes per flight on a desktop with RTX 2080 Ti.

**Key limitation for this project**: Their training data is specific to Nullarbor Desert
terrain. A model trained on one ground type does not transfer well to a different one
(grassland, volcanic desert, dry lake bed, arctic tundra). Collecting domain-matched
negative examples is as important as collecting positive examples.

**Code/data released**: No.

---

### Citron et al. (2021) — Independent US approach with transfer learning
*"Recovery of Meteorites Using an Autonomous Drone and Machine Learning"*
*Meteoritics & Planetary Science*, 56, 1073+. DOI: 10.1111/maps.13663. arXiv: 2106.06523
SETI Institute, NASA Ames / Walker Lake, Nevada

The most architecturally relevant paper for this project. Unlike the Curtin/DFN approach,
Citron used **ImageNet-pretrained networks** (transfer learning) rather than training from
scratch.

**Setup**: Inexpensive off-the-shelf 3DR drone with GoPro Hero4, explicitly emphasising
low-cost accessibility. Test site: Walker Lake, Nevada dry lake bed.

**Model**: "A combination of different CNNs" — specifically **GoogLeNet and AlexNet**
pretrained on ImageNet, then fine-tuned on meteorite patch data.

**Training data**: 526 image patches of 8 meteorite fragments placed on local terrain and
photographed from above, plus internet-sourced meteorite images. Terrain diversity was
explicitly included.

**Results**: Proof-of-concept. System correctly identified test meteorites placed in the
Walker Lake dry lake bed. False positives included "rocks previously unidentified." No
specific precision/recall numbers published. No actual fallen meteorite was recovered
(they were testing methodology, not searching a strewn field).

**Key insight for this project**: Transfer learning from ImageNet means you need far fewer
meteorite images to get a working classifier. This is the right architecture direction for
our ~85 image starting point. Also the first paper to explicitly target terrain diversity
rather than one specific location.

**Code/data released**: No.

---

### Anderson et al. (2026) — Cloud-based tool (find.gfo.rocks)
*"A Cloud-Based Tool for Meteorite Recovery Using Drones and Machine Learning"*
arXiv: 2605.19179. Submitted May 2026.
Desert Fireball Network / Global Fireball Observatory, Curtin University

**What's new**: The DFN has turned their pipeline into a service at `find.gfo.rocks`,
running on ARDC Nectar Research Cloud with Pawsey Supercomputing Centre storage. Other
research groups can submit drone imagery and receive candidate lists back. Documented
results from multiple South and Western Australian falls, including the November 2025
recovery of the Dale meteorite (DFN's 11th recovered specimen, 3rd via drone). The Dale
recovery covered a 3×0.5 km area, generated 31,153 ML candidates, narrowed to 728 Stage 4
candidates after manual sorting.

**Access**: Available free to the research community upon request; commercial use requires
separate agreement. Not open-source.

**Relevance**: If we ever survey a confirmed strewn field, this tool could be used
alongside or instead of our own inference pipeline. It would not help with a speculative
general survey.

---

### Thoresen et al. (2024) — ESA Apollo rock thin-section classifier (HIGH RELEVANCE)
*"Breccia and basalt classification of thin sections of Apollo rocks with deep learning"*
arXiv: 2410.21024. GitHub: `github.com/esa/apollo_rock_thin_section_classifier`
European Space Agency

Not a meteorite detection paper, but the closest methodological analog to our situation:
**rare geological specimens, limited training data, classification between rock types**.

**Data**: 7,943 training images from 513 Apollo lunar rock samples (thin sections).
2,861 basalt + 5,082 breccia images — comparable in scale to our ~86 images.

**Model**: Inception-ResNet-v2 pretrained on ImageNet, then two-phase fine-tuning:
1. SimCLR self-supervised contrastive pretraining on augmented pairs (unlabeled data)
2. Supervised fine-tuning with frozen early layers

**Augmentation**: Random rotations, zoom ±20%, brightness/contrast/saturation/hue shifts,
Gaussian noise.

**Results**: Image-level accuracy 93.51%, sample-level 98.44%.

**Key insight**: SimCLR pretraining on *unlabeled* rock/terrain images can improve feature
representations before labeled training. This means images we collect of terrain (even
without meteorites) are useful for pretraining.

**Code released**: Yes — `github.com/esa/apollo_rock_thin_section_classifier`.

---

### Chen et al. (2023) — Rock image classification with transfer learning
*"Rock image classification using deep residual neural network with transfer learning"*
*Frontiers in Earth Science*, 11, 1079447. DOI: 10.3389/feart.2022.1079447

**Data**: Only 315 rock images across 7 classes (45 images/class — comparable to our
situation). After patch slicing: 27,386 images. After augmentation: 382,598 images.

**Model**: ResNet-34, pretrained on a Texture Library dataset (47 texture types, 78,960
images).

**Key finding**: Transfer learning improved accuracy from 88.1% to 99.1% — **+11
percentage points** over training from scratch. With small datasets, the pretrained
backbone is doing most of the work.

**Directly applicable technique**: Slice each source image into many patches, then
augment each patch heavily. 85 images → potentially thousands of training tiles.

---

## Available datasets

The situation for publicly available meteorite image datasets is poor. The DFN quote
sums it up well: *"Unlike cats, there is no large online database of nice meteorite pictures."*

| Dataset | Size | Type | License | Relevance |
|---|---|---|---|---|
| [MineralImage5k](https://datasetninja.com/mineral-image-5k) | 19,207 images; 151 in meteor split | Museum display shots only — no in-situ photos | MIT | Medium — feature recognition only, not drone survey |
| [NASA Meteorite Landings (Kaggle)](https://www.kaggle.com/datasets/nasa/meteorite-landings) | 45K+ entries | CSV metadata only, no images | Open | Low — no images |
| [NightSkyUCP (Sennlaub 2022)](https://doi.org/10.6084/m9.figshare.16451625) | 20,000 events | Video, atmospheric meteors (not ground stones) | Public | Low — wrong problem |
| Meteoritical Bulletin | ~80K entries | Some photos linked per entry | — | Medium — source for scraping |
| DFN internal library | ~100K+ positive tiles | Drone imagery from Australian falls | Not released | N/A |

**MineralImage5k** is worth integrating for feature recognition training. The 151-image
meteor split is all museum display shots — no in-situ field photos — so it will not help
with the drone survey tile classifier. The non-meteor splits are useful as hard negatives.
Download via `github.com/dataset-ninja/mineral-image-5k` (Hugging Face hosting is offline).
**This is an immediate actionable step for sub-problem 1.**

---

## Constraints and their implications

### Constraint 1: Minimal budget
- No money for high-end drone hardware, large cloud GPU runs, or commercial annotation.
- **Implication**: favour pre-trained backbone models, small architectures that train on
  consumer hardware, and free/public data sources. The Citron 2021 approach (inexpensive
  consumer drone + transfer learning) is the right model for our situation.

### Constraint 2: Very few training images (~86 images)
At 86 images the feature-recognition model (YOLOv8) is severely under-trained. Chen et al.
2023 showed a +11% accuracy boost from transfer learning vs. from-scratch training at this
scale, and that patch-slicing + augmentation can multiply a 315-image dataset to 382K tiles.

General guidance for object detection data requirements:
- < 100 images: model memorises, poor generalisation
- 300–500 images per class: reasonable generalisation begins
- 1,000–10,000 per class: competitive performance

The architecture is **not** the bottleneck. Acquiring more training data is.

### Constraint 3: Only one physical meteorite specimen
We have one real meteorite available for field data collection sessions. This is enough
for the tile classifier — see "Site-specific fine-tuning" below — but requires supplementation
with stand-in objects to avoid overfitting to a single specimen's exact shape and albedo.

---

## Strategies for the low-data regime

### A. Transfer learning from ImageNet (highest priority)
The Citron 2021 paper used GoogLeNet/AlexNet pretrained on ImageNet. Chen et al. 2023
showed +11% accuracy vs. from-scratch at comparable dataset sizes. For the tile
classifier, MobileNetV2, EfficientNet-B0, or ResNet-18 are good choices — lightweight,
well-supported, and strong ImageNet priors. Freeze most layers; fine-tune only the final
1–2 layers initially.

The current pipeline (YOLOv8 pretrained on COCO) already uses transfer learning. This is
correct. When we build the tile classifier, the same principle applies.

### B. Patch slicing + aggressive augmentation
Chen et al. 2023 turned 315 images into 382K tiles via patch slicing and augmentation.
The same technique is valid for our ~86 images:
- Slice each image into many 224×224 (or 125×125) patches with overlap
- Augment each patch: random flips, rotations (including 90°/180°/270°), zoom ±20%,
  brightness/contrast/hue shifts, Gaussian noise

For the drone tile classifier specifically, a 50MP drone image yields thousands of tiles —
even a single survey flight provides a large negative (background) dataset.

### C. Site-specific fine-tuning before an expedition
**This is the primary data collection strategy for the drone survey use case.**

Before a real survey, bring one or more meteorites (or stand-ins) to the survey location
or a representative terrain. Place them on the ground and fly the drone at survey altitude,
collecting video. This yields:

- **Domain-matched positives**: real specimens on real terrain, from drone altitude
- **Domain-matched negatives**: all the surrounding frames showing only ground

**One specimen is sufficient for this step**, because what the model needs to learn is
what THIS ground looks like with an anomaly on it. The variability required is in the
*background*, not the object. Place the specimen at 20 different spots, with different
orientations, at different distances within the frame, and film at two times of day
(morning and afternoon shadows differ significantly). This yields hundreds of usable tiles
from a single session.

**Supplementing one specimen with stand-ins**: To avoid overfitting to the exact shape and
albedo of our one meteorite, supplement with:
- **Dark angular basalt or obsidian rocks** — share surface texture and dark colour
- **Slag / industrial waste** — common meteorwrong candidates; training the model to flag
  and then reject these in post-processing is correct behaviour
- **Spray-painted rocks** — a coat of flat black paint simulates fusion crust on any
  rock shape; a technique used explicitly in some published work

**Practical checklist for a field collection session**:
- Fly at the same altitude you plan to use for the actual survey (~30–50m AGL)
- Use the same camera and settings as the real survey
- Place specimens at multiple locations, orientations, and depths in frame
- Collect at multiple sun angles if possible (morning vs. afternoon)
- Film plenty of bare ground too — negatives are as important as positives
- Note GPS coordinates where specimens were placed (validates post-processing)

### D. Sourcing more real reference data
For sub-problem 1 (feature recognition), the most reliable improvement is more annotated
images. Sources:

- **Meteoritical Bulletin** (already scraped) — ~80K entries, most with photos
- **MineralImage5k** — 19,207 MIT-licensed mineral photos including some meteorites;
  immediately available, no scraping required (evaluated - contains no in-situ images)
- **Meteorite dealers** — Dealers often have large unpublished photo archives and may
  share for research purposes; worth asking directly
- **Meteorite hunting communities** — r/meteorites, MetSoc forums, Facebook groups
- **Museums** — NHM London, Smithsonian, Field Museum have meteorite photo collections

Priority: in-situ images (meteorite on ground before recovery) are rarest and most
valuable for the drone survey model. Museum/hand photos are useful for feature recognition.

### E. SimCLR self-supervised pretraining
The ESA Apollo paper (Thoresen 2024) used SimCLR contrastive pretraining on *unlabeled*
images before fine-tuning the classifier. This means drone survey footage or terrain
images (no annotation needed) can improve the feature backbone. Any video we collect
of candidate terrain — even before we have a meteorite to place in it — is useful training
material for this step.

### F. Semi-supervised / active learning (already in place)
The current `auto_annotate.py → Label Studio review` loop is a form of active learning:
the model pre-labels images, a human corrects predictions, corrected annotations re-enter
training. This is the right approach for growing a dataset efficiently when labelling time
is the bottleneck. Each correction improves the model faster than annotating a fresh image
from scratch.

### G. MineralImage5k as supplementary data
19,207 mineral specimen images, MIT licensed. The "10_meteor" split contains 151 images,
all museum display shots of meteorite specimens — **no in-situ field photos**. Useful for:
- Feature recognition training (sub-problem 1): mix the 151 meteor images into the training set
- Hard negatives: the non-meteor splits contain visually similar rocks

Not useful for the drone survey tile classifier (sub-problem 2) — wrong camera angle and
background entirely. Download via `github.com/dataset-ninja/mineral-image-5k`.

---

## Architecture comparison

| Architecture | Task | Data needed | Notes |
|---|---|---|---|
| YOLOv8n/s (current) | Feature detection | 500+ images | Good default; bounding-box output |
| Binary CNN tile classifier | Drone survey | 50K+ tiles | Anderson/DFN approach; fast inference |
| MobileNetV2 / EfficientNet-B0 | Binary tile classifier | 1K+ tiles w/ TL | Better for low-data than custom CNN from scratch |
| ResNet-18/34 + ImageNet | Binary tile classifier | 1K+ tiles | Chen et al. approach; strong low-data baseline |
| Inception-ResNet-v2 + SimCLR | Tile classifier | Unlabeled terrain + few labeled | ESA Apollo approach; highest accuracy at low data |
| Grounding DINO | Feature detection | 0 (text prompt) | Zero-shot baseline — detect "meteorite" without training |
| DINO v2 / SAM features | Few-shot detection | ~10 examples | Promising; no fine-tuning needed |

**Near-term recommendation**: Stay on YOLOv8s for feature recognition and focus on growing
the dataset to 300–500 annotated images. For the drone tile classifier, use an ImageNet-
pretrained MobileNetV2 or EfficientNet-B0 fine-tuned on tiles (following Citron 2021 and
Chen 2023 rather than the DFN's from-scratch CNN).

---

## Recommended next steps (priority order)

1. **Run the scraper more aggressively** — target 500+ images in the DB from the
   Meteoritical Bulletin alone.

2. **Download and integrate MineralImage5k** — MIT license, immediate, provides both
   additional positive examples (meteor split) and hard negatives.

3. **Sort the existing ~86 images** — tag each as `in_situ`, `studio`, `hand`,
   `thin_section` in the Streamlit app. This determines what we actually have and
   unblocks the scene classifier.

4. **Run a proper training session** once 300+ images are annotated:
   ```powershell
   python scripts/train_model.py --epochs 100 --model yolov8s.pt --clean
   ```

5. **Plan a field data collection session** — even before a real survey, bring the
   meteorite to any open terrain and collect drone footage for future tile classifier
   training. No model training needed yet; just collect and store the raw video.

6. **Build the tile classifier** (once field footage exists) — follow Citron 2021 /
   Chen 2023: ImageNet-pretrained MobileNetV2 or EfficientNet-B0, patch-sliced tiles,
   aggressive augmentation, binary cross-entropy loss with class weighting.

7. **Evaluate Grounding DINO** as a zero-shot baseline for feature recognition — may
   detect fusion crust / meteorite body from text prompts with no training data.

---

## Hardware: DJI Mavic Pro

The drone available for field surveys is a **DJI Mavic Pro** with a 12MP (4000×3000)
1/2.3" CMOS sensor, 78.8° FOV, f/2.2 fixed lens.

### Ground resolution at survey altitudes

| Altitude (AGL) | GSD (mm/px) | 5cm meteorite | 10cm meteorite | 20cm meteorite | Coverage per frame |
|---|---|---|---|---|---|
| 10m | ~2.5 | ~20px ✓ | ~40px ✓ | ~80px ✓ | ~14m × 10m |
| 15m | ~4 | ~12px ✓ | ~25px ✓ | ~50px ✓ | ~21m × 15m |
| 20m | ~5.5 | ~9px ⚠ | ~18px ✓ | ~36px ✓ | ~28m × 21m |
| 30m | ~8 | ~6px ✗ | ~12px ⚠ | ~25px ✓ | ~42m × 31m |
| 50m | ~13 | ~4px ✗ | ~8px ✗ | ~15px ⚠ | ~70m × 52m |

✓ = reliably detectable  ⚠ = marginal  ✗ = likely too small

**Comparison**: The Australian team's 44MP Zenmuse P1 achieved 1.8mm/pixel at survey
altitude. To match that resolution the Mavic Pro would need to fly at ~7m AGL —
impractically low and risky. The practical minimum detectable size with the Mavic Pro
is approximately **5cm at 15m AGL**.

### Implications for survey planning

- **Recommended survey altitude**: 15–20m AGL — best balance of coverage vs. resolution.
  Lower (10m) gives better detection but covers very little ground per flight battery.
- **Coverage per battery**: The Mavic Pro has ~27 min flight time. At 15m AGL with 80%
  side overlap and 3 m/s speed, a single battery covers roughly 1–2 hectares (0.01–0.02 km²).
  The Australian team covered 5.1 km² total — roughly 250–500× more area per flight.
- **Tile size adjustment**: At 15m AGL (~4mm/px), a 125×125 tile covers 50cm × 50cm of
  ground. A 64×64 tile covers 25cm × 25cm — keeping physical tile coverage similar to the
  Australian approach. The tile size used during training must match tile size used during
  inference.
- **Video vs. stills**: At low altitude, continuous video (4K at 30fps) may be more
  practical than an overlap-mosaic of stills. Each video frame becomes a source of survey
  tiles. At 3 m/s flight speed, frames overlap significantly even without a dedicated
  mapping flight pattern.
- **Detection limit**: A 5cm stone at 15m AGL appears as ~12px across. At 20m it's ~9px —
  below the threshold used in Anderson 2020 (minimum ~11px at 1.8mm/px). Plan surveys
  for stones ≥5–8cm; smaller finds may be missed regardless of model quality.

---

## Open questions

- How frequently do we intend to survey, and in what terrain types? Each new terrain type
  ideally gets its own field data collection session.
- Are there meteorite recovery groups (DFN, SETI, meteorite hunters) willing to share
  unlabelled field photos that we could use for pretraining?

---

## References

- Anderson et al. (2020). Machine learning for semi-automated meteorite recovery.
  *Meteoritics & Planetary Science*, 55, 2461–2471. DOI: 10.1111/maps.13593. arXiv: 2009.13852
- Anderson et al. (2022). Successful recovery of an observed meteorite fall using drones
  and machine learning. *ApJL*, 930(2). DOI: 10.3847/2041-8213/ac66d4. arXiv: 2203.01466
- Anderson et al. (2026). A cloud-based tool for meteorite recovery using drones and
  machine learning. arXiv: 2605.19179
- Citron et al. (2021). Recovery of meteorites using an autonomous drone and machine
  learning. *Meteoritics & Planetary Science*, 56, 1073+. DOI: 10.1111/maps.13663. arXiv: 2106.06523
- Thoresen et al. (2024). Breccia and basalt classification of thin sections of Apollo
  rocks with deep learning. arXiv: 2410.21024. Code: github.com/esa/apollo_rock_thin_section_classifier
- Chen et al. (2023). Rock image classification using deep residual neural network with
  transfer learning. *Frontiers in Earth Science*, 11, 1079447. DOI: 10.3389/feart.2022.1079447
- Nesteruk et al. (2023). MineralImage5k: A benchmark for zero-shot raw mineral visual
  recognition and description. *Computers & Geosciences*, 178, 105414
- Sennlaub et al. (2022). Object classification on video data of meteors and meteor-like
  phenomena: algorithm and data. *MNRAS*, 489(4), 5109. arXiv: 2208.14914
