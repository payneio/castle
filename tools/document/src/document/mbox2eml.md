# mbox2eml

Convert MBOX mailbox files to individual .eml files with clean, descriptive
filenames based on date, sender, and recipient.

## Usage

```bash
mbox2eml mailbox.mbox                    # Export to eml_output/
mbox2eml mailbox.mbox -o emails/         # Export to custom directory
mbox2eml mailbox.mbox --max-length 80    # Truncate filenames at 80 chars
```

Output filenames look like:

```
2025-03-23_15-09-42_from_alice_example_com_to_bob_example_com.eml
```

## What can you do with .eml files?

- Open in email clients (Thunderbird, Outlook, etc.)
- Parse and analyze with Python or CLI tools
- Extract metadata, body, or attachments
- Archive and search with grep, ripgrep, etc.
