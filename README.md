# Mistral PDF to Markdown Converter

[![PyPI version](https://img.shields.io/pypi/v/mistral-pdf-to-markdown.svg)](https://pypi.org/project/mistral-pdf-to-markdown/)
![Poetry](https://img.shields.io/badge/poetry-2.1.2-blue?logo=poetry&logoColor=blue)

A simple command-line tool to convert PDF files into Markdown format using the Mistral AI OCR API.
This tool also extracts embedded images and saves them in a subdirectory relative to the output markdown file.

## Installation

You can install the package directly from PyPI using pip:

```bash
pip install mistral-pdf-to-markdown
```

### Global Installation (Recommended for CLI Usage)

If you want to use the `pdf2md` command from anywhere in your system without activating a specific virtual environment, the recommended way is to use `pipx`:

1.  **Install `pipx`** (if you don't have it already). Follow the official [pipx installation guide](https://pipx.pypa.io/stable/installation/). A common method is:
    ```bash
    python3 -m pip install --user pipx
    python3 -m pipx ensurepath
    ```
    *(Restart your terminal after running `ensurepath`)*

2.  **Install the package using `pipx`:**
    ```bash
    pipx install mistral-pdf-to-markdown
    ```

This installs the package in an isolated environment but makes the `pdf2md` command globally available.

### Installation from Source

Alternatively, if you want to install from the source:

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/arcangelo7/mistral-pdf-to-markdown.git
    cd mistral-pdf-to-markdown 
    ```

2.  **Install dependencies using Poetry:**
    ```bash
    poetry install
    ```

## Usage

1.  **Set your Mistral API Key:**
    You can set your API key as an environment variable:
    ```bash
    export MISTRAL_API_KEY='your_api_key_here'
    ```
    Alternatively, you can create a `.env` file in the project root directory with the following content:
    ```
    MISTRAL_API_KEY=your_api_key_here
    ```
    You can also pass the API key directly using the `--api-key` option.

2.  **Run the conversion:**

    ### Convert a Single PDF File
    The `convert` command processes a single PDF file.
    ```bash
    poetry run pdf2md convert <path/to/your/document.pdf> [options]
    ```
    Or, if you have activated the virtual environment (`poetry shell`):
    ```bash
    pdf2md convert <path/to/your/document.pdf> [options]
    ```

    **Options for Single File Conversion:**
    *   `--output` or `-o`: Specify the path for the output Markdown file. If not provided, it defaults to the same name as the input PDF but with a `.md` extension (e.g., `document.md`).
    *   `--api-key`: Provide the Mistral API key directly.

    ### Convert Multiple PDF Files from a Directory
    The `convert-dir` command processes all PDF files in a specified directory.
    ```bash
    poetry run pdf2md convert-dir <path/to/directory/with/pdfs> [options]
    ```
    Or, if you have activated the virtual environment (`poetry shell`):
    ```bash
    pdf2md convert-dir <path/to/directory/with/pdfs> [options]
    ```

    **Options for Directory Conversion:**
    *   `--output-dir` or `-o`: Specify the directory where output Markdown files will be saved. If not provided, it defaults to the same directory as the input PDFs.
    *   `--api-key`: Provide the Mistral API key directly.
    *   `--max-workers` or `-w`: Maximum number of concurrent conversions (default: 2). Increase this value to process multiple files in parallel for faster conversion.

**Image Handling:**

The script will attempt to extract images embedded in the PDF.
*   Images are saved in a subdirectory named `<output_filename_stem>_images` (e.g., if the output is `report.md`, images will be in `report_images/`).
*   The generated Markdown file will contain relative links pointing to the images in this subdirectory.

**Examples:**

```bash
# Convert a single PDF file
poetry run pdf2md convert ./my_report.pdf -o ./output/report.md
```
This command will create:
*   `./output/report.md` (the markdown content)
*   `./output/report_images/` (a directory containing extracted images)

```bash
# Convert all PDF files in a directory
poetry run pdf2md convert-dir ./pdf_documents/ -o ./markdown_output/ -w 4
```
This command will:
*   Process all PDF files in the `./pdf_documents/` directory
*   Save the resulting Markdown files in the `./markdown_output/` directory
*   Process up to 4 files concurrently
*   Create image directories for each output file as needed

An example output generated from `example.pdf` (included in the repository) can be found in `example.md`, with its corresponding images located in the `example_images/` directory.

## Development

Use `poetry shell` to activate the virtual environment for development.

Run tests (if any) using:
```bash
poetry run pytest
```

## License

This project is licensed under the ISC License - see the [LICENSE](LICENSE) file for details.