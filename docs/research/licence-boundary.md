# Licence, size and separability — diagram OCR and geometry

Measured 2026-11-08 on Ubuntu 24.04, Python 3.12.3, wheels from PyPI the same day.
`[M]` means read out of the artefact (wheel `dist-info/licenses`, SBOM, `readelf -d`,
`/proc/self/maps`, `dpkg-query`, live import); `[D]` means publisher or Debian metadata,
not confirmed on the binary. Sizes are one linux amd64 wheel, installed, no models.

Summary of the full report; the numbers below are the ones the decision rests on.

## The finding that changes the design

`tesserocr`'s manylinux wheel **vendors jbigkit 2.1 — GPL-2.0-or-later — as
`tesserocr.libs/libjbig-*.so.2.1`** `[M]`. It is reached
`libtesseract → libleptonica → libtiff → libjbig` and is **mapped at `import` time, not
only when a JBIG/TIFF image is read** `[M]`. Deleting the `.so` breaks the import `[M]`;
`apt`'s `libtiff6` hard-depends on `libjbig0` `[M]`. The wheel ships no GPL-2 text and no
source offer `[M]`.

So "opt-in GPL" for tesseract means *a GPL library in the venv whenever the extra is
installed*, which is acceptable only behind the consent gate — and unnecessary, because a
clean default exists.

## Candidates (licence + installed size)

| candidate | licence | > MPL copyleft? | installed |
|---|---|---|---|
| `tesserocr` 2.12.0 wheel | MIT wrapper; tesseract Apache-2.0; leptonica BSD-2; libtiff BSD-like; **jbigkit GPL-2.0-or-later** | **yes, GPL-2.0+** | 33.3 MiB |
| `tesseract-ocr` apt 5.3.4 | Apache-2.0 + libtiff→libjbig0 GPL-2+; cairo/pango LGPL-2.1 | **yes, GPL-2.0+** | ~120 MiB with deps |
| `rapidocr` 3.10.0 | Apache-2.0, PP-OCRv6 small ONNX **bundled** (9.5+21.2+0.6 MB) | **no** — LGPL-2.1 only via GEOS | 30.9 MiB |
| `rapidocr-onnxruntime` 1.4.4 | Apache-2.0 but depends on **non-headless** opencv → Qt5 LGPL-3.0 | LGPL-3.0 | 15.5 MiB |
| `paddleocr` + `paddlepaddle` | Apache-2.0 wrapper; **Intel MKL ML + iomp5 proprietary, terms not shipped** | proprietary binaries | 687 MiB |
| `easyocr` / `doctr` / `surya` / `pix2text` | Apache-2.0/MIT wrappers over `torch` (1091.6 MiB, NVIDIA CUDA redistributables, terms not in the wheel) | not acceptable | — |
| `PyMuPDF` | **AGPL-3.0** or commercial | yes, AGPL | 110.3 MiB |
| `Pillow` 13.0.0 | MIT-CMU; SBOM declares `libimagequant` GPL-3.0 as **optional and not linked** (`0 liq_` symbols) `[M]`; real FriBiDi not linked `[M]` | **no** | 19.5 MiB |
| `opencv-python-headless` | MIT wrapper + OpenCV Apache-2.0; **FFmpeg LGPL-2.1** in `*.libs/`, verified not a GPL build `[M]` | LGPL-2.1 | 135.4–143.3 MiB |
| `opencv-python` (non-headless) | as above **+ Qt5 LGPL-3.0** | LGPL-3.0 | 180.7 MiB |
| `numpy` / `scipy` / `scikit-image` / `networkx` / `onnxruntime` / `shapely` | BSD/MIT/Apache; `libgfortran`/`libquadmath` **GPL-3.0+ WITH GCC Runtime Library Exception**; GEOS LGPL-2.1 | exception permits any linking | 53.8 / 106.8 / 28.3 / 7.0 / 61.5 / 7.4 MiB |

There is **no pure-Python OCR engine**: every candidate is a wrapper over a native core.

## Recommendation implemented in ADR-0012

**Default (ungated, no GPL anywhere):** `rapidocr>=3.10,<4` + `onnxruntime` +
`opencv-python-headless` + `numpy` + `pillow` + `networkx` — **≈325 MiB**, weak copyleft
only (FFmpeg and GEOS, LGPL-2.1, dynamic, unmodified, in the wheels' own `*.libs/`
directories). One dependency set serves both OCR and geometry, because `rapidocr` already
requires headless OpenCV `[M]`.

**Opt-in (`diagram-tesseract` extra):** `tesserocr>=2.12` + `tesseract-ocr-eng` tessdata,
≈37.2 MiB, GPL-2.0-or-later, behind `ingest/optin.py` (ADR-0013).

**Rejected:** torch-family OCR (1.1 GiB, NVIDIA terms unverifiable), paddle (proprietary
Intel binaries), PyMuPDF (AGPL), non-headless OpenCV (Qt5 LGPL-3.0, dead weight on a
server), and building leptonica with `-DENABLE_TIFF=OFF` (the only zero-copyleft-at-all
route; costs a compiler stage, more than this build should pay).

## Obligations

- `THIRD_PARTY_NOTICES.md` must name FFmpeg, GEOS, the GCC runtime exception and OpenCV's
  own third-party file; when the tesseract extra is installed it must append jbigkit with
  the GPL-2 text and a written offer, because the wheel ships neither.
- A wheel's SBOM is not its linkage: `libimagequant` and real FriBiDi appear in Pillow's
  SBOM and are not linked. Check symbols, not manifests.
