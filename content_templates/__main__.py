"""Command line:

    python -m content_templates build [--out DIR]          write one .xlsx per niche
    python -m content_templates check FILE --niche NICHE   validate a filled sheet
"""

import argparse
import json
import os
import sys

from content_templates.excel import build_workbook, read_workbook
from content_templates.specs import NICHES, get_spec


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m content_templates")
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build", help="write one Excel template per niche")
    build.add_argument("--out", default="output/content_templates")
    check = sub.add_parser("check", help="validate a filled Excel file")
    check.add_argument("file")
    check.add_argument("--niche", required=True, choices=sorted(NICHES))
    args = parser.parse_args(argv)

    if args.command == "build":
        os.makedirs(args.out, exist_ok=True)
        for spec in NICHES.values():
            path = os.path.join(args.out, f"{spec.niche}_content_template.xlsx")
            build_workbook(spec).save(path)
            print(path)
        return 0

    result = read_workbook(args.file, get_spec(args.niche))
    print(json.dumps({"ok": result.ok, "videos": len(result.videos), "errors": result.errors}, indent=2, ensure_ascii=False))
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
