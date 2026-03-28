"""
Terminal display helpers for CLI mode.
"""
try:
    from colorama import init, Fore, Style
    init(autoreset=True)
    HAS_COLOR = True
except ImportError:
    HAS_COLOR = False


def _ok(label: str) -> str:
    prefix = (Fore.GREEN + "✅" + Style.RESET_ALL) if HAS_COLOR else "[OK]"
    return f"  {prefix}  {label}"


def _warn(label: str) -> str:
    prefix = (Fore.YELLOW + "⚠️ " + Style.RESET_ALL) if HAS_COLOR else "[WARN]"
    return f"  {prefix} {label}"


def _fail(label: str) -> str:
    prefix = (Fore.RED + "❌" + Style.RESET_ALL) if HAS_COLOR else "[FAIL]"
    return f"  {prefix}  {label}"


def print_verification_status(state: dict) -> None:
    print("\n" + "═" * 60)
    print("  🔐  ARIA VERIFICATION CHAIN STATUS")
    print("═" * 60)

    if state.get("pii_clean"):
        print(_ok("PII Scan          — Clean"))
    elif state.get("pii_warning"):
        print(_warn(f"PII Scan          — Warning: {state['pii_warning']}"))
    else:
        print(_fail("PII Scan          — Not run"))

    if state.get("recipient_validated"):
        print(_ok(f"Recipient Valid   — {state.get('recipient_email', '')} confirmed"))
    elif state.get("validation_error"):
        print(_fail(f"Recipient Valid   — {state['validation_error']}"))

    if state.get("content_policy_pass"):
        print(_ok("Content Policy    — No violations"))
    elif state.get("policy_violations"):
        print(_warn(f"Content Policy    — {state['policy_violations']}"))

    risk = state.get("overall_risk", "UNKNOWN")
    if risk == "LOW":
        print(_ok(f"Risk Level        — {risk}"))
    elif risk == "MEDIUM":
        print(_warn(f"Risk Level        — {risk}"))
    else:
        print(_fail(f"Risk Level        — {risk}"))

    if state.get("blocked"):
        print(_fail(f"BLOCKED           — {state.get('block_reason', '')}"))

    print("═" * 60)


def print_email_preview(state: dict) -> None:
    print("\n  📧  EMAIL PREVIEW")
    print("─" * 60)
    print(f"  To:      {state.get('recipient_name', '')} <{state.get('recipient_email', '')}>")
    print(f"  Subject: {state.get('subject', '')}")
    print("─" * 60)
    for line in state.get("body_draft", "").splitlines():
        print(f"  {line}")
    print("─" * 60)
