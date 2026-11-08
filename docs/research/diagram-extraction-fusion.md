# Diagram extraction: state of the art and a weighted-fusion design

Research brief, 2026-11-08. Scope: unattended extraction from raster diagrams (flowchart,
architecture, ERD, sequence) at collection scale. **[OBSERVED]** = read in the linked source;
**[INFERRED]** = this brief's design inference.

---

## 1. How real systems do it

| System | Input | Method | VLM? | Licence | Accuracy |
|---|---|---|---|---|---|
| [Docling](https://github.com/docling-project/docling) | PDF, PNG | DocLayNet layout → reading order → TableFormer; EasyOCR ([report](https://arxiv.org/abs/2408.09869)) | Optional (pictures, charts) | MIT ([README](https://github.com/docling-project/docling#license)) | DocLayNet baselines mAP 72.4–76.8, human 82–83 ([DocLayNet](https://arxiv.org/abs/2206.01062)); 1.27–2.45 pages/s CPU |
| [Marker](https://github.com/datalab-to/marker) | PDF, image, Office | Layout + text layer/OCR + equations; `--use_llm` hybrid | Optional LLM | Apache-2.0 code; weights OpenRAIL-M, free under $5M ([README](https://github.com/datalab-to/marker#commercial-usage)) | olmocr-bench 76.0%, 83.5% born-digital |
| [MinerU](https://github.com/opendatalab/MinerU) | PDF, scans | Pipeline tiers (OCR + layout + table/formula) or VLM tier ([docs](https://github.com/opendatalab/MinerU/blob/master/docs/en/index.md)) | Optional | Apache-2.0 **plus** terms: >100M MAU or >$20M revenue needs a commercial licence ([LICENSE](https://github.com/opendatalab/MinerU/blob/master/LICENSE.md)) | OmniDocBench text edit distance 0.206, best pipeline there ([OmniDocBench](https://arxiv.org/abs/2412.07626)) |
| [Unstructured](https://github.com/Unstructured-IO/unstructured) | PDF, image, Office | YOLOX/Detectron2 layout + OCR ([inference](https://github.com/Unstructured-IO/unstructured-inference)) | No | Apache-2.0 | OSS 0.715 text / 0.426 table cell vs 0.878 / 0.866 paid; vendor-reported, different benchmarks |
| [PaddleOCR / PP-StructureV3](https://github.com/PaddlePaddle/PaddleOCR) | image, PDF | Seven modules: layout, OCR, table, formula, seal, chart | No for text; **yes** for charts | Apache-2.0 | Calls keypoint chart pipelines "lack robustness" ([docs](https://github.com/PaddlePaddle/PaddleOCR/blob/main/docs/version3.x/module_usage/chart_parsing.en.md)) |
| [DocLayout-YOLO](https://github.com/opendatalab/DocLayout-YOLO) | page image | YOLOv10 detector, synthetic DocSynth-300K | No | AGPL-3.0 | Detector component in MinerU-lineage tools |
| [LayoutLMv3](https://arxiv.org/abs/2204.08387) | page + OCR boxes | Joint text/layout/image transformer (early fusion) | Multimodal | MIT code; **weights CC-BY-NC-SA-4.0** ([HF](https://huggingface.co/microsoft/layoutlmv3-base)) | FUNSD F1 92.08; PubLayNet mAP 95.1 (base) |
| [DePlot](https://arxiv.org/abs/2212.10505) / [MatCha](https://arxiv.org/abs/2212.09662) | chart image | Pix2Struct (282M) plot→linearised table, then LLM | Yes | Apache-2.0 ([repo](https://github.com/google-research/google-research)) | PlotQA RNSS 97.1 / RMSF1 94.2 vs ChartOCR 81.0 / 60.1; ChartQA human 38.2 (MatCha) |
| [TRACE](https://aclanthology.org/2026.emnlp-main.1704.pdf) | flowchart | Arrowhead detector → one VLM query per arrowhead → triplet; OCR vocabulary repair | Yes | Not stated in paper | F1 93.77 (FlowVQA), 63.91 (hand-drawn FC_A) |
| [FlowExtract](https://arxiv.org/pdf/2604.06770) | ISO 5807 flowchart | YOLOv8 nodes + EasyOCR + arrowhead orientation + backward line trace | No | MIT ([repo](https://github.com/aixpert-rug/FlowExtract)) | Node F1 98.8; edge F1 66.7 (P 85.5 / R 54.6) |
| [TextFlow](https://aclanthology.org/2025.naacl-long.180.pdf) | flowchart | Graph → Graphviz/Mermaid text → LLM reasons | Extraction yes | MIT ([repo](https://github.com/NJIT-AI-Center/TextFlow)) | 88.23% (GPT-4o, Graphviz, tool-assisted, gold graph) |
| [BPMN-VLM](https://arxiv.org/pdf/2511.22448v1) | BPMN image | Prompted VLM ± OCR enrichment | Yes | No licence stated ([repo](https://github.com/pritamdeka/BPMN-VLM)) | Name F1 0.817; relations+types ≤0.475 |
| [Digitize-PID](https://arxiv.org/pdf/2109.03794) / ChartOCR | P&ID, charts | Morphology/Hough lines + symbols + OCR + keypoints | No | Not stated | Lines: complete 99.34%, **dashed 82.91%**; keypoint tables RMSF1 60.1 |
| [Azure Document Intelligence](https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/prebuilt/layout) | PDF, image | Layout model emits figure polygons + `FigureContent` | No | Proprietary | Figure **regions only**, no semantics |

Two patterns: every commercial product here stops at *finding* the figure — "Picture" is
DocLayNet's weakest class (models mAP 71.7–77.1, human 69–71) — while the systems that extract
*structure* separate perception from topology, because end-to-end VLMs fail there: across 13,858
flowcharts, edge F1 of GPT-4V, Claude-3, Gemini-Pro, LLaVA, Qwen-VL, InternLM and DeepSeek stayed
**below 0.30** ([FlowExtract §1](https://arxiv.org/pdf/2604.06770), summarising that benchmark).
No verifiable "DagDiagram" project exists (GitHub search: 0 results); graph-to-text NLG
([e.g.](https://arxiv.org/abs/2209.07258)) consumes an already-parsed graph and adds no vision.

---

## 2. Fusion strategy with weights

Everything here is **[INFERRED]**: weights and thresholds are priors to tune on the six fixtures,
not published numbers; cited systems fix only the *shape* of the fusion.

Signals, each independently extractable from one PNG:

- **S1 OCR tokens** — `(text, bbox, conf)` (Tesseract `image_to_data`, PaddleOCR).
- **S2 boxes** — `(class, bbox, score)` from a detector.
- **S3 segments** — Hough-P or skeleton lines, gap ratio separating solid from dashed.
- **S4 arrowheads** — `(bbox, tip, orientation)`.
- **S5 label** — OCR tokens clustered by box containment and proximity.
- **S6 order** — reading order (topological for flowcharts; x for lifelines, y for messages).
- **S7 VLM triplets** — optional, hypotheses only.

**Fusion levels** — the part published systems mostly skip:

| Level | Inputs | Rule |
|---|---|---|
| Character | S1 from ≥2 OCR configs | ROVER alignment vote ([NIST](https://www.nist.gov/publications/post-processing-system-yield-reduced-word-error-rates-recognizer-output-voting-error)); multi-stream voting cut CER 44% (0.0234→0.01317), 70% with post-processing ([LV-ROVER](https://arxiv.org/html/2607.00250v2)) |
| Label | S1×2, S5, resolver, S7 | weighted similarity vote |
| Edge | S3, S4, S2 anchoring, S7 | geometric vote; **never** text |
| Graph | all | schema filter only, never edge generation |

Label vote, with `sim(a,b) = 1 − lev(a,b)/max(|a|,|b|)`:

```
score(s) = Σ_i w_i·a_i·sim(s, s_i) / Σ_i w_i·a_i
accept if best ≥ 0.60 and (best − second) ≥ 0.15, else emit label_alternatives
```

Edge vote for `e = (u,v)`, `a_i ∈ {0, 0.5, 1}`:

```
a_box   endpoints within τ_box of the two box boundaries
a_arrow exactly one endpoint carries an arrowhead whose tip is within τ_tip
        and whose orientation is within 30° of the segment direction
a_line  run covers ≥95% of the span (gap ratio ≤0.2)
a_vlm   1 if S7 asserts (u,v), 0 if it contradicts, 0.5 if silent

conf(e) = Σ w_i·a_i / Σ w_i,  w = {box .30, arrow .30, line .25, vlm .15}
```

Hard rule: `a_arrow = 0` or `a_box = 0` demotes the edge to `needs_review` at `conf × 0.4`; it
never becomes a FACT. This is TRACE's grounding constraint written as a weight: TRACE requires
each triplet to be grounded to a *detected* arrowhead, and swapping the detector (SAM 3 vs
YOLOv11) moves F1 <1 pp while the paradigm moves it ~23 pp ([TRACE](https://aclanthology.org/2026.emnlp-main.1704.pdf)).

`a_i` are ternary, so `conf(e)` is an **ordinal** band (`≥0.85`, `0.6–0.85`, `<0.6`), not a
probability — six diagrams cannot support an isotonic fit. Keep weights versioned like
`extractor_version` ([ADR-0012](../adr/0012-diagram-evidence.md)).

Elsewhere: TRACE fuses at anchor level plus OCR-vocabulary repair; FlowExtract fuses two geometric
signals, no text; LayoutLMv3 fuses at representation level. **Not** fused: Docling, Marker,
Unstructured and PP-StructureV3 are sequential chains where later stages trust earlier ones
([Docling report](https://arxiv.org/abs/2408.09869)); DePlot, MatCha and PP-Chart2Table trust one
model. Naive fusion can hurt: OCR in a strong VLM prompt dropped GPT-4.1 name F1 0.807→0.775 while
mid-tier models gained 3–5 F1 ([BPMN-VLM](https://arxiv.org/pdf/2511.22448v1)) — hence weighted,
margin-gated voting.

---

## 3. Self-check without a human

All seven need no ground truth and only `difflib`, `statistics`, `math` and rectangle arithmetic.
The quantities are computable as stated; cut-offs are [INFERRED] priors.

1. **Cross-method disagreement** — per node `sim(ocr, vlm)`; median and share below 0.85 (TRACE's
   relaxed-F1 threshold). High share = two readers saw different diagrams.
2. **OCR confidence distribution** — share of words `conf < 60`, mean and p10 per diagram.
3. **Label-to-box containment** — `area(tokens ∩ boxes)/area(tokens)`; the remainder is caption or
   a missed box.
4. **Connector anchoring** — share of segment endpoints within `τ_box` of a box; share of
   arrowheads with no segment tip within `τ_tip` (FlowExtract's recall ceiling).
5. **Topology consistency** — edge/node density, isolated nodes, self-loops, duplicates, cycles
   where a DAG is expected (DFS/union-find).
6. **Label resolvability** — share of labels the ontology resolver matches; unknown-label rate
   tracks OCR corruption (already measured: `customerId` → `customerld`,
   [ADR-0012](../adr/0012-diagram-evidence.md)).
7. **Reproducibility** — identical config twice must be byte-identical; the same ADR measured
   8/40 lines drifting between Tesseract 5.5.0 and 5.5.3.

(1) plus (4) catch the dangerous case — confident but wrong: invented edges fail anchoring, mangled
labels fail disagreement. None proves correctness; together they detect *broken extraction*.
[INFERRED]

---

## 4. Honest limits

**Hand-drawn.** TRACE falls from 93.77 F1 on computerised FlowVQA to 63.91 on hand-drawn FC_A
(≈30 pp); on FC_A node errors are 42.0% of all errors vs 10.0% overall — reading fails, not
reasoning. Fixed-vocabulary CV baselines collapse to 2.46 / 2.60 F1 on the two hand-drawn sets.
[OBSERVED, [TRACE](https://aclanthology.org/2026.emnlp-main.1704.pdf)]

**Dashed.** Digitize-PID measures 99.34% on complete lines but **82.91%** on dashed ones, and calls
Hough detection parameter-dependent and weak on noise. On dashed curves Mask R-CNN reaches bAP50
71.2 (finds boxes) yet mAP50 **2.0** (cannot extract); LETR tops out at sAP5 14.4 vs 23.1.
[OBSERVED, [Digitize-PID](https://arxiv.org/pdf/2109.03794),
[CVPR'22](https://openaccess.thecvf.com/content/CVPR2022/papers/Liu_Neural_Recognition_of_Dashed_Curves_With_Gestalt_Law_of_Continuity_CVPR_2022_paper.pdf)]

**Handwriting.** OmniDocBench edit distance on handwritten Notes is 0.651 (Marker) and 0.984
(MinerU, which "detects all handwritten notes as figures") against 0.055–0.131 on books.
[OBSERVED, [OmniDocBench](https://arxiv.org/abs/2412.07626)]

**Topology and direction.** VLM edge F1 below 0.30 on 13,858 flowcharts; FlowExtract's own VLM
baselines score 0.107 and 0.015. BPMN relations+types never exceed 0.475. On printed sequence
diagrams the best model inserts 13.0% and deletes 15.8% of nodes, with 12.7%/15.4% on direction
changes and ~13% on messages; only participants are reliable (0.72%/2.88%). [OBSERVED,
[FlowExtract](https://arxiv.org/pdf/2604.06770), [BPMN-VLM](https://arxiv.org/pdf/2511.22448v1),
[UML-sequence](https://arxiv.org/pdf/2509.11667)]

**Arrowheads cap everything.** FlowExtract detects arrowheads at 73.1%, capping edge recall at
54.6%; TRACE blames small or occluded arrowheads, with residual errors of 10.4% wrong direction
and 27.4% missing triplets. [OBSERVED, both]

**Implication.** [INFERRED] For printed box-and-line diagrams expect roughly 0.6–0.8 F1 with the
§2 weights; for hand-drawn or dashed, ≈0.6 or worse; for handwritten annotations, text extraction
fails outright. Diagram output must therefore ship as region-cited, confidence-banded evidence —
the stance [ADR-0012](../adr/0012-diagram-evidence.md) already takes, now with numbers behind it.
