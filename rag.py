"""Cap 4 — RAG de tus documentos (todo LOCAL).

Blue lee tus PDFs, apuntes, Word y .txt/.md, los trocea, los indexa con
embeddings (fastembed, modelo multilingüe pequeño) en una base sqlite-vec, y
después busca por SIGNIFICADO los pasajes relevantes a una pregunta. El cerebro
de Blue redacta la respuesta hablada a partir de esos pasajes (no inventa).

Pensado para lo que estudia Wilmer: normas, apuntes de termo/fluidos/motores,
datasheets, manuales. Cero nube: el modelo corre en CPU local.

Ámbito: como la memoria, lo indexado se liga al PROYECTO ACTIVO (project="" =
global, visible siempre). Así "trabajemos en termo" enfoca tus apuntes de termo.
"""
from __future__ import annotations
import os
import sqlite3
import time

# modelo de embeddings: multilingüe, 384 dim, ~0.22GB (ligero para la RAM)
_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
_DIM = 384
_DB_PATH = os.path.expanduser("~/.config/blue/rag.db")
# caché PERSISTENTE del modelo (no TMPDIR, que es efímero/distinto por proceso)
_CACHE_DIR = os.path.expanduser("~/.cache/blue/fastembed")

# extensiones de archivo que sabemos leer
_EXTS = {".pdf", ".txt", ".md", ".markdown", ".rst", ".docx"}

# troceado
_CHUNK = 900          # caracteres por trozo
_OVERLAP = 150        # solape entre trozos
_MAX_CHUNKS_FILE = 400  # tope por archivo (evita PDFs gigantes)
_OCR_MAX_PAGES = 40     # tope de páginas a pasar por OCR (es lento)

_embedder = None      # singleton perezoso (no carga el modelo hasta usarlo)


# ---------------------------------------------------------------- utilidades
def _active_project() -> str:
    try:
        import workspace
        return workspace.active_key() or ""
    except Exception:
        return ""


def _get_embedder():
    global _embedder
    if _embedder is None:
        from fastembed import TextEmbedding
        os.makedirs(_CACHE_DIR, exist_ok=True)
        _embedder = TextEmbedding(model_name=_MODEL, cache_dir=_CACHE_DIR)
    return _embedder


def _embed(texts: list[str]) -> list[list[float]]:
    emb = _get_embedder()
    return [v.tolist() for v in emb.embed(texts)]


def _db() -> sqlite3.Connection:
    import sqlite_vec
    os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)
    db = sqlite3.connect(_DB_PATH)
    db.enable_load_extension(True)
    sqlite_vec.load(db)
    db.enable_load_extension(False)
    db.execute("""CREATE TABLE IF NOT EXISTS docs(
        id INTEGER PRIMARY KEY, path TEXT, title TEXT, chunk_idx INTEGER,
        text TEXT, project TEXT, mtime REAL)""")
    db.execute("CREATE INDEX IF NOT EXISTS idx_docs_path ON docs(path)")
    db.execute(f"CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks "
               f"USING vec0(embedding float[{_DIM}])")
    return db


def available() -> bool:
    """True si el stack RAG está instalado (fastembed + sqlite-vec)."""
    import importlib.util as u
    return all(u.find_spec(m) for m in ("fastembed", "sqlite_vec"))


# ------------------------------------------------------------ extracción texto
def _ocr_lang() -> str:
    """Idiomas para tesseract: 'spa+eng' si hay datos de español, si no 'eng'."""
    import subprocess
    try:
        langs = subprocess.run(["tesseract", "--list-langs"],
                                capture_output=True, text=True, timeout=10).stdout
    except Exception:
        langs = ""
    return "spa+eng" if "spa" in langs else "eng"


def _ocr_pdf(doc) -> str:
    """OCR de un PDF escaneado: rasteriza cada página (con fitz, que ya tenemos)
    y la pasa por tesseract. Solo se usa como fallback cuando el PDF no trae
    texto. Sin dependencias nuevas de pip: llama al binario tesseract."""
    import subprocess
    import tempfile
    from shutil import which
    if which("tesseract") is None:
        return ""
    import fitz
    lang = _ocr_lang()
    zoom = fitz.Matrix(200 / 72, 200 / 72)   # ~200 DPI, buen punto para OCR
    parts = []
    for i, pg in enumerate(doc):
        if i >= _OCR_MAX_PAGES:
            break
        try:
            pix = pg.get_pixmap(matrix=zoom)
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
                tf.write(pix.tobytes("png"))
                img = tf.name
            try:
                r = subprocess.run(["tesseract", img, "stdout", "-l", lang],
                                   capture_output=True, text=True, timeout=120)
                parts.append(r.stdout)
            finally:
                try:
                    os.unlink(img)
                except OSError:
                    pass
        except Exception:
            continue
    return "\n".join(parts)


def _extract(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext == ".pdf":
            import fitz
            doc = fitz.open(path)
            parts = [pg.get_text() for pg in doc]
            text = "\n".join(parts)
            # casi sin texto => probablemente escaneado: intenta OCR
            if len(text.strip()) < max(80, 20 * doc.page_count):
                ocr = _ocr_pdf(doc)
                if len(ocr.strip()) > len(text.strip()):
                    text = ocr
            doc.close()
            return text
        if ext == ".docx":
            import docx
            d = docx.Document(path)
            return "\n".join(p.text for p in d.paragraphs)
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return ""


def _chunk(text: str) -> list[str]:
    text = " ".join((text or "").split())   # normaliza espacios/saltos
    if not text:
        return []
    out, i, n = [], 0, len(text)
    while i < n and len(out) < _MAX_CHUNKS_FILE:
        end = min(i + _CHUNK, n)
        if end < n:                         # corta en el último espacio del trozo
            sp = text.rfind(" ", i + _CHUNK - _OVERLAP, end)
            if sp > i:
                end = sp
        out.append(text[i:end].strip())
        if end >= n:
            break
        i = end - _OVERLAP
    return [c for c in out if c]


def _gather(path: str) -> list[str]:
    path = os.path.expanduser(path)
    if os.path.isfile(path):
        return [path] if os.path.splitext(path)[1].lower() in _EXTS else []
    files = []
    for root, _, names in os.walk(path):
        for nm in names:
            if os.path.splitext(nm)[1].lower() in _EXTS:
                files.append(os.path.join(root, nm))
    return files


# ----------------------------------------------------------------- indexar
def index(path: str, project: str | None = None) -> str:
    """Indexa un archivo o carpeta. Salta archivos ya indexados sin cambios."""
    if not available():
        return ("Aún no tengo instalado el lector de documentos, Wilmer.")
    files = _gather(path)
    if not files:
        return f"No encontré documentos legibles en {path}."
    proj = _active_project() if project is None else project
    db = _db()
    indexed, skipped, chunks_total = 0, 0, 0
    for fp in files:
        try:
            mtime = os.path.getmtime(fp)
        except OSError:
            continue
        row = db.execute("SELECT mtime FROM docs WHERE path=? LIMIT 1",
                         (fp,)).fetchone()
        if row and abs(row[0] - mtime) < 1.0:        # ya indexado, sin cambios
            skipped += 1
            continue
        # reindexar: borra trozos viejos (de vec y docs) de ese archivo
        old = db.execute("SELECT id FROM docs WHERE path=?", (fp,)).fetchall()
        for (oid,) in old:
            db.execute("DELETE FROM vec_chunks WHERE rowid=?", (oid,))
        db.execute("DELETE FROM docs WHERE path=?", (fp,))
        pieces = _chunk(_extract(fp))
        if not pieces:
            continue
        vecs = _embed(pieces)
        title = os.path.basename(fp)
        import sqlite_vec
        for idx, (txt, vec) in enumerate(zip(pieces, vecs)):
            cur = db.execute(
                "INSERT INTO docs(path,title,chunk_idx,text,project,mtime) "
                "VALUES(?,?,?,?,?,?)", (fp, title, idx, txt, proj, mtime))
            db.execute("INSERT INTO vec_chunks(rowid,embedding) VALUES(?,?)",
                       (cur.lastrowid, sqlite_vec.serialize_float32(vec)))
            chunks_total += 1
        indexed += 1
    db.commit()
    db.close()
    scope = "global" if not proj else f"el proyecto {proj}"
    if indexed == 0 and skipped:
        return f"Tus {skipped} documentos ya estaban al día en {scope}, Wilmer."
    extra = f" ({skipped} ya estaban al día)" if skipped else ""
    return (f"Listo: indexé {indexed} documento(s), {chunks_total} fragmentos "
            f"en {scope}{extra}.")


# ----------------------------------------------------------------- buscar
def search(query: str, k: int = 5, project: str | None = None) -> str:
    """Busca por significado y devuelve los pasajes relevantes con su fuente.
    El cerebro de Blue redacta la respuesta a partir de esto (no inventa)."""
    if not available():
        return "Aún no tengo el lector de documentos instalado, Wilmer."
    q = (query or "").strip()
    if not q:
        return "¿Sobre qué quieres que busque en tus documentos?"
    try:
        db = _db()
    except Exception as e:
        return f"No pude abrir el índice de documentos: {str(e)[:120]}"
    if not db.execute("SELECT 1 FROM docs LIMIT 1").fetchone():
        db.close()
        return ("No tienes documentos indexados todavía. Dime qué carpeta o "
                "archivo indexar y lo agrego.")
    proj = _active_project() if project is None else project
    import sqlite_vec
    qv = sqlite_vec.serialize_float32(_embed([q])[0])
    # sobre-pedimos (KNN con 'k=?' en la tabla vec sola) y luego filtramos por
    # ámbito (global + proyecto activo). sqlite-vec exige 'k=?', no LIMIT.
    rows = db.execute(
        "SELECT d.id, v.distance, d.title, d.text, d.project FROM ("
        "  SELECT rowid, distance FROM vec_chunks "
        "  WHERE embedding MATCH ? AND k = ?) v "
        "JOIN docs d ON d.id = v.rowid ORDER BY v.distance",
        (qv, max(k * 4, 16))).fetchall()
    db.close()
    hits = [r for r in rows if (not r[4]) or r[4] == proj][:k]
    if not hits:
        return ("No encontré nada relevante en tus documentos sobre eso, Wilmer.")
    out = ["PASAJES RELEVANTES de los documentos de Wilmer (responde a partir de "
           "esto, en español y hablado; cita el documento; si no alcanza, dilo):"]
    for _, dist, title, text, _p in hits:
        snippet = text if len(text) <= 600 else text[:600] + "…"
        out.append(f"\n[{title}] {snippet}")
    return "\n".join(out)


def inventory() -> list[dict]:
    """Documentos indexados: [{title, path, project, chunks}]. Solo lee la BD,
    NO carga el modelo de embeddings (sirve para pintar el panel web barato)."""
    if not available():
        return []
    try:
        db = _db()
    except Exception:
        return []
    rows = db.execute(
        "SELECT path, title, project, COUNT(*) FROM docs "
        "GROUP BY path ORDER BY project, title").fetchall()
    db.close()
    return [{"path": p, "title": t, "project": pr or "", "chunks": c}
            for (p, t, pr, c) in rows]


def stats() -> str:
    """Cuántos documentos/fragmentos hay indexados (por ámbito actual)."""
    if not available():
        return "El lector de documentos no está instalado."
    db = _db()
    proj = _active_project()
    n_files = db.execute(
        "SELECT COUNT(DISTINCT path) FROM docs WHERE project='' OR project=?",
        (proj,)).fetchone()[0]
    n_ch = db.execute(
        "SELECT COUNT(*) FROM docs WHERE project='' OR project=?",
        (proj,)).fetchone()[0]
    db.close()
    return f"Tienes {n_files} documento(s) indexados ({n_ch} fragmentos)."
