#!/usr/bin/env python3
"""Extract paragraph text from a DOCX with only the Python standard library."""

from __future__ import annotations

import argparse
import zipfile
from pathlib import Path
from xml.etree import ElementTree


WORD_NAMESPACE = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def extract_text(document: Path) -> str:
    """Return non-empty Word paragraphs in document order."""
    with zipfile.ZipFile(document) as archive:
        xml = archive.read("word/document.xml")
    root = ElementTree.fromstring(xml)
    paragraphs = []
    for paragraph in root.iter(f"{WORD_NAMESPACE}p"):
        text = "".join(node.text or "" for node in paragraph.iter(f"{WORD_NAMESPACE}t")).strip()
        if text:
            paragraphs.append(text)
    return "\n".join(paragraphs) + ("\n" if paragraphs else "")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("document", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    text = extract_text(args.document)
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
