# Castle Tools

CLI utilities managed by the castle platform. Each tool follows Unix philosophy:
read from stdin or file arguments, write to stdout, compose via pipes.

## Installation

Each category is its own package, installed individually:

```bash
castle sync    # installs all category packages
```

Or manually install a single category:

```bash
uv tool install --editable tools/document/
```

## Tools by Category

### android (`castle-android`)

| Tool | Description | Requires |
|------|-------------|----------|
| `android-backup` | Backup Android device using ADB | adb |

### browser (`castle-browser`)

| Tool | Description |
|------|-------------|
| `browser` | Browse the web using natural language via browser-use |

### document (`castle-document`)

| Tool | Description | Requires |
|------|-------------|----------|
| `docx2md` | Convert Word .docx files to Markdown | pandoc |
| `html2text` | Convert HTML content to plain text | |
| `md2pdf` | Convert Markdown files to PDF | pandoc, texlive-latex-base |
| `pdf2md` | Convert PDF files to Markdown | pandoc, poppler-utils |

### gpt (`castle-gpt`)

| Tool | Description |
|------|-------------|
| `gpt` | OpenAI text generation utility |

### mdscraper (`castle-mdscraper`)

| Tool | Description |
|------|-------------|
| `mdscraper` | Combine text files into a single markdown document |

### search (`castle-search`)

| Tool | Description | Requires |
|------|-------------|----------|
| `docx-extractor` | Extract content and metadata from Word .docx files | pandoc |
| `pdf-extractor` | Extract content and metadata from PDF files | |
| `search` | Manage self-contained searchable collections of files | |
| `text-extractor` | Extract content and metadata from text files | |

### system (`castle-system`)

| Tool | Description | Requires |
|------|-------------|----------|
| `backup-collect` | Collect files from various sources into backup directory | rsync |
| `schedule` | Manage systemd user timers and scheduled tasks | |

## Directory Structure

```
tools/
├── <category>/
│   ├── pyproject.toml          # Per-category package
│   └── src/<category>/
│       ├── __init__.py
│       ├── <tool>.py           # Implementation
│       └── <tool>.md           # Documentation (YAML frontmatter + docs)
└── README.md
```

Each tool has two files:

- **`<tool>.py`** -- the implementation, with a `main()` entry point
- **`<tool>.md`** -- YAML frontmatter (command, description, version, category,
  system_dependencies) followed by usage documentation

## Adding a New Tool

```bash
castle create my-tool --type tool --category document
```

Or manually:

1. Create `tools/<category>/src/<category>/my_tool.py` with an argparse `main()` function
2. Create `tools/<category>/src/<category>/my_tool.md` with YAML frontmatter
3. Add the entry point to `tools/<category>/pyproject.toml`:
   ```toml
   my-tool = "<category>.my_tool:main"
   ```
4. Register in `castle.yaml`:
   ```yaml
   my-tool:
     description: What it does
     tool:
       tool_type: python_standalone
       category: <category>
       source: tools/<category>/
     install:
       path: { alias: my-tool }
   ```
5. Run `castle sync` to install

## Tool Types

Castle manages three types of tools:

| Type | Description | Installation |
|------|-------------|-------------|
| `python_standalone` | Own pyproject.toml | Individual `uv tool install` per category |
| `script` | Bash or binary | Symlinked to `~/.local/bin/` |

## Conventions

- Read from stdin or file argument, write to stdout
- Error messages and status to stderr
- Exit 0 on success, 1 on error
- `--help` for usage, `--version` where applicable
- Composable via Unix pipes: `pdf2md paper.pdf | gpt "summarize this"`

## Managing Tools

```bash
castle tool list              # All tools grouped by category
castle tool info <name>       # Tool details + documentation
castle list --role tool       # Tools in the component listing
castle info <name> --json     # Full manifest including tool metadata
```
