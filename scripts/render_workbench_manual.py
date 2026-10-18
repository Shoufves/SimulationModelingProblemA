"""Use the packaged DOCX renderer with Word PDF export on Windows.

This machine has no bundled LibreOffice. Only the PDF conversion hook changes;
the skill's renderer still rasterizes and names all QA page PNGs with Poppler.
"""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SKILL = Path.home() / ".codex/plugins/cache/openai-primary-runtime/documents/26.1015.12040/skills/documents"
RUNTIME = Path(sys.executable).resolve().parents[1]
POPPLER = RUNTIME / "native/poppler/Library/bin"


def word_pdf(doc_path, user_profile, convert_tmp_dir, stem, verbose=False):
    output = Path(convert_tmp_dir) / (stem + ".pdf")
    result = subprocess.run([
        "powershell.exe", "-NoProfile", "-File", str(ROOT / "scripts/render_manual_word.ps1"),
        "-InputPath", doc_path, "-OutputPath", str(output),
    ], capture_output=True, text=True, timeout=100)
    if result.returncode or not output.is_file():
        raise RuntimeError(result.stdout + result.stderr)
    return str(output), "Converted in a separate hidden Word instance"


def main():
    if not SKILL.is_dir():
        raise SystemExit("Documents skill path unavailable")
    os.environ["PATH"] = str(POPPLER) + os.pathsep + os.environ["PATH"]
    spec = importlib.util.spec_from_file_location("skill_render_docx", SKILL / "render_docx.py")
    renderer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(renderer)
    renderer.convert_to_pdf = word_pdf
    sys.argv = [
        str(SKILL / "render_docx.py"), str(ROOT / "outputs/manuals/多能源仿真实验台操作手册.docx"),
        "--output_dir", str(ROOT / "tmp/workbench-manual-render"), "--dpi", "150", "--emit_pdf",
    ]
    renderer.main()


if __name__ == "__main__":
    main()
