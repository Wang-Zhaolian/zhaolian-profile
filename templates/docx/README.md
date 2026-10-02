# Word template

`academic_cv_template.docx` stores page size, margins, fonts, and paragraph styles. The generator
loads this file, clears its empty body, and writes the same selected content used by the LaTeX
renderer.

Rebuild it after changing `scripts/build_docx_template.py`:

```powershell
uv run python scripts/build_docx_template.py
```

Keep the template free of personal data.

