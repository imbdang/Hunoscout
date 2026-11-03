"""i18n key → chữ hiển thị ở mọi ngôn ngữ, đọc từ bản decompile.

Anchor và selector lưu bằng key nên một pattern dùng được cho cả app tiếng Việt lẫn tiếng Anh.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

_KV = re.compile(r'(?:"([\w.$-]+)"|\b([A-Za-z_$][\w$]*))\s*:\s*"((?:[^"\\]|\\.)*)"')


def _unescape(s: str) -> str:
    try:
        return json.loads(f'"{s}"')
    except ValueError:
        return s


class Lexicon:
    def __init__(self, files: dict[str, Path]):
        self.langs: dict[str, dict[str, str]] = {}
        for lang, path in files.items():
            src = path.read_text(encoding="utf-8")
            self.langs[lang] = {(a or b): _unescape(v) for a, b, v in _KV.findall(src)}

    def texts(self, key: str) -> set[str]:
        """Mọi cách hiển thị của `key`. Rỗng nếu key không tồn tại."""
        return {d[key].strip() for d in self.langs.values() if key in d}
