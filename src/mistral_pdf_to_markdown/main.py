import base64
import os
import pathlib
import re
from concurrent.futures import ThreadPoolExecutor

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

        _convert_file(pdf_path, output, api_key)
        click.echo(f"Successfully converted PDF to Markdown: '{output}'")
        return True
    except Exception as e:
        click.echo(f"An error occurred: {e}", err=True)
        return False

@cli.command()
@click.argument('directory_path', type=click.Path(exists=True, file_okay=False, dir_okay=True))
@click.option('--output-dir', '-o', type=click.Path(file_okay=False), help='Output directory for markdown files. Defaults to same directory as input.')
@click.option('--api-key', envvar='MISTRAL_API_KEY', help='Mistral API Key. Can also be set via MISTRAL_API_KEY environment variable.')
@click.option('--max-workers', '-w', type=int, default=2, help='Maximum number of concurrent conversions. Default is 2.')
def convert_dir(directory_path, output_dir, api_key, max_workers):
    """Converts all PDF files in a directory to Markdown."""
    load_dotenv()

    if not api_key:
        api_key = os.getenv('MISTRAL_API_KEY')

    if not api_key:
        click.echo("Error: Mistral API Key not found. Set MISTRAL_API_KEY environment variable or use --api-key option.", err=True)
        return


    if not output_dir:
        output_dir = directory_path
    else:

        os.makedirs(output_dir, exist_ok=True)


    pdf_files = []
    for file in os.listdir(directory_path):
        if file.lower().endswith('.pdf'):
            pdf_files.append(os.path.join(directory_path, file))

    if not pdf_files:
        click.echo(f"No PDF files found in '{directory_path}'")
        return

    click.echo(f"Found {len(pdf_files)} PDF files to convert")


    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = []
        for pdf_path in pdf_files:

            base_name = os.path.basename(pdf_path)
            output_name = os.path.splitext(base_name)[0] + '.md'
            output_path = os.path.join(output_dir, output_name)
            

            future = executor.submit(
                _convert_file, 
                pdf_path=pdf_path, 
                output=output_path, 
                api_key=api_key
            )
            futures.append((future, pdf_path, output_path))
        

        for future, pdf_path, output_path in futures:
            try:
                future.result()
                click.echo(f"✅ Successfully converted '{pdf_path}' to '{output_path}'")
            except Exception as e:
                click.echo(f"❌ Failed to convert '{pdf_path}': {e}", err=True)


def _convert_file(pdf_path, output, api_key):
    """Internal function to convert a single PDF file to Markdown.
    Used by both convert and convert_dir commands."""
    try:
        client = Mistral(api_key=api_key)


        with open(pdf_path, "rb") as f:
            uploaded_pdf = client.files.upload(
                file={
                    "file_name": os.path.basename(pdf_path),
                    "content": f,
                },
                purpose="ocr"
            )


        signed_url = client.files.get_signed_url(file_id=uploaded_pdf.id)


        ocr_response = client.ocr.process(
            model="mistral-ocr-latest",
            document={
                "type": "document_url",
                "document_url": signed_url.url
            },
            include_image_base64=True
        )


        final_markdown_parts = []
        output_path = pathlib.Path(output)
        image_dir = output_path.parent / (output_path.stem + "_images")
        try:
            image_dir.mkdir(parents=True, exist_ok=True)
        except Exception as mkdir_err:
            click.echo(f"Warning: Could not create image directory '{image_dir}': {mkdir_err}", err=True)

        image_counter = 0
        processed_image_filenames = set()


        for page in ocr_response.pages:
             page_markdown = page.markdown if hasattr(page, 'markdown') else ''

             found_images = re.findall(r"!\[.*?\]\((.*?)\)", page_markdown)
             processed_image_filenames.update(found_images)


        for page_index, page in enumerate(ocr_response.pages):
            page_markdown = page.markdown if hasattr(page, 'markdown') else ''
            images_saved_on_page = 0
            if hasattr(page, 'images') and page.images:
                for img_index, image_obj in enumerate(page.images):
                    if hasattr(image_obj, 'image_base64') and image_obj.image_base64:
                        try:
                            base64_data = image_obj.image_base64
                            if ';base64,' in base64_data:
                                base64_data = base64_data.split(';base64,', 1)[1]

                            image_data = base64.b64decode(base64_data)


                            image_filename = f"image_p{page_index}_i{img_index}.png"
                            potential_markdown_filename = None
                            for fname in processed_image_filenames:
                                if fname.startswith(f"img-{image_counter}."):
                                     potential_markdown_filename = fname
                                     break

                            if potential_markdown_filename:
                                base_name, _ = os.path.splitext(potential_markdown_filename)
                                image_filename = base_name + ".png"
                            
                            image_save_path = image_dir / image_filename
                            relative_image_path = image_dir.name + "/" + image_filename

                            with open(image_save_path, 'wb') as img_file:
                                img_file.write(image_data)
                            image_counter += 1
                            images_saved_on_page += 1


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

                        except Exception as img_err:
                            pass

            final_markdown_parts.append(page_markdown)

        markdown_content = "\n\n".join(final_markdown_parts)

        with open(output, 'w', encoding='utf-8') as outfile:
            outfile.write(markdown_content)


        try:
            client.files.delete(file_id=uploaded_pdf.id)
        except Exception:
            pass

        return True

    except Exception as e:
        raise Exception(f"Error converting {pdf_path}: {str(e)}")


if __name__ == '__main__':
    cli() 