"""Script parser — dispatches by file extension."""

from pathlib import Path
from ..models import Script


def parse_script(file_path: str) -> Script:
    """Parse a screenplay file and return a Script model."""
    ext = Path(file_path).suffix.lower()
    if ext == ".pdf":
        from .pdf_parser import parse_pdf
        return parse_pdf(file_path)
    elif ext == ".fdx":
        raise NotImplementedError("Final Draft (.fdx) parsing not yet implemented")
    elif ext == ".docx":
        raise NotImplementedError("Word (.docx) parsing not yet implemented")
    elif ext == ".txt":
        raise NotImplementedError("Plain text (.txt) parsing not yet implemented")
    else:
        raise ValueError(f"Unsupported file format: {ext}")
