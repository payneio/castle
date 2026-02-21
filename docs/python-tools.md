# Python Tools in Castle

How to build CLI tools following Unix philosophy. Based on the patterns in the
[toolkit](https://github.com/payneio/toolkit) project.

## Principles

- Each tool does one thing well
- Read from stdin or file argument, write to stdout
- Compose via pipes: `pdf2md doc.pdf | gpt "summarize this"`
- Status messages go to stderr (don't interfere with piping)
- Exit 0 on success, 1 on error

## Stack

| Layer | Choice |
|-------|--------|
| **CLI** | argparse |
| **Package manager** | uv (never pip) |
| **Build** | hatchling |
| **Testing** | unittest + mocking |
| **Linting** | ruff |
| **Type checking** | pyright |

## Project layout

Tools live inside a single package with categories:

```
toolkit/
├── tools/
│   ├── document/
│   │   ├── pdf2md.py          # Implementation
│   │   ├── pdf2md.md          # Docs + YAML frontmatter (single source of truth)
│   │   └── test_pdf2md.py     # Tests alongside tool
│   ├── search/
│   │   ├── search.py
│   │   ├── search.md
│   │   └── test_search.py
│   ├── system/
│   │   ├── schedule.py
│   │   └── schedule.md
│   └── toolkit/
│       ├── toolkit.py         # Meta-tool for discovery/scaffolding
│       └── toolkit.md
├── pyproject.toml
├── Makefile
└── README.md
```

Each tool is a `.py` + `.md` pair. The `.md` file has YAML frontmatter for
metadata — no separate config files needed.

## YAML frontmatter (.md file)

```yaml
---
command: pdf2md
script: document/pdf2md.py
description: Convert PDF files to Markdown
version: 1.0.0
category: document
system_dependencies:
  - pandoc
  - poppler-utils
---

# pdf2md

Converts PDF files to Markdown format...
```

The toolkit management command discovers tools by scanning for these `.md` files.

## pyproject.toml

```toml
[project]
name = "toolkit"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "requests>=2.28.0",
    "pyyaml>=6.0.0",
]

[project.scripts]
pdf2md = "tools.document.pdf2md:main"
docx2md = "tools.document.docx2md:main"
search = "tools.search.search:main"
toolkit = "tools.toolkit.toolkit:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["tools"]
```

Entry points follow `command = "tools.<category>.<tool>:main"`. After
`uv tool install --editable .`, all commands are in PATH.

## Tool implementation patterns

### Simple tool: stdin/stdout

The most common pattern. Read from a file argument or stdin, process, write
to stdout.

```python
#!/usr/bin/env python3
"""
my-tool: Brief description

Detailed usage docs here.

Usage:
    my-tool [options] [FILE]
    cat input.txt | my-tool

Examples:
    my-tool input.txt
    my-tool input.txt -o output.txt
    cat input.txt | my-tool > output.txt
"""

import argparse
import sys


def process(data: str) -> str:
    """Core logic — pure function, easy to test."""
    return data.upper()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Brief description",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("input", nargs="?", help="Input file (default: stdin)")
    parser.add_argument("-o", "--output", help="Output file (default: stdout)")
    parser.add_argument("--version", action="version", version="my-tool 1.0.0")
    args = parser.parse_args()

    # Read
    if args.input:
        with open(args.input) as f:
            data = f.read()
    else:
        data = sys.stdin.read()

    # Process
    result = process(data)

    # Write
    if args.output:
        with open(args.output, "w") as f:
            f.write(result)
        print(f"Wrote to {args.output}", file=sys.stderr)
    else:
        print(result, end="")

    return 0


if __name__ == "__main__":
    sys.exit(main())
```

### Tool with subcommands

For complex tools with multiple operations:

```python
def cmd_init(args: argparse.Namespace) -> int:
    """Initialize a collection."""
    directory = args.directory or "."
    # ...
    print(f"Initialized in {directory}")
    return 0


def cmd_query(args: argparse.Namespace) -> int:
    """Search a collection."""
    # ...
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage collections")
    parser.add_argument("--version", action="version", version="1.0.0")
    subparsers = parser.add_subparsers(dest="command")

    init_p = subparsers.add_parser("init", help="Initialize")
    init_p.add_argument("directory", nargs="?")
    init_p.add_argument("--name", help="Collection name")
    init_p.add_argument("--force", action="store_true")

    query_p = subparsers.add_parser("query", help="Search")
    query_p.add_argument("query", help="Search query")
    query_p.add_argument("--limit", type=int, default=20)

    args = parser.parse_args()

    if args.command == "init":
        return cmd_init(args)
    elif args.command == "query":
        return cmd_query(args)
    else:
        parser.print_help()
        return 1
```

### Tool with external processes

When wrapping system commands:

```python
import subprocess
import sys


def convert(input_file: str, output_file: str) -> int:
    try:
        result = subprocess.run(
            ["pandoc", input_file, "-o", output_file],
            check=True,
            capture_output=True,
            text=True,
        )
        return 0
    except subprocess.CalledProcessError as e:
        print(f"Error: {e}", file=sys.stderr)
        if e.stderr:
            print(e.stderr, file=sys.stderr)
        return 1
    except FileNotFoundError:
        print("Error: pandoc not found. Install with: apt install pandoc",
              file=sys.stderr)
        return 1
```

Always use `check=True` and `capture_output=True` with subprocess. Handle
`FileNotFoundError` for missing system dependencies.

### Tool with optional dependencies

```python
tantivy_available = False
try:
    import tantivy
    tantivy_available = True
except ImportError:
    tantivy = None


def check_tantivy() -> None:
    if not tantivy_available:
        print("Error: tantivy not found. Install with: uv add tantivy",
              file=sys.stderr)
        sys.exit(1)
```

## Error handling

```python
def main() -> int:
    try:
        result = do_work()
        print(result)
        return 0
    except SpecificError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except FileNotFoundError as e:
        print(f"Error: file not found: {e}", file=sys.stderr)
        return 1
```

Rules:
- Normal output goes to **stdout** (enables piping)
- Error messages go to **stderr**
- Status/progress messages go to **stderr**
- Return **0** for success, **1** for error
- Entry point: `sys.exit(main())`

## Piping

Tools compose naturally via Unix pipes:

```bash
# Convert and summarize
pdf2md paper.pdf | gpt "summarize this"

# Process a batch
for f in *.pdf; do pdf2md "$f" > "${f%.pdf}.md"; done

# Chain extractors
cat doc.txt | text-extractor | jq .content
```

When a tool writes to both a file and stdout, status messages must go to
stderr so they don't contaminate the pipe:

```python
with open(output_file, "w") as f:
    f.write(result)
print(result)                                    # stdout (for piping)
print(f"Wrote to {output_file}", file=sys.stderr)  # stderr (status)
```

## Testing

Tests live alongside the tool implementation, using unittest with mocking:

```python
# tools/gpt/test_gpt.py
import unittest
from unittest.mock import patch, MagicMock
from io import StringIO

from tools.gpt import gpt


class TestGPT(unittest.TestCase):
    @patch("tools.gpt.gpt.get_api_key")
    @patch("openai.OpenAI")
    def test_generate(self, mock_openai, mock_key):
        mock_key.return_value = "fake-key"
        mock_client = MagicMock()
        mock_openai.return_value = mock_client
        mock_client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="response"))]
        )

        result = gpt.generate_text("prompt", "gpt-4", 0.7, 500)
        self.assertEqual(result, "response")

    @patch("tools.gpt.gpt.generate_text")
    def test_cli(self, mock_gen):
        mock_gen.return_value = "output"
        with patch("sys.argv", ["gpt", "prompt"]):
            with patch("sys.stdout", new=StringIO()) as out:
                gpt.main()
                self.assertEqual(out.getvalue().strip(), "output")
```

Pattern: mock external dependencies (APIs, file I/O, subprocesses), test the
CLI by patching `sys.argv`.

## Build and install

```makefile
# Makefile
all: build install

build:
	uv sync

install:
	uv tool install --editable .

check:
	uv run ruff format .
	uv run ruff check . --fix
	uv run pyright

test:
	uv run pytest -v

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
```

```bash
make all        # Sync deps + install to PATH
make check      # Format, lint, type-check
make test       # Run tests
```

## Creating a new tool

Use the toolkit management command:

```bash
toolkit create my-tool --description "Does something" --category document
```

This creates the `.py` template, `.md` with frontmatter, and updates
`pyproject.toml` with the entry point.

Or manually:
1. Create `tools/<category>/my_tool.py` with the argparse pattern above
2. Create `tools/<category>/my_tool.md` with YAML frontmatter
3. Add entry to `pyproject.toml` under `[project.scripts]`:
   ```toml
   my-tool = "tools.category.my_tool:main"
   ```
4. Run `make install` to register in PATH

## Registering in castle

```yaml
# castle.yaml
components:
  toolkit:
    description: Personal utility scripts
    run:
      runner: command
      argv: ["toolkit"]
      cwd: toolkit
    install:
      path: { alias: toolkit }
```

Tools with `install.path` get the `tool` role. They don't need `expose`,
`proxy`, or `manage` blocks.
