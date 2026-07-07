from collections.abc import Iterable, Iterator
from pathlib import Path

def get_pandoc_version() -> str: ...
def convert_file(
    source_file: list[str] | str | Path | Iterator[str],
    to: str,
    format: str | None = ...,
    extra_args: Iterable[str] = ...,
    outputfile: str | Path | None = ...,
    filters: Iterable[str] | None = ...,
    verify_format: bool = ...,
    sandbox: bool = ...,
    cworkdir: str | None = ...,
    sort_files: bool = ...,
) -> str: ...
