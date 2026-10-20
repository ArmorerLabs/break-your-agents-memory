"""The workshop notebook: valid nbformat, compilable cells, workshop shape.

The notebook is the hands-on hour's source of truth, so CI guards it like
code: every code cell must compile as plain Python (no IPython magics —
that is what lets the same file run locally, in Colab, and in this test),
and the cells the facilitators rely on must stay present.
"""

from __future__ import annotations

import json
from pathlib import Path

NOTEBOOK = Path(__file__).resolve().parent.parent / "notebooks" / "workshop.ipynb"


def _load() -> dict:
    return json.loads(NOTEBOOK.read_text())


def test_notebook_is_valid_nbformat_with_python_kernel():
    nb = _load()
    assert nb["nbformat"] == 4
    assert nb["metadata"]["kernelspec"]["name"] == "python3"
    ids = [c["id"] for c in nb["cells"]]
    assert len(ids) == len(set(ids)), "cell ids must be unique"


def test_every_code_cell_compiles_as_plain_python():
    nb = _load()
    code_cells = [c for c in nb["cells"] if c["cell_type"] == "code"]
    assert len(code_cells) >= 10
    for cell in code_cells:
        source = "".join(cell["source"]) if isinstance(cell["source"], list) else cell["source"]
        compile(source, cell["id"], "exec")  # raises SyntaxError on magics/broken code


def test_workshop_shape_markers_present():
    nb = _load()
    full_text = "\n".join("".join(c["source"]) if isinstance(c["source"], list) else c["source"] for c in nb["cells"])
    # Colab bootstrap + local root detection
    assert '"google.colab" in sys.modules' in full_text
    assert "find_repo_root" in full_text
    # facilitator checkpoints 0-4
    for checkpoint in ["Checkpoint 0", "Checkpoint 1", "Checkpoint 2", "Checkpoint 3", "Checkpoint 4"]:
        assert checkpoint in full_text, checkpoint
    # the exercise: editable custom defense written from the notebook
    assert "CUSTOM_DEFENSE_CODE" in full_text
    assert "lab/defenses/custom.py" in full_text
    # offline-first, live optional and guarded
    assert '"--mode", "replay"' in full_text
    assert "RUN_LIVE = False" in full_text
