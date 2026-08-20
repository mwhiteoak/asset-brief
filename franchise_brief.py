"""Entry point kept for compatibility — the edition itself now lives in
editions.run_franchise(), with its editorial content in franchise_content.py.

    python franchise_brief.py     ==  python editions.py franchise
"""
import sys

from editions import run_franchise

if __name__ == "__main__":
    try:
        run_franchise()
    except Exception as e:
        print(f"\nFAILED: {e}", file=sys.stderr)
        sys.exit(1)
