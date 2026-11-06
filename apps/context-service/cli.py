# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""`ncs` — ingest, resolve, query."""

import argparse
import logging
import sys
from datetime import date

from api.render import render_text
from ingest.pipeline import ingest
from models.answer import EvidenceFilter, TimeFilter
from models.ontology import Status
from service import IndexMissing, query, resolved
from settings import load_settings


def _ingest(_: argparse.Namespace) -> int:
    report = ingest(load_settings())
    print(f"written {report.written} claims, dropped {len(report.dropped)}")
    for reason in report.dropped:
        print(f"  dropped {reason}")
    return 1 if report.dropped else 0


def _resolve(args: argparse.Namespace) -> int:
    for r in resolved(load_settings(), args.as_of or date.today()):
        span = r.claim.evidence[0]
        print(
            f"{r.status:<10} conf {r.confidence:.2f} score {r.score.score:.3f} "
            f"{r.claim.source_type:<10} {span.path}:{span.start_line}  {r.reason}"
        )
    return 0


def _query(args: argparse.Namespace) -> int:
    time = TimeFilter(as_of=args.as_of, status_in=[Status.VALID]) if args.valid_only else (
        TimeFilter(as_of=args.as_of)
    )
    answer = query(args.question, load_settings(), time, EvidenceFilter(min_confidence=args.min_confidence))
    print(answer.model_dump_json(indent=2) if args.json else render_text(answer))
    return 0


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(prog="ncs")
    sub = parser.add_subparsers(required=True)

    sub.add_parser("ingest", help="gate and date the claim fixtures").set_defaults(fn=_ingest)

    p = sub.add_parser("resolve", help="print every claim with its status and score")
    p.add_argument("--as-of", type=date.fromisoformat)
    p.set_defaults(fn=_resolve)

    p = sub.add_parser("query", help="answer a question, split into VALID / NOT VALID")
    p.add_argument("question")
    p.add_argument("--as-of", type=date.fromisoformat)
    p.add_argument("--min-confidence", type=float)
    p.add_argument("--valid-only", action="store_true", help="omit the NOT VALID section")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=_query)

    args = parser.parse_args()
    try:
        sys.exit(args.fn(args))
    except IndexMissing as exc:
        print(exc, file=sys.stderr)
        sys.exit(2)
