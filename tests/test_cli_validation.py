"""CLI validation tests: invalid options must fail cleanly, not traceback."""

from click.testing import CliRunner

from mistral_pdf_to_markdown.main import cli


def test_convert_dir_rejects_zero_max_workers(tmp_path):
    source = tmp_path / "a.pdf"
    source.write_bytes(b"%PDF-1.4 fake")
    result = CliRunner().invoke(
        cli, ["convert-dir", str(tmp_path), "--api-key", "dummy", "--max-workers", "0"]
    )
    assert result.exit_code == 2
    assert "max-workers" in result.output
