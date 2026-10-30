"""Every model prompt lives in prompts/<name>.md so it can be edited by hand. Files are read on each use, so an edit
applies to the next request. {{name}} placeholders are filled in; <!-- comments --> are notes for the editor and are
dropped."""
import re
from pathlib import Path

DIR = Path(__file__).resolve().parent.parent / "prompts"


def load(name: str, **values) -> str:
    text = re.sub(r"<!--.*?-->\s*", "", (DIR / f"{name}.md").read_text(), flags=re.S).strip()
    for k, v in values.items():
        text = text.replace("{{" + k + "}}", str(v))
    return text
