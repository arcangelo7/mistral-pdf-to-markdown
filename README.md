# Mistral PDF to Markdown

[![PyPI version](https://img.shields.io/pypi/v/mistral-pdf-to-markdown.svg)](https://pypi.org/project/mistral-pdf-to-markdown/)
![uv](https://img.shields.io/badge/uv-managed-blueviolet?logo=python&logoColor=white)

CLI tool to convert PDF and EPUB files to Markdown with the Mistral OCR API. Embedded images are saved next to the generated Markdown file.

The converter calls `mistral-ocr-latest`.

## Installation

Install the published CLI:

```bash
pip install mistral-pdf-to-markdown
```

For an isolated global command:

```bash
pipx install mistral-pdf-to-markdown
```

For local development:

```bash
git clone https://github.com/arcangelo7/mistral-pdf-to-markdown.git
cd mistral-pdf-to-markdown
uv sync --locked
```

EPUB conversion also requires `pandoc`: https://pandoc.org/installing.html

## Usage

Set your Mistral API key:

```bash
export MISTRAL_API_KEY='your_api_key_here'
```

You can also use a `.env` file or pass `--api-key`.

```bash
pdf2md convert ./document.pdf
pdf2md convert ./document.epub -o ./output/document.md
pdf2md convert-dir ./documents -o ./markdown_output -w 4
```

Output images are written to `<output_filename_stem>_images/` and linked from the Markdown file.

The repository includes [example.md](example.md), generated from [example.pdf](example.pdf).

## License

ISC. See [LICENSE](LICENSE).
