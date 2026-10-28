#!/usr/bin/env python3
"""Print hosted probe evidence and fail unless the complete unit builds on stable."""
import argparse
import json
from pathlib import Path

from probe import outcome


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("result", type=Path)
    parser.add_argument("--expected-unit", required=True)
    args = parser.parse_args()
    if not args.result.is_file():
        print(f"### {args.expected_unit}\n\nStatus: incomplete. Result JSON is missing.")
        return 1
    result = json.loads(args.result.read_text())
    status = outcome(result)
    requested = list(result.get("input_sha256", {}))
    if (len(requested) != 1 or Path(requested[0]).name != args.expected_unit
            or len(result.get("syntax", [])) != 1):
        status = "incomplete"
    if result.get("status") != status:
        status = "incomplete"
    translation = result.get("transpile", {})
    print(f"### {args.expected_unit}\n\nStatus: **{status}**. Whole compiler acceptance is untested.")
    print(f"\nComplete translation: {result.get('complete_translation', False)}.")
    for key in ("exit_code", "timed_out", "wall_seconds", "user_cpu_seconds", "system_cpu_seconds", "max_rss_bytes"):
        print(f"- Translator {key}: {translation.get(key, 'unavailable')}")
    return 0 if status == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
