import base64
import os
import pathlib
import re
import shutil
import tempfile
import zipfile
from concurrent.futures import Future, ThreadPoolExecutor

import click
import pypandoc
from dotenv import load_dotenv
from mistralai.client import Mistral
from mistralai.client.models.documenturlchunk import DocumentURLChunkTypedDict
from mistralai.client.models.file import FileTypedDict


def _convert_epub_to_pdf(epub_path: str) -> str:
    """Convert EPUB file to PDF using pypandoc.
    Extracts EPUB to temp directory and executes conversion there to preserve images.
    Returns path to temporary PDF file."""
    try:
        pypandoc.get_pandoc_version()
    except OSError as error:
        raise RuntimeError(
            "pandoc is not installed. Please install pandoc to convert EPUB files. See: https://pandoc.org/installing.html"
        ) from error

    temp_dir: str | None = None
    original_cwd = os.getcwd()
    try:
        temp_dir = str(
            pathlib.Path(tempfile.mkdtemp(dir=".", prefix=".epub_temp_")).resolve()
        )

        with zipfile.ZipFile(epub_path, "r") as zip_ref:
            zip_ref.extractall(temp_dir)

        temp_epub = os.path.join(temp_dir, os.path.basename(epub_path))
        shutil.copy2(epub_path, temp_epub)

        temp_pdf_fd, temp_pdf_name = tempfile.mkstemp(
            suffix=".pdf", dir=".", prefix=".epub_temp_"
        )
        os.close(temp_pdf_fd)
        temp_pdf_path = str(pathlib.Path(temp_pdf_name).resolve())

        os.chdir(temp_dir)

        pypandoc.convert_file(
            temp_epub,
            "pdf",
            outputfile=temp_pdf_path,
            extra_args=["--pdf-engine=weasyprint"],
        )

        return temp_pdf_path
    except Exception as error:
        raise RuntimeError(
            f"Error converting EPUB to PDF: {error}. Make sure pandoc is installed."
        ) from error
    finally:
        os.chdir(original_cwd)

        if temp_dir and os.path.exists(temp_dir):
            try:
                shutil.rmtree(temp_dir)
            except Exception:
                pass


@click.group()
def cli() -> None:
    """A CLI tool to convert PDF and EPUB files to Markdown using Mistral OCR."""
    pass


@cli.command()
@click.argument("file_path", type=click.Path(exists=True, dir_okay=False))
@click.option(
    "--output", "-o", type=click.Path(dir_okay=False), help="Output markdown file path."
)
@click.option(
    "--api-key",
    envvar="MISTRAL_API_KEY",
    help="Mistral API Key. Can also be set via MISTRAL_API_KEY environment variable.",
)
def convert(file_path: str, output: str | None, api_key: str | None) -> bool | None:
    """Converts a PDF or EPUB file to Markdown."""
    load_dotenv()

    resolved_api_key = api_key or os.getenv("MISTRAL_API_KEY")
    if not resolved_api_key:
        click.echo(
            "Error: Mistral API Key not found. Set MISTRAL_API_KEY environment variable or use --api-key option.",
            err=True,
        )
        return None

    output_path = output or os.path.splitext(file_path)[0] + ".md"

    click.echo(f"Converting '{file_path}' to '{output_path}'...")

    try:
        _convert_file(file_path, output_path, resolved_api_key)
        click.echo(f"Successfully converted to Markdown: '{output_path}'")
        return True
    except Exception as error:
        click.echo(f"An error occurred: {error}", err=True)
        return False


@cli.command()
@click.argument(
    "directory_path", type=click.Path(exists=True, file_okay=False, dir_okay=True)
)
@click.option(
    "--output-dir",
    "-o",
    type=click.Path(file_okay=False),
    help="Output directory for markdown files. Defaults to same directory as input.",
)
@click.option(
    "--api-key",
    envvar="MISTRAL_API_KEY",
    help="Mistral API Key. Can also be set via MISTRAL_API_KEY environment variable.",
)
@click.option(
    "--max-workers",
    "-w",
    type=int,
    default=2,
    help="Maximum number of concurrent conversions. Default is 2.",
)
def convert_dir(
    directory_path: str,
    output_dir: str | None,
    api_key: str | None,
    max_workers: int,
) -> None:
    """Converts all PDF and EPUB files in a directory to Markdown."""
    load_dotenv()

    resolved_api_key = api_key or os.getenv("MISTRAL_API_KEY")
    if not resolved_api_key:
        click.echo(
            "Error: Mistral API Key not found. Set MISTRAL_API_KEY environment variable or use --api-key option.",
            err=True,
        )
        return

    resolved_output_dir = output_dir or directory_path
    if output_dir:
        os.makedirs(resolved_output_dir, exist_ok=True)

    document_files: list[str] = []
    for file_name in os.listdir(directory_path):
        if file_name.lower().endswith((".pdf", ".epub")):
            document_files.append(os.path.join(directory_path, file_name))

    if not document_files:
        click.echo(f"No PDF or EPUB files found in '{directory_path}'")
        return

    click.echo(f"Found {len(document_files)} files to convert")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures: list[tuple[Future[bool], str, str]] = []
        for file_path in document_files:
            base_name = os.path.basename(file_path)
            output_name = os.path.splitext(base_name)[0] + ".md"
            output_path = os.path.join(resolved_output_dir, output_name)

            future = executor.submit(
                _convert_file,
                file_path=file_path,
                output=output_path,
                api_key=resolved_api_key,
            )
            futures.append((future, file_path, output_path))

        for future, file_path, output_path in futures:
            try:
                future.result()
                click.echo(f"Successfully converted '{file_path}' to '{output_path}'")
            except Exception as error:
                click.echo(f"Failed to convert '{file_path}': {error}", err=True)


def _convert_file(file_path: str, output: str, api_key: str) -> bool:
    """Internal function to convert a single PDF or EPUB file to Markdown.
    Used by both convert and convert_dir commands."""
    temp_pdf_path: str | None = None
    try:
        client = Mistral(api_key=api_key)

        if file_path.lower().endswith(".epub"):
            click.echo("Converting EPUB to PDF...")
            temp_pdf_path = _convert_epub_to_pdf(file_path)
            pdf_to_process = temp_pdf_path
        else:
            pdf_to_process = file_path

        with open(pdf_to_process, "rb") as pdf_file:
            upload_file: FileTypedDict = {
                "file_name": os.path.basename(pdf_to_process),
                "content": pdf_file,
            }
            uploaded_pdf = client.files.upload(file=upload_file, purpose="ocr")

        signed_url = client.files.get_signed_url(file_id=uploaded_pdf.id)

        document: DocumentURLChunkTypedDict = {
            "type": "document_url",
            "document_url": signed_url.url,
        }
        ocr_response = client.ocr.process(
            model="mistral-ocr-latest",
            document=document,
            include_image_base64=True,
        )

        final_markdown_parts: list[str] = []
        output_path = pathlib.Path(output)
        image_dir = output_path.parent / (output_path.stem + "_images")
        try:
            image_dir.mkdir(parents=True, exist_ok=True)
        except Exception as mkdir_error:
            click.echo(
                f"Warning: Could not create image directory '{image_dir}': {mkdir_error}",
                err=True,
            )

        image_counter = 0
        processed_image_filenames: set[str] = set()

        for page in ocr_response.pages:
            found_images = re.findall(r"!\[.*?\]\((.*?)\)", page.markdown)
            processed_image_filenames.update(found_images)

        for page_index, page in enumerate(ocr_response.pages):
            page_markdown = page.markdown
            for img_index, image_obj in enumerate(page.images):
                base64_data = image_obj.image_base64
                if not isinstance(base64_data, str):
                    continue

                try:
                    if ";base64," in base64_data:
                        base64_data = base64_data.split(";base64,", 1)[1]

                    image_data = base64.b64decode(base64_data)

                    image_filename = f"image_p{page_index}_i{img_index}.png"
                    potential_markdown_filename: str | None = None
                    for file_name in processed_image_filenames:
                        if file_name.startswith(f"img-{image_counter}."):
                            potential_markdown_filename = file_name
                            break

                    if potential_markdown_filename:
                        base_name, _ = os.path.splitext(potential_markdown_filename)
                        image_filename = base_name + ".png"

                    image_save_path = image_dir / image_filename
                    relative_image_path = image_dir.name + "/" + image_filename

                    with open(image_save_path, "wb") as image_file:
                        image_file.write(image_data)
                    image_counter += 1

                    original_filename_in_markdown: str | None = None
                    if image_filename in processed_image_filenames:
                        original_filename_in_markdown = image_filename
                    elif (
                        potential_markdown_filename is not None
                        and potential_markdown_filename in processed_image_filenames
                    ):
                        original_filename_in_markdown = potential_markdown_filename

                    if original_filename_in_markdown:
                        old_link_pattern = f"]({original_filename_in_markdown})"
                        new_link_pattern = f"]({relative_image_path})"
                        if old_link_pattern in page_markdown:
                            page_markdown = page_markdown.replace(
                                old_link_pattern, new_link_pattern
                            )

                except Exception:
                    pass

            final_markdown_parts.append(page_markdown)

        markdown_content = "\n\n".join(final_markdown_parts)

        with open(output, "w", encoding="utf-8") as outfile:
            outfile.write(markdown_content)

        try:
            client.files.delete(file_id=uploaded_pdf.id)
        except Exception:
            pass

        return True

    except Exception as error:
        raise RuntimeError(f"Error converting {file_path}: {error}") from error
    finally:
        if temp_pdf_path and os.path.exists(temp_pdf_path):
            try:
                os.remove(temp_pdf_path)
            except Exception:
                pass


if __name__ == "__main__":
    cli()
