from typing import Any

import pdfplumber as pp

# TODO 


def get_pdf_layout(self, filepath: str, page_num: int) -> dict[str, Any]:
    page = page_num - 1

    with pp.open(filepath) as pdf:
        if len(pdf.pages) >= page_num:
            raise Exception(
                f"There are only {len(pdf.pages)} pages in the given document. Path: {filepath}.",
                "Please make sure you are requesting the correct 1-indexed page.",
            )
        page = pdf.pages[page_num - 1]  # pdf plumber is 0-index

        width = page.width
        height = page.height
        bbox = page.bbox

        words = page.extract_words()
        tables = page.extract_tables()

        return {
            "width": width,
            "height": height,
            "bbox": bbox,
            "words": words,
            "tables": tables,
        }
