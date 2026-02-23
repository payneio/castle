# Python Tools in Castle

How to build CLI tools following Unix philosophy.

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
| **Testing** | pytest |
| **Linting** | ruff (shared `ruff.toml` at repo root) |
| **Type checking** | pyright (shared `pyrightconfig.json` at repo root) |
| **Python** | 3.11+ minimum |

## Project layout

Each tool is an independent project under `components/` with its own `pyproject.toml`:

```
components/my-tool/
├── src/my_tool/
│   ├── __init__.py
│   └── main.py       # Entry point
├── tests/
│   └── test_main.py
├── pyproject.toml
└── CLAUDE.md
```

Examples: `components/pdf2md/`, `components/gpt/`, `components/protonmail/`

## Creating a new tool

```bash
castle create my-tool --type tool --description "Does something"
cd components/my-tool && uv sync
```

This scaffolds the project and registers it in `castle.yaml`.

## pyproject.toml

```toml
[project]
name = "my-tool"
version = "0.1.0"
description = "Does something useful"
requires-python = ">=3.11"
dependencies = []

[project.scripts]
my-tool = "my_tool.main:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/my_tool"]

[dependency-groups]
dev = ["pytest>=7.0.0"]

[tool.ruff.lint.isort]
known-first-party = ["my_tool"]
```

After `uv tool install --editable .`, the command is in PATH.

## Tool implementation patterns

### Simple tool: stdin/stdout

The most common pattern. Read from a file argument or stdin, process, write
to stdout.

```python
#!/usr/bin/env python3
"""
my-tool: Brief description

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
        subprocess.run(
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

## Testing

Tests use pytest. For standalone tools, test via subprocess to exercise the
real CLI interface:

```python
import subprocess
import sys


class TestCLI:
    def test_version(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "my_tool.main", "--version"],
            capture_output=True,
            text=True,
        )
        assert "my-tool" in result.stdout

    def test_stdin(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "my_tool.main"],
            input="hello\n",
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "hello" in result.stdout

    def test_file_input(self, tmp_path) -> None:
        input_file = tmp_path / "input.txt"
        input_file.write_text("test data")
        result = subprocess.run(
            [sys.executable, "-m", "my_tool.main", str(input_file)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "test data" in result.stdout
```

For unit testing core logic, import the function directly and test it as a
pure function.

## Commands

```bash
uv sync                     # Install deps
uv run my-tool --help       # Run the tool
uv run pytest tests/ -v     # Run tests
uv run ruff check .         # Lint
uv run ruff format .        # Format
```

## Registering in castle.yaml

```yaml
components:
  my-tool:
    description: Does something useful
    source: components/my-tool
    install:
      path:
        alias: my-tool
```

Tools with system dependencies declare them in the component:

```yaml
components:
  pdf2md:
    description: Convert PDF files to Markdown
    source: components/pdf2md
    install:
      path:
        alias: pdf2md
    tool:
      system_dependencies: [pandoc, poppler-utils]
```

Tools live in the `components:` section. If a tool also runs on a schedule,
add a separate entry in the `jobs:` section referencing the component.

See @docs/component-registry.md for the full registry reference.
