# Third-party notices

Only the components that carry an obligation beyond "retain the licence" are listed; the
full texts ship inside each wheel's `dist-info/licenses/` directory.

**Status: declared, not installed.** The shipped default install (`pyproject.toml`
`dependencies`) contains none of the components below. They arrive only when an optional
extra is installed — `pip install -e '.[diagram]'` for the zero-GPL reader and geometry set,
`pip install -e '.[diagram-tesseract]'` for the GPL reader. Nothing here is installed today.

`diagram` extra (LGPL-2.1 only):

| component | licence | where | obligation |
|---|---|---|---|
| FFmpeg libraries | LGPL-2.1-or-later | `opencv_python_headless.libs/libav*.so` | dynamic, unmodified, separate files: notice retained here and in OpenCV's own third-party file |
| GEOS | LGPL-2.1-or-later | `shapely.libs/libgeos*.so` | as above |
| GCC runtime (`libgfortran`, `libquadmath`, `libgomp`) | GPL-3.0-or-later **WITH GCC Runtime Library Exception** | `numpy.libs/`, `opencv_python_headless.libs/` | the exception permits distribution under any terms; stated here because the wheels do not ship it |
| OpenCV | Apache-2.0 | `cv2/` | retain `cv2/LICENSE-3RD-PARTY.txt` verbatim |
| Pillow | MIT-CMU | `PIL/` | retain the SBOM's licence list |
| onnxruntime | MIT | `onnxruntime/` | none beyond the text |

`diagram-tesseract` extra (GPL-2.0-or-later), appended when that extra is installed:

| component | licence | where | obligation |
|---|---|---|---|
| jbigkit 2.1 | **GPL-2.0-or-later** | `tesserocr.libs/libjbig-*.so.2.1`, mapped at `import tesserocr` | **the wheel ships neither the GPL-2 text nor a source offer**: redistribute only with both, or do not redistribute the environment |

Nothing here is legal advice. The measurement behind each row, and the reasoning for
keeping the GPL component in its own extra, is in
[docs/research/licence-boundary.md](../docs/research/licence-boundary.md) and
[docs/adr/0013-opt-in-capabilities.md](../docs/adr/0013-opt-in-capabilities.md).
