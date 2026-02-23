#!/usr/bin/env python3
"""
mbox2eml: Convert MBOX mailbox files to individual .eml files

Reads an .mbox file and exports each message as a separate .eml file
with clean, descriptive filenames based on date, sender, and recipient.

Usage:
    mboxer mailbox.mbox
    mboxer mailbox.mbox -o output_dir/
    mboxer mailbox.mbox --max-length 80

Options:
    -o, --output DIR      Output directory (default: eml_output)
    --max-length N        Max filename length before truncation (default: 100)
"""

import argparse
import email
import email.header
import email.utils
import mailbox
import os
import re
import sys


def sanitize_filename(name: str) -> str:
    """Replace non-word characters with underscores."""
    return re.sub(r"[^\w\-_.]", "_", name)


def decode_header_field(header_value: str | None) -> str:
    """Decode an email header field to a plain string."""
    if header_value is None:
        return ""
    if isinstance(header_value, email.header.Header):
        return str(header_value)
    decoded_fragments = email.header.decode_header(header_value)
    return "".join(
        str(t[0], t[1] or "utf-8") if isinstance(t[0], bytes) else t[0]
        for t in decoded_fragments
    )


def extract_addresses(header_value: str | None) -> list[str]:
    """Extract lowercase email addresses from a header field."""
    decoded = decode_header_field(header_value)
    return [
        email.utils.parseaddr(addr)[1].lower()
        for addr in decoded.split(",")
        if addr.strip()
    ]


def convert(mbox_path: str, output_dir: str, max_length: int = 100) -> int:
    """Convert an mbox file to individual .eml files. Returns count of exported messages."""
    if not os.path.exists(mbox_path):
        print(f"Error: file not found: {mbox_path}", file=sys.stderr)
        return -1

    os.makedirs(output_dir, exist_ok=True)
    mbox = mailbox.mbox(mbox_path)
    count = 0

    for i, msg in enumerate(mbox):
        date_str = msg.get("date")
        try:
            parsed_date = email.utils.parsedate_to_datetime(date_str)  # type: ignore[arg-type]
            timestamp = parsed_date.strftime("%Y-%m-%d_%H-%M-%S")
        except Exception:
            timestamp = f"unknown_date_{i:04}"

        from_addr = email.utils.parseaddr(decode_header_field(msg.get("from")))[1].lower()
        to_addrs = extract_addresses(msg.get("to"))
        safe_sender = sanitize_filename(from_addr or "unknown")

        if not to_addrs:
            safe_recipient = "unknown"
        elif len(to_addrs) == 1:
            safe_recipient = sanitize_filename(to_addrs[0])
        else:
            safe_recipient = sanitize_filename(to_addrs[0]) + "_et_al"

        base_name = f"{timestamp}_from_{safe_sender}_to_{safe_recipient}"
        if len(base_name) > max_length:
            base_name = base_name[:max_length]
        filename = base_name + ".eml"
        filepath = os.path.join(output_dir, filename)

        try:
            with open(filepath, "wb") as f:
                f.write(bytes(msg))
            print(f"[{i + 1:04}] Saved: {filename}", file=sys.stderr)
            count += 1
        except Exception as e:
            print(f"[{i + 1:04}] Error saving {filename}: {e}", file=sys.stderr)

    return count


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert MBOX mailbox files to individual .eml files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("input", help="Input .mbox file")
    parser.add_argument(
        "-o", "--output", default="eml_output",
        help="Output directory (default: eml_output)",
    )
    parser.add_argument(
        "--max-length", type=int, default=100,
        help="Max filename length (default: 100)",
    )
    parser.add_argument("--version", action="version", version="mbox2eml 1.0.0")
    args = parser.parse_args()

    count = convert(args.input, args.output, args.max_length)
    if count < 0:
        return 1

    print(f"Exported {count} messages to {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
