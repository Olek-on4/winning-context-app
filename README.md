# winning-context-app

Solution for the AT&T Context Service hackathon. Builds an evidence-backed Context Service on top of the [Northstar Equipment](https://github.com/arkik7/att-hackathon-task) corpus (twelve apps, docs, wiki, meeting notes, incidents, API specs, diagrams).

The corpus lives in `vendor/att-hackathon-task` as a git submodule and is the only source of input data. Everything in this repository is our own code.

## Layout

```
.
├── apps/                     our Context Service implementation (language TBD)
├── vendor/att-hackathon-task corpus submodule, read-only
├── docs/                     our design notes and API decisions
└── LICENSE                   MPL-2.0
```

## Clone

The corpus is required for every task that touches data:

```sh
git clone --recurse-submodules <repo-url>
# existing checkout:
git submodule update --init --recursive
```

Refresh the corpus to the pinned commit after a pull:

```sh
git submodule update --recursive
```

## Corpus facts

- Source of truth: `vendor/att-hackathon-task` (MIT licensed, fictional organization).
- Main material: TypeScript/Python/Java apps, `docs/`, `wiki/`, `meeting-notes/`, `issues/`, `incidents/`, `releases/`, `api-specs/`, `diagrams/`.
- Running the upstream apps is optional; source inspection is sufficient. Derived stores (parsed corpus, embeddings, indexes) must not be committed.

## License

MPL-2.0. See `LICENSE`. The corpus submodule keeps its own MIT license.
