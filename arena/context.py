"""Local, project-scoped text retrieval and conversation memory without embedding API costs."""

from pathlib import Path
import re
import sqlite3
import time
import zipfile

from .config import ArenaError
from .tools import MAX_FILE, files


class ContextStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS chunks(path TEXT, first_line INTEGER, text TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS turns(id INTEGER PRIMARY KEY, task TEXT, answer TEXT, created REAL)')

    def connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def index(self, root):
        root = Path(root)
        chunks, count = [], 0
        for path in files(root):
            if path.stat().st_size > MAX_FILE:
                continue
            try:
                text = path.read_text(encoding='utf-8')
            except UnicodeError:
                continue
            if '\0' in text:
                continue
            count += 1
            if count > 3000:
                raise ArenaError('Context index exceeds 3000 text files.')
            lines = text.splitlines()
            for start in range(0, len(lines), 60):
                chunks.append((path.relative_to(root).as_posix(), start + 1, '\n'.join(lines[start:start + 60])[:6000]))
        with self.connect() as db:
            db.execute('DELETE FROM chunks')
            db.executemany('INSERT INTO chunks VALUES (?,?,?)', chunks)
        return {'files': count, 'chunks': len(chunks)}

    def search(self, query, limit=6):
        if not isinstance(query, str) or not query or len(query) > 1000:
            raise ArenaError('Context query must contain 1-1000 characters.')
        terms = list(dict.fromkeys(re.findall(r'[\w]{2,}', query.lower())))[:12]
        if not terms:
            return []
        # Literal matching avoids executing arbitrary FTS syntax supplied by the model.
        with self.connect() as db:
            rows = db.execute('SELECT path, first_line, text FROM chunks').fetchall()
        ranked = []
        for path, line, text in rows:
            lowered = text.lower()
            score = sum(lowered.count(term) + 3 * (term in path.lower()) for term in terms)
            if score:
                ranked.append((score, path, line, text))
        ranked.sort(key=lambda x: (-x[0], x[1], x[2]))
        return [{'source': p, 'first_line': line, 'text': text} for _, p, line, text in ranked[:limit]]

    def remember(self, task, answer):
        with self.connect() as db:
            db.execute('INSERT INTO turns(task,answer,created) VALUES (?,?,?)', (task, answer, time.time()))

    def recent(self, limit=4):
        with self.connect() as db:
            rows = db.execute('SELECT task, answer FROM turns ORDER BY id DESC LIMIT ?', (limit,)).fetchall()
        return [{'task': task[:2000], 'answer': answer[:4000]} for task, answer in rows[::-1]]

    def history_search(self, query):
        if not isinstance(query, str) or not query or len(query) > 1000:
            raise ArenaError('History query must contain 1-1000 characters.')
        terms = set(re.findall(r'\w{3,}', query.lower()))
        with self.connect() as db:
            rows = db.execute('SELECT id,task,answer FROM turns ORDER BY id DESC LIMIT 200').fetchall()
        ranked = sorted(rows, key=lambda row: -sum(term in (row[1] + row[2]).lower() for term in terms))
        return [{'turn': i, 'task': task[:2000], 'answer': answer[:4000]} for i, task, answer in ranked[:3]
                if any(term in (task + answer).lower() for term in terms)]


def read_document(path):
    path = Path(path)
    if path.stat().st_size > 8 * 1024 * 1024:
        raise ArenaError('Document exceeds 8 MiB.')
    if path.suffix.lower() == '.pdf':
        try:
            from pypdf import PdfReader
        except ImportError:
            raise ArenaError('Install PDF support: pip install -e ".[documents]"') from None
        reader = PdfReader(path)
        if reader.is_encrypted:
            raise ArenaError('Encrypted PDFs are not supported.')
        text = '\n'.join((page.extract_text() or '')[:12000] for page in reader.pages[:20])
        note = 'Text extraction only, first 20 pages; scanned PDFs require OCR outside this tool.'
    elif path.suffix.lower() == '.docx':
        import xml.etree.ElementTree as ET
        with zipfile.ZipFile(path) as archive:
            entry = archive.getinfo('word/document.xml')
            if entry.file_size > 4 * 1024 * 1024:
                raise ArenaError('Expanded DOCX text exceeds 4 MiB.')
            xml = ET.fromstring(archive.read(entry))
            text = '\n'.join(node.text or '' for node in xml.iter() if node.tag.endswith('}t'))
        note = 'Text extraction only; formatting, images, and macros are not executed.'
    else:
        text = path.read_text(encoding='utf-8')
        note = 'UTF-8 text'
    return {'path': path.name, 'text': text[:20000], 'truncated': len(text) > 20000, 'note': note}
