"""
CLI tool for managing the Refinery roster.

Usage:
    python roster.py status                     Show current roster
    python roster.py pending                    Show pending proposals
    python roster.py approve <category> <ticker> Approve a pending change
    python roster.py reject <category> <ticker>  Reject a pending change
    python roster.py add <category> <ticker>     Add ticker to watch tier
    python roster.py remove <category> <ticker>  Remove ticker from roster
    python roster.py pin <category> <ticker>     Pin ticker (prevent demotion)
    python roster.py unpin <category> <ticker>   Unpin ticker
"""

import argparse
import json
import sys

from agents import roster_agent
from agents.memory_agent import init_db


def _load_roster():
    return roster_agent._load_roster()


def cmd_status(args):
    """Show current roster status."""
    roster = _load_roster()
    print(f"Roster (updated: {roster.get('last_updated', 'never')})\n")

    for category, data in roster.get("categories", {}).items():
        active = data.get("active", [])
        watch = data.get("watch", [])
        pinned = data.get("pinned", [])
        print(f"  {category}:")
        print(f"    Active ({len(active)}): {', '.join(active)}")
        print(f"    Watch  ({len(watch)}): {', '.join(watch)}")
        if pinned:
            print(f"    Pinned: {', '.join(pinned)}")
        print()


def cmd_pending(args):
    """Show pending roster proposals."""
    roster = _load_roster()
    pending = roster.get("pending_changes", [])

    if not pending:
        print("No pending roster changes.")
        return

    print(f"Pending changes ({len(pending)}):\n")
    for i, p in enumerate(pending, 1):
        print(f"  {i}. {p['action'].upper()}: {p['ticker']} in {p['category']}")
        print(f"     Health: {p.get('health_score', 'N/A'):.2f}")
        print(f"     Reason: {p['reason']}")
        print(f"     Date: {p.get('proposed_date', 'unknown')}")
        print()


def cmd_approve(args):
    """Approve a pending roster change."""
    init_db()
    roster = _load_roster()
    pending = roster.get("pending_changes", [])

    match = None
    for p in pending:
        if p["category"] == args.category and p["ticker"] == args.ticker:
            match = p
            break

    if not match:
        print(f"No pending change found for {args.ticker} in {args.category}")
        return

    success = roster_agent.apply_change(args.category, args.ticker, match["action"])
    if success:
        print(f"Approved: {match['action']} {args.ticker} in {args.category}")
    else:
        print("Failed to apply change.")


def cmd_reject(args):
    """Reject a pending roster change."""
    roster = _load_roster()
    roster["pending_changes"] = [
        p for p in roster.get("pending_changes", [])
        if not (p["category"] == args.category and p["ticker"] == args.ticker)
    ]
    roster_agent._save_roster(roster)
    print(f"Rejected change for {args.ticker} in {args.category}")


def cmd_add(args):
    """Add a ticker to watch tier."""
    init_db()
    success = roster_agent.apply_change(args.category, args.ticker, "add")
    if success:
        print(f"Added {args.ticker} to watch tier in {args.category}")
    else:
        print("Failed. Check category name.")


def cmd_remove(args):
    """Remove a ticker from roster."""
    init_db()
    success = roster_agent.apply_change(args.category, args.ticker, "evict")
    if success:
        print(f"Removed {args.ticker} from {args.category}")
    else:
        print("Failed. Check category and ticker.")


def cmd_pin(args):
    """Pin a ticker to prevent demotion."""
    init_db()
    success = roster_agent.apply_change(args.category, args.ticker, "pin")
    if success:
        print(f"Pinned {args.ticker} in {args.category}")
    else:
        print("Failed.")


def cmd_unpin(args):
    """Unpin a ticker."""
    init_db()
    success = roster_agent.apply_change(args.category, args.ticker, "unpin")
    if success:
        print(f"Unpinned {args.ticker} in {args.category}")
    else:
        print("Failed.")


def main():
    parser = argparse.ArgumentParser(description="Refinery Roster Management")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("status", help="Show current roster")
    subparsers.add_parser("pending", help="Show pending proposals")

    for cmd in ["approve", "reject", "add", "remove", "pin", "unpin"]:
        sp = subparsers.add_parser(cmd, help=f"{cmd.title()} a roster change")
        sp.add_argument("category", help="Category name (e.g., us_large_cap_growth)")
        sp.add_argument("ticker", help="Ticker symbol (e.g., AAPL)")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    commands = {
        "status": cmd_status,
        "pending": cmd_pending,
        "approve": cmd_approve,
        "reject": cmd_reject,
        "add": cmd_add,
        "remove": cmd_remove,
        "pin": cmd_pin,
        "unpin": cmd_unpin,
    }

    commands[args.command](args)

if __name__ == "__main__":
    main()
