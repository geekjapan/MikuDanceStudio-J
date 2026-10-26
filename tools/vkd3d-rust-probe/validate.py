#!/usr/bin/env python3
"""Print hosted probe evidence and fail unless the complete unit builds on stable."""
import argparse
import json
from pathlib import Path

from probe import outcome


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("result", type=Path)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--expected-unit")
    group.add_argument("--all-units", action="store_true")
    args = parser.parse_args()
    if not args.result.is_file():
        print(f"### {args.expected_unit or 'all 24 units'}\n\nStatus: incomplete. Result JSON is missing.")
        return 1
    result = json.loads(args.result.read_text())
    status = outcome(result)
    requested = list(result.get("input_sha256", {}))
    if args.all_units:
        from full_compiler import UNITS
        if (sorted(requested) != list(UNITS)
                or sorted(result.get("translated_sources", [])) != list(UNITS)
                or len(result.get("syntax", [])) != len(UNITS)
                or not result.get("all_unit_prototype")):
            status = "incomplete"
    elif (len(requested) != 1 or Path(requested[0]).name != args.expected_unit
            or len(result.get("syntax", [])) != 1):
        status = "incomplete"
    if result.get("status") != status:
        status = "incomplete"
    translation = result.get("transpile", {})
    print(f"### {args.expected_unit or 'all 24 units'}\n\nStatus: **{status}**. Production/stable compiler acceptance is unproven.")
    print(f"\nComplete translation: {result.get('complete_translation', False)}.")
    for key in ("exit_code", "timed_out", "wall_seconds", "user_cpu_seconds", "system_cpu_seconds", "max_rss_bytes"):
        print(f"- Translator {key}: {translation.get(key, 'unavailable')}")
    if args.all_units:
        print("\nParser patch: " + str(result.get("parser_patch", "unavailable")))
        print("\nLink: " + str(result.get("link", "unavailable")))
        print("\nRuntime: " + str(result.get("runtime_comparison", {}).get("status", "unavailable")))
        return 1  # A bootstrap/modified prototype is never production stable acceptance.
    return 0 if status == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
