# Plan 17 — HTML Clean Reader (R-08)

**Covers**: US-17
**Status**: in-progress

---

## Goal

Implement `HTMLCleanReader` to strip nav/footer/header/script/style from HTML before
indexing, satisfying R-08's "strip nav/footer/script" requirement.

---

## Implementation Steps

### Step 1 — `HTMLCleanReader` class in `src/pipeline/ops/parse.py`

Add before `_get_file_extractor()`:

```python
class HTMLCleanReader(BaseReader):
    _STRIP_TAGS = frozenset({"nav", "footer", "header", "script", "style", "aside"})

    def load_data(self, file: Path, extra_info=None) -> list[Document]:
        from bs4 import BeautifulSoup
        with open(file, encoding="utf-8") as f:
            soup = BeautifulSoup(f, "html.parser")
        for tag in soup.find_all(self._STRIP_TAGS):
            tag.decompose()
        body = soup.find("body") or soup
        text = body.get_text(separator="\n", strip=True)
        metadata = {"file_path": str(file)}
        metadata.update(extra_info or {})
        return [Document(text=text, metadata=metadata)]
```

Imports needed: `BaseReader` from `llama_index.core.readers.base`.

### Step 2 — Replace `HTMLTagReader` in `_get_file_extractor()`

Remove `HTMLTagReader` import; use `HTMLCleanReader` for `.html` and `.htm`.

### Step 3 — Tests in `tests/unit/test_parse_html.py`

- HTML with `<nav>`, `<footer>`, `<script>`, `<style>`, `<aside>`, `<body>` content
- Assert stripped tags not in result text
- Assert body text present
- Assert single Document returned

---

## Files Changed

| File | Change |
|------|--------|
| `src/pipeline/ops/parse.py` | Add `HTMLCleanReader`; replace `HTMLTagReader` |
| `tests/unit/test_parse_html.py` | New test file |
