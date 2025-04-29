import base64
import os
import pathlib
import re

import click
from dotenv import load_dotenv
from mistralai import Mistral


@click.group()
def cli():
    """A CLI tool to convert PDF files to Markdown using Mistral OCR."""
    pass

@cli.command()
@click.argument('pdf_path', type=click.Path(exists=True, dir_okay=False))
@click.option('--output', '-o', type=click.Path(dir_okay=False), help='Output markdown file path.')
@click.option('--api-key', envvar='MISTRAL_API_KEY', help='Mistral API Key. Can also be set via MISTRAL_API_KEY environment variable.')
def convert(pdf_path, output, api_key):
    """Converts a PDF file to Markdown."""
    load_dotenv()

    if not api_key:
        api_key = os.getenv('MISTRAL_API_KEY')

    if not api_key:
        click.echo("Error: Mistral API Key not found. Set MISTRAL_API_KEY environment variable or use --api-key option.", err=True)
        return

    if not output:
        output = os.path.splitext(pdf_path)[0] + '.md'

    click.echo(f"Converting '{pdf_path}' to '{output}'...")

    try:
        client = Mistral(api_key=api_key)

        # 1. Upload the file
        click.echo("Uploading PDF...")
        with open(pdf_path, "rb") as f:
            uploaded_pdf = client.files.upload(
                file={
                    "file_name": os.path.basename(pdf_path),
                    "content": f,
                },
                purpose="ocr"
            )
        click.echo(f"File uploaded successfully. File ID: {uploaded_pdf.id}")

        # 2. Get signed URL
        click.echo("Getting signed URL...")
        signed_url = client.files.get_signed_url(file_id=uploaded_pdf.id)
        click.echo("Signed URL obtained.")

        # 3. Process with OCR
        click.echo("Processing with Mistral OCR...")
        ocr_response = client.ocr.process(
            model="mistral-ocr-latest",
            document={
                "type": "document_url",
                "document_url": signed_url.url
            },
            include_image_base64=True
        )
        click.echo("OCR processing complete.")

        # 4. Extract markdown content and save images
        click.echo("Extracting markdown and saving images...")
        final_markdown_parts = []
        output_path = pathlib.Path(output)
        image_dir = output_path.parent / (output_path.stem + "_images")
        try:
            image_dir.mkdir(parents=True, exist_ok=True)
            click.echo(f"Image directory created/ensured: '{image_dir}'")
        except Exception as mkdir_err:
            click.echo(f"Warning: Could not create image directory '{image_dir}': {mkdir_err}", err=True)

        image_counter = 0
        processed_image_filenames = set()

        # First pass: check markdown for image references
        for page in ocr_response.pages:
             page_markdown = page.markdown if hasattr(page, 'markdown') else ''
             # Simple regex to find markdown image syntax ![alt](filename.ext)
             # This helps identify expected image filenames
             found_images = re.findall(r"!\[.*?\]\((.*?)\)", page_markdown)
             processed_image_filenames.update(found_images)

        click.echo(f"Found references to {len(processed_image_filenames)} image filenames in markdown.")

        # Second pass: process pages and save images
        for page_index, page in enumerate(ocr_response.pages):
            page_markdown = page.markdown if hasattr(page, 'markdown') else ''
            images_saved_on_page = 0
            if hasattr(page, 'images') and page.images:
                click.echo(f"  Processing images for page {page_index+1}...")
                for img_index, image_obj in enumerate(page.images):
                    if hasattr(image_obj, 'image_base64') and image_obj.image_base64:
                        try:
                            base64_data = image_obj.image_base64
                            if ';base64,' in base64_data:
                                base64_data = base64_data.split(';base64,', 1)[1]
                                click.echo("    Stripped data URI prefix.")

                            image_data = base64.b64decode(base64_data)

                            # --- Determine filename ---
                            image_filename = f"image_p{page_index}_i{img_index}.png"
                            potential_markdown_filename = None
                            for fname in processed_image_filenames:
                                if fname.startswith(f"img-{image_counter}."):
                                     potential_markdown_filename = fname
                                     break

                            if potential_markdown_filename:
                                base_name, _ = os.path.splitext(potential_markdown_filename)
                                image_filename = base_name + ".png"
                                click.echo(f"    Matched image to markdown reference base name: {base_name} -> {image_filename}")
                            else:
                                click.echo(f"    Using default filename: {image_filename}")

                            image_save_path = image_dir / image_filename
                            relative_image_path = image_dir.name + "/" + image_filename

                            with open(image_save_path, 'wb') as img_file:
                                img_file.write(image_data)
                            image_counter += 1
                            images_saved_on_page += 1

                            # --- Modify markdown to use the correct relative path ---
                            original_filename_in_markdown = None
                            if image_filename in processed_image_filenames:
                                original_filename_in_markdown = image_filename
                            elif potential_markdown_filename in processed_image_filenames:
                                original_filename_in_markdown = potential_markdown_filename

                            if original_filename_in_markdown:
                                old_link_pattern = f"]({original_filename_in_markdown})"
                                new_link_pattern = f"]({relative_image_path})"
                                if old_link_pattern in page_markdown:
                                    page_markdown = page_markdown.replace(old_link_pattern, new_link_pattern)
                                    click.echo(f"    Updated markdown link: {original_filename_in_markdown} -> {relative_image_path}")
                                else:
                                     click.echo(f"    Warning: Could not find markdown link pattern '{old_link_pattern}' to replace.", err=True)
                            # --- End Markdown modification ---

                        except Exception as img_err:
                            click.echo(f"    Warning: Could not process image {img_index} on page {page_index+1}: {img_err}", err=True)

                if images_saved_on_page > 0:
                     click.echo(f"    Saved {images_saved_on_page} image(s) for page {page_index+1}.")


            final_markdown_parts.append(page_markdown)

        markdown_content = "\\n\\n".join(final_markdown_parts)
        click.echo(f"Extracted markdown. Processed {image_counter} images in '{image_dir}'.")

        with open(output, 'w', encoding='utf-8') as outfile:
            outfile.write(markdown_content)

        click.echo(f"Successfully converted PDF to Markdown: '{output}'")

        # 5. Delete the uploaded file
        try:
            client.files.delete(file_id=uploaded_pdf.id)
            click.echo(f"Deleted uploaded file from Mistral: {uploaded_pdf.id}")
        except Exception as delete_err:
            click.echo(f"Warning: Could not delete uploaded file {uploaded_pdf.id}: {delete_err}", err=True)

    except Exception as e:
        click.echo(f"An error occurred: {e}", err=True)

if __name__ == '__main__':
    cli() 