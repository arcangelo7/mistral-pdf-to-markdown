from __future__ import annotations

import os
import re
import shutil
import tempfile
import zipfile
from base64 import b64decode
from binascii import Error as Base64DecodeError
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import suppress
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

import click
import httpx
from dotenv import load_dotenv
from mistralai.client import Mistral
from mistralai.client.errors.mistralerror import MistralError
from mistralai.client.errors.no_response_error import NoResponseError

import pypandoc

if TYPE_CHECKING:
    from mistralai.client.models.documenturlchunk import DocumentURLChunkTypedDict
    from mistralai.client.models.file import FileTypedDict
    from mistralai.client.models.ocrpageobject import OCRPageObject


DOCUMENT_SUFFIXES = (".pdf", ".epub")
BASE64_MARKER = ";base64,"
IMAGE_REFERENCE_PATTERN = re.compile(r"!\[.*?\]\((.*?)\)")
MISSING_API_KEY_MESSAGE = (
    "Error: Mistral API Key not found. Set MISTRAL_API_KEY environment variable "
    "or use --api-key option."
)
PANDOC_NOT_INSTALLED_MESSAGE = (
    "pandoc is not installed. Please install pandoc to convert EPUB files. "
    "See: https://pandoc.org/installing.html"
)


class ConversionError(RuntimeError):
    pass


def _convert_epub_to_pdf(epub_path: Path) -> Path:
    """Convert EPUB file to PDF using pypandoc.
    Extracts EPUB to temp directory and executes conversion there to preserve images.
    Returns path to temporary PDF file."""
    _ensure_pandoc_is_available()

    temp_dir = Path(tempfile.mkdtemp(dir=".", prefix=".epub_temp_")).resolve()
    temp_pdf_path: Path | None = None

    try:
        _extract_epub(epub_path, temp_dir)

        temp_epub = temp_dir / epub_path.name
        shutil.copy2(epub_path, temp_epub)

        temp_pdf_path = _create_temp_pdf_path()

        pypandoc.convert_file(
            str(temp_epub),
            "pdf",
            outputfile=str(temp_pdf_path),
            extra_args=["--pdf-engine=weasyprint"],
            cworkdir=str(temp_dir),
        )
    except (OSError, RuntimeError, zipfile.BadZipFile) as error:
        if temp_pdf_path is not None:
            with suppress(OSError):
                temp_pdf_path.unlink()
        message = (
            f"Error converting EPUB to PDF: {error}. Make sure pandoc is installed."
        )
        raise ConversionError(message) from error
    else:
        return temp_pdf_path
    finally:
        with suppress(OSError):
            shutil.rmtree(temp_dir)


def _extract_epub(epub_path: Path, target_dir: Path) -> None:
    with zipfile.ZipFile(epub_path, "r") as zip_file:
        for member in zip_file.infolist():
            destination = _safe_archive_member_path(member.filename, target_dir)
            if member.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
                continue

            destination.parent.mkdir(parents=True, exist_ok=True)
            with (
                zip_file.open(member) as source_file,
                destination.open(
                    "wb",
                ) as destination_file,
            ):
                shutil.copyfileobj(source_file, destination_file)


def _safe_archive_member_path(member_filename: str, target_dir: Path) -> Path:
    archive_path = PurePosixPath(member_filename)
    if archive_path.is_absolute() or ".." in archive_path.parts:
        message = f"Unsafe EPUB archive member: {member_filename}"
        raise ConversionError(message)

    return target_dir.joinpath(*archive_path.parts)


def _ensure_pandoc_is_available() -> None:
    try:
        pypandoc.get_pandoc_version()
    except OSError as error:
        raise ConversionError(PANDOC_NOT_INSTALLED_MESSAGE) from error


def _create_temp_pdf_path() -> Path:
    temp_pdf_fd, temp_pdf_name = tempfile.mkstemp(
        suffix=".pdf",
        dir=".",
        prefix=".epub_temp_",
    )
    os.close(temp_pdf_fd)
    return Path(temp_pdf_name).resolve()


@click.group()
def cli() -> None:
    """A CLI tool to convert PDF and EPUB files to Markdown using Mistral OCR."""


@cli.command()
@click.argument("file_path", type=click.Path(exists=True, dir_okay=False))
@click.option(
    "--output",
    "-o",
    type=click.Path(dir_okay=False),
    help="Output markdown file path.",
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
        click.echo(MISSING_API_KEY_MESSAGE, err=True)
        return None

    source_path = Path(file_path)
    output_path = Path(output) if output else source_path.with_suffix(".md")

    click.echo(f"Converting '{file_path}' to '{output_path}'...")

    try:
        _convert_file(source_path, output_path, resolved_api_key)
    except ConversionError as error:
        click.echo(f"An error occurred: {error}", err=True)
        return False
    else:
        click.echo(f"Successfully converted to Markdown: '{output_path}'")
        return True


@cli.command()
@click.argument(
    "directory_path",
    type=click.Path(exists=True, file_okay=False, dir_okay=True),
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
        click.echo(MISSING_API_KEY_MESSAGE, err=True)
        return

    directory = Path(directory_path)
    resolved_output_dir = Path(output_dir) if output_dir else directory
    if output_dir:
        resolved_output_dir.mkdir(parents=True, exist_ok=True)

    document_files = _document_files(directory)

    if not document_files:
        click.echo(f"No PDF or EPUB files found in '{directory_path}'")
        return

    click.echo(f"Found {len(document_files)} files to convert")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures: list[tuple[Future[bool], Path, Path]] = []
        for file_path in document_files:
            output_path = resolved_output_dir / f"{file_path.stem}.md"

            future = executor.submit(
                _convert_file,
                file_path=file_path,
                output=output_path,
                api_key=resolved_api_key,
            )
            futures.append((future, file_path, output_path))

        for future, file_path, output_path in futures:
            _report_conversion_result(future, file_path, output_path)


def _document_files(directory: Path) -> list[Path]:
    with os.scandir(directory) as entries:
        return [
            Path(entry.path)
            for entry in entries
            if entry.is_file() and entry.name.lower().endswith(DOCUMENT_SUFFIXES)
        ]


def _report_conversion_result(
    future: Future[bool],
    file_path: Path,
    output_path: Path,
) -> None:
    try:
        future.result()
    except ConversionError as error:
        click.echo(f"Failed to convert '{file_path}': {error}", err=True)
    else:
        click.echo(f"Successfully converted '{file_path}' to '{output_path}'")


def _convert_file(file_path: Path, output: Path, api_key: str) -> bool:
    """Internal function to convert a single PDF or EPUB file to Markdown.
    Used by both convert and convert_dir commands."""
    temp_pdf_path: Path | None = None
    try:
        client = Mistral(api_key=api_key)
        pdf_to_process = file_path

        if file_path.suffix.lower() == ".epub":
            click.echo("Converting EPUB to PDF...")
            temp_pdf_path = _convert_epub_to_pdf(file_path)
            pdf_to_process = temp_pdf_path

        uploaded_file_id = _upload_file(client, pdf_to_process)
        try:
            pages = _process_ocr(client, uploaded_file_id)
            _write_markdown(pages, output)
        finally:
            _delete_uploaded_file(client, uploaded_file_id)
    except (
        ConversionError,
        MistralError,
        NoResponseError,
        OSError,
        ValueError,
        httpx.HTTPError,
    ) as error:
        message = f"Error converting {file_path}: {error}"
        raise ConversionError(message) from error
    else:
        return True
    finally:
        if temp_pdf_path is not None:
            with suppress(OSError):
                temp_pdf_path.unlink()


def _upload_file(client: Mistral, pdf_path: Path) -> str:
    with pdf_path.open("rb") as pdf_file:
        upload_file: FileTypedDict = {
            "file_name": pdf_path.name,
            "content": pdf_file,
        }
        uploaded_pdf = client.files.upload(file=upload_file, purpose="ocr")

    return uploaded_pdf.id


def _process_ocr(client: Mistral, file_id: str) -> list[OCRPageObject]:
    signed_url = client.files.get_signed_url(file_id=file_id)
    document: DocumentURLChunkTypedDict = {
        "type": "document_url",
        "document_url": signed_url.url,
    }
    ocr_response = client.ocr.process(
        model="mistral-ocr-latest",
        document=document,
        include_image_base64=True,
    )

    return ocr_response.pages


def _delete_uploaded_file(client: Mistral, file_id: str) -> None:
    with suppress(MistralError, NoResponseError, httpx.HTTPError):
        client.files.delete(file_id=file_id)


def _write_markdown(pages: list[OCRPageObject], output_path: Path) -> None:
    image_dir = output_path.parent / f"{output_path.stem}_images"
    image_dir_available = _create_image_dir(image_dir)
    referenced_filenames = _referenced_image_filenames(pages)
    image_counter = 0
    markdown_parts: list[str] = []

    for page_index, page in enumerate(pages):
        if image_dir_available:
            page_markdown, image_counter = _process_page_images(
                page,
                page_index,
                image_dir,
                referenced_filenames,
                image_counter,
            )
        else:
            page_markdown = page.markdown
        markdown_parts.append(page_markdown)

    output_path.write_text("\n\n".join(markdown_parts), encoding="utf-8")


def _create_image_dir(image_dir: Path) -> bool:
    try:
        image_dir.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        click.echo(
            f"Warning: Could not create image directory '{image_dir}': {error}",
            err=True,
        )
        return False

    return True


def _referenced_image_filenames(pages: list[OCRPageObject]) -> set[str]:
    return {
        image_filename
        for page in pages
        for image_filename in IMAGE_REFERENCE_PATTERN.findall(page.markdown)
    }


def _process_page_images(
    page: OCRPageObject,
    page_index: int,
    image_dir: Path,
    referenced_filenames: set[str],
    image_counter: int,
) -> tuple[str, int]:
    page_markdown = page.markdown

    for image_index, image_obj in enumerate(page.images):
        base64_data = image_obj.image_base64
        if not isinstance(base64_data, str):
            continue

        image_filename, markdown_filename = _image_filename(
            page_index,
            image_index,
            image_counter,
            referenced_filenames,
        )

        try:
            image_data = _decode_image(base64_data)
            (image_dir / image_filename).write_bytes(image_data)
        except (Base64DecodeError, OSError) as error:
            click.echo(
                f"Warning: Could not save image '{image_filename}': {error}",
                err=True,
            )
            continue

        image_counter += 1
        original_filename = _original_markdown_filename(
            image_filename,
            markdown_filename,
            referenced_filenames,
        )
        if original_filename is not None:
            page_markdown = _replace_image_link(
                page_markdown,
                original_filename,
                f"{image_dir.name}/{image_filename}",
            )

    return page_markdown, image_counter


def _decode_image(base64_data: str) -> bytes:
    if BASE64_MARKER in base64_data:
        base64_data = base64_data.split(BASE64_MARKER, maxsplit=1)[1]

    return b64decode(base64_data, validate=True)


def _image_filename(
    page_index: int,
    image_index: int,
    image_counter: int,
    referenced_filenames: set[str],
) -> tuple[str, str | None]:
    markdown_filename = _mistral_image_filename(image_counter, referenced_filenames)
    if markdown_filename is None:
        return f"image_p{page_index}_i{image_index}.png", None

    return f"{Path(markdown_filename).stem}.png", markdown_filename


def _mistral_image_filename(
    image_counter: int,
    referenced_filenames: set[str],
) -> str | None:
    expected_prefix = f"img-{image_counter}."
    return next(
        (
            filename
            for filename in referenced_filenames
            if filename.startswith(expected_prefix)
        ),
        None,
    )


def _original_markdown_filename(
    image_filename: str,
    markdown_filename: str | None,
    referenced_filenames: set[str],
) -> str | None:
    if image_filename in referenced_filenames:
        return image_filename
    if markdown_filename in referenced_filenames:
        return markdown_filename

    return None


def _replace_image_link(markdown: str, old_filename: str, new_path: str) -> str:
    return markdown.replace(f"]({old_filename})", f"]({new_path})")


if __name__ == "__main__":
    cli()
