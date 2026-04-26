#!/usr/bin/env python3
"""Refinery preflight checklist.

Runs every validator in utils/preflight and prints a colour-coded checklist.
Use this to confirm an install is wired up before kicking off the scheduler,
or as a CI smoke test (see --json).

Examples:
  python check.py                 quick check, no email send
  python check.py --send-email    additionally fire a test email
  python check.py --json          machine-readable for scripting
  python check.py --quiet         only the summary line
"""

from __future__ import annotations

import argparse
import json
import sys

from utils.preflight import collect_results

_GREEN = "\033[32m"
_RED = "\033[31m"
_YELLOW = "\033[33m"
_DIM = "\033[2m"
_RESET = "\033[0m"


def _supports_color(stream) -> bool:
    return hasattr(stream, "isatty") and stream.isatty()


def _format_line(result: dict, use_color: bool) -> str:
    if result["skipped"]:
        marker = "[ ]"
        color = _YELLOW if use_color else ""
    elif result["ok"]:
        marker = "[x]"
        color = _GREEN if use_color else ""
    else:
        marker = "[!]"
        color = _RED if use_color else ""

    reset = _RESET if use_color else ""
    return f"  {color}{marker}{reset} {result['name']:<26} {_DIM if use_color else ''}{result['message']}{reset}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Refinery preflight checklist")
    parser.add_argument("--send-email", action="store_true",
                        help="Fire a one-line test email to TO_EMAIL via SMTP")
    parser.add_argument("--quiet", action="store_true",
                        help="Print only the summary line")
    parser.add_argument("--json", action="store_true", dest="as_json",
                        help="Machine-readable JSON output (overrides --quiet)")
    args = parser.parse_args()

    results = collect_results(send_email=args.send_email)

    passed = sum(1 for result in results if result["ok"])
    total = len(results)
    failed = [result for result in results if not result["ok"]]

    if args.as_json:
        json.dump({
            "passed": passed,
            "total": total,
            "all_ok": not failed,
            "checks": results,
        }, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0 if not failed else 1

    use_color = _supports_color(sys.stdout)

    if not args.quiet:
        print("The Refinery preflight")
        for result in results:
            print(_format_line(result, use_color))
        print()

    if not failed:
        marker = f"{_GREEN}OK{_RESET}" if use_color else "OK"
        skipped = sum(1 for result in results if result["skipped"])
        if skipped:
            print(f"{marker}: {passed} of {total} checks passed ({skipped} skipped). "
                  f"Run with --send-email to verify SMTP.")
        else:
            print(f"{marker}: {passed} of {total} checks passed.")
        return 0

    marker = f"{_RED}FAIL{_RESET}" if use_color else "FAIL"
    print(f"{marker}: {len(failed)} of {total} checks failed.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
