"""
Copies the college logo, the student table and the "Guided by" block from the
Jury 1 title slide onto the Jury 2 title slide, at exactly the same positions.

Run after building the deck:

    node presentation/jury2/build_deck.js
    .venv\\Scripts\\python.exe presentation\\jury2\\copy_title_details.py

Copying them from the Jury 1 deck, rather than typing them again, means the
details stay identical in both decks.
"""

import copy
import io
import os

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

HERE = os.path.dirname(os.path.abspath(__file__))

# Enrollment numbers that were wrong in the Jury 1 table. The correct values
# come from the group's Contribution Statement.
CORRECTIONS = {
    "ADT23SOCB0477": "ADT23SOCB0997",   # Saumya Joshi
    "ADT23OSCB0347": "ADT23SOCB1117",   # Siddhant Pawar
}


def correct_table(table):
    """Swap in the corrected numbers, keeping the cell's formatting."""
    for row in table.rows:
        for cell in row.cells:
            for paragraph in cell.text_frame.paragraphs:
                value = paragraph.text.strip()
                if value in CORRECTIONS and paragraph.runs:
                    paragraph.runs[0].text = CORRECTIONS[value]
                    for extra in paragraph.runs[1:]:
                        extra.text = ""
                    print("corrected", value, "->", CORRECTIONS[value])
OLD_DECK = os.path.join(HERE, "..", "jury1", "Chatbot_Long_Term_Memory_Jury1.pptx")
NEW_DECK = os.path.join(HERE, "SentimentAwareChatbot_Jury2.pptx")


def main():
    old_slide = Presentation(OLD_DECK).slides[0]
    new_deck = Presentation(NEW_DECK)
    new_slide = new_deck.slides[0]

    for shape in old_slide.shapes:
        # The college logo: added as a new picture at the same place and size.
        if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
            new_slide.shapes.add_picture(
                io.BytesIO(shape.image.blob),
                shape.left, shape.top, shape.width, shape.height,
            )
            print("copied logo")

        # The student table, and the text box that starts with "Guided by".
        # Neither links to anything else in the file, so a plain copy works.
        elif shape.has_table or (
            shape.has_text_frame and shape.text_frame.text.startswith("Guided by")
        ):
            element = copy.deepcopy(shape._element)

            # Every shape on a slide needs its own id number, otherwise
            # PowerPoint offers to "repair" the file. Give the copy a new one.
            used = [int(n.get("id")) for n in new_slide.shapes._spTree.iter()
                    if n.tag.endswith("}cNvPr")]
            element.xpath(".//p:cNvPr")[0].set("id", str(max(used) + 1))

            new_slide.shapes._spTree.append(element)
            print("copied", "table" if shape.has_table else "guide details")

    for shape in new_slide.shapes:
        if shape.has_table:
            correct_table(shape.table)

    new_deck.save(NEW_DECK)
    print("saved", NEW_DECK)


if __name__ == "__main__":
    main()
