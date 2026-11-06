# Local model on the GPU — the exact sequence

Target: `nomic-embed-text` (768-d, ~274 MB) serving `cli index` on the RTX 3060 Mobile,
with the planner (`llama3.2`) optional on top. Everything runs on this machine; no key,
no per-call cost, no network at query time.

The code is already wired: `retrieval/hybrid.py::_embed` sends `num_gpu=-1` and
`keep_alive=30m`, and rejects any embedding that is not 768-d instead of silently
corrupting the index. `cli index` prints `{"embedded": true|false}` — that flag is the
whole acceptance test.

## 1. Driver (this is the blocker today)

```sh
ubuntu-drivers devices | grep -A2 recommended          # expect nvidia-driver-595-open
sudo ubuntu-drivers autoinstall                        # or: sudo apt install nvidia-driver-595-open
sudo reboot
```

After the reboot:

```sh
nvidia-smi                       # must print the GA106M / RTX 3060, not "couldn't communicate"
ls /dev/nvidia*                  # must list devices
```

If `nvidia-smi` still fails, the module is not loading for this kernel:

```sh
uname -r; dkms status; modinfo nvidia | head -3
sudo apt install --reinstall linux-modules-nvidia-595-$(uname -r)
```

`prime-select` says `on-demand`. That is fine for CUDA compute: the dGPU powers up on
first use instead of driving the display. If it stays asleep, force the profile for the
session with `__NV_PRIME_RENDER_OFFLOAD=1 __GLX_VENDOR_LIBRARY_NAME=nvidia`.

## 2. Ollama

```sh
curl -fsSL https://ollama.com/install.sh | sh     # installs the systemd unit
sudo systemctl enable --now ollama
ollama pull nomic-embed-text
ollama pull llama3.2                              # optional: planner instead of the keyword fallback
```

Check that the model actually lands on the card, not in RAM:

```sh
ollama run nomic-embed-text "warm up" >/dev/null
ollama ps          # PROCESSOR must read 100% GPU
```

If it says CPU: the driver step is incomplete, or VRAM is claimed by something else
(`nvidia-smi` shows per-process usage). A 6 GB laptop sharing VRAM with the desktop can
still hold a 274 MB embedding model; a 4 GB planner next to it is what squeezes.

## 3. Environment

```sh
export OLLAMA_HOST=http://localhost:11434
export OLLAMA_EMBED_MODEL=nomic-embed-text
export OLLAMA_NUM_GPU=-1          # every layer on the GPU
export OLLAMA_KEEP_ALIVE=30m      # keep it resident during the demo
```

Nothing else needs configuring: the 768-d vector index already exists in
`schema.cypher`, and the query path picks vectors up automatically once chunks carry
`embedding`.

## 4. Prove it

```sh
make index        # expect {"chunks": N, "embedded": true}
make test         # 72 tests, unaffected by the model
make rehearse     # 12 checks; the index line must say embedded=true
```

Then confirm the vector index is populated, not just the text one:

```sh
docker exec northstar-neo4j cypher-shell -u neo4j -p northstar \
  "CALL db.index.vector.queryNodes('chunk_embedding', 3, \$v) YIELD node, score
   RETURN node.id AS id, score" --param 'v=[0.0,…768 values…]'
```

Cheaper equivalent: ask something with no identifier in it. With vectors on, the answer
or its `gaps` names real evidence candidates; with vectors off, it falls back to BM25 and
the same question usually returns nothing.

## 5. What changes and what does not

| With the model | Behaviour |
|---|---|
| Index time | one embed call per chunk (~1800 chunks for the corpus), once |
| Query time | one embed call per question, ~10–30 ms on GPU, then HNSW |
| Failure | `embedded:false`, BM25 still answers — the demo never depends on the model |
| Token cost | zero; the model is local |

The planner uses `OLLAMA_MODEL` (default `llama3.2`) when it is reachable and falls back
to the deterministic keyword planner otherwise. Both paths are tested; the fallback is
what runs today.

## 6. Known limits, said out loud

- One laptop, one GPU: this is not a serving architecture. Concurrency is Ollama's.
- Embedding model and dimension are pinned (768). Changing either is a re-index and a
  `schema.cypher` edit, not a config toggle.
- The model never sees retrieved text, only the user's question and the ontology digest —
  the planner prompt is deliberately blind to corpus content (AGENTS invariant 3).
- Nothing on the GPU path is measured on this machine yet: the driver is absent, so the
  latency numbers in `docs/09-evaluation.md` remain local-CPU/BM25 numbers.
