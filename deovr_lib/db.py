from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .config import DEFAULT_DB, ensure_dirs

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS libraries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    path TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT '2d',
    enabled INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS movies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    library_id INTEGER NOT NULL REFERENCES libraries(id) ON DELETE CASCADE,
    code TEXT,
    title TEXT NOT NULL,
    plot TEXT,
    studio TEXT,
    year INTEGER,
    aired TEXT,
    rating REAL,
    runtime INTEGER,
    kind TEXT NOT NULL DEFAULT '2d',
    strm_path TEXT NOT NULL UNIQUE,
    strm_url TEXT,
    poster_path TEXT,
    nfo_path TEXT,
    nfo_mtime REAL,
    strm_mtime REAL,
    folder_name TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS actors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS genres (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS movie_actors (
    movie_id INTEGER NOT NULL REFERENCES movies(id) ON DELETE CASCADE,
    actor_id INTEGER NOT NULL REFERENCES actors(id) ON DELETE CASCADE,
    PRIMARY KEY (movie_id, actor_id)
);

CREATE TABLE IF NOT EXISTS movie_genres (
    movie_id INTEGER NOT NULL REFERENCES movies(id) ON DELETE CASCADE,
    genre_id INTEGER NOT NULL REFERENCES genres(id) ON DELETE CASCADE,
    PRIMARY KEY (movie_id, genre_id)
);

CREATE INDEX IF NOT EXISTS idx_movies_library ON movies(library_id);
CREATE INDEX IF NOT EXISTS idx_movies_code ON movies(code);
CREATE INDEX IF NOT EXISTS idx_movies_studio ON movies(studio);
CREATE INDEX IF NOT EXISTS idx_movies_year ON movies(year);
CREATE INDEX IF NOT EXISTS idx_movies_kind ON movies(kind);
CREATE INDEX IF NOT EXISTS idx_movies_title ON movies(title);
CREATE INDEX IF NOT EXISTS idx_movie_actors_actor ON movie_actors(actor_id);
CREATE INDEX IF NOT EXISTS idx_movie_genres_genre ON movie_genres(genre_id);

CREATE VIRTUAL TABLE IF NOT EXISTS movies_fts USING fts5(
    title, plot, code, studio, actors, genres,
    content='',
    tokenize='trigram'
);
"""


class Database:
    def __init__(self, path: Path | None = None) -> None:
        ensure_dirs()
        self.path = Path(path or DEFAULT_DB)
        self._init()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @contextmanager
    def session(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init(self) -> None:
        with self.session() as conn:
            conn.executescript(SCHEMA)
            self._ensure_fts(conn)

    def _ensure_fts(self, conn: sqlite3.Connection) -> None:
        """Ensure FTS uses trigram (CJK substring); rebuild if needed."""
        try:
            row = conn.execute(
                "SELECT sql FROM sqlite_master WHERE name='movies_fts'"
            ).fetchone()
            sql = (row[0] or "") if row else ""
            if "trigram" in sql.lower():
                return
            conn.execute("DROP TABLE IF EXISTS movies_fts")
            conn.execute(
                """CREATE VIRTUAL TABLE movies_fts USING fts5(
                    title, plot, code, studio, actors, genres,
                    content='',
                    tokenize='trigram'
                )"""
            )
            rows = conn.execute(
                """SELECT m.id, m.title, m.plot, m.code, m.studio,
                          (SELECT group_concat(a.name, ' ') FROM actors a
                           JOIN movie_actors ma ON ma.actor_id=a.id WHERE ma.movie_id=m.id) AS actors,
                          (SELECT group_concat(g.name, ' ') FROM genres g
                           JOIN movie_genres mg ON mg.genre_id=g.id WHERE mg.movie_id=m.id) AS genres
                   FROM movies m"""
            ).fetchall()
            for r in rows:
                conn.execute(
                    """INSERT INTO movies_fts(rowid, title, plot, code, studio, actors, genres)
                       VALUES(?,?,?,?,?,?,?)""",
                    (
                        r["id"],
                        r["title"] or "",
                        r["plot"] or "",
                        r["code"] or "",
                        r["studio"] or "",
                        r["actors"] or "",
                        r["genres"] or "",
                    ),
                )
        except Exception:
            pass

    def upsert_library(self, name: str, path: str, kind: str = "2d") -> int:
        with self.session() as conn:
            row = conn.execute(
                "SELECT id FROM libraries WHERE name=?", (name,)
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE libraries SET path=?, kind=?, enabled=1 WHERE id=?",
                    (path, kind, row["id"]),
                )
                return int(row["id"])
            cur = conn.execute(
                "INSERT INTO libraries(name, path, kind) VALUES(?,?,?)",
                (name, path, kind),
            )
            return int(cur.lastrowid)

    def list_libraries(self) -> list[dict[str, Any]]:
        with self.session() as conn:
            rows = conn.execute(
                "SELECT * FROM libraries WHERE enabled=1 ORDER BY id"
            ).fetchall()
            return [dict(r) for r in rows]

    def get_or_create_actor(self, conn: sqlite3.Connection, name: str) -> int:
        row = conn.execute("SELECT id FROM actors WHERE name=?", (name,)).fetchone()
        if row:
            return int(row["id"])
        cur = conn.execute("INSERT INTO actors(name) VALUES(?)", (name,))
        return int(cur.lastrowid)

    def get_or_create_genre(self, conn: sqlite3.Connection, name: str) -> int:
        row = conn.execute("SELECT id FROM genres WHERE name=?", (name,)).fetchone()
        if row:
            return int(row["id"])
        cur = conn.execute("INSERT INTO genres(name) VALUES(?)", (name,))
        return int(cur.lastrowid)

    def upsert_movie(
        self,
        *,
        library_id: int,
        code: str,
        title: str,
        plot: str,
        studio: str,
        year: int | None,
        aired: str,
        rating: float | None,
        runtime: int | None,
        kind: str,
        strm_path: str,
        strm_url: str,
        poster_path: str | None,
        nfo_path: str | None,
        nfo_mtime: float | None,
        strm_mtime: float | None,
        folder_name: str,
        actors: list[str],
        genres: list[str],
    ) -> int:
        with self.session() as conn:
            existing = conn.execute(
                "SELECT id FROM movies WHERE strm_path=?", (strm_path,)
            ).fetchone()
            if existing:
                mid = int(existing["id"])
                conn.execute(
                    """UPDATE movies SET
                        library_id=?, code=?, title=?, plot=?, studio=?, year=?,
                        aired=?, rating=?, runtime=?, kind=?, strm_url=?,
                        poster_path=?, nfo_path=?, nfo_mtime=?, strm_mtime=?,
                        folder_name=?, updated_at=datetime('now')
                    WHERE id=?""",
                    (
                        library_id, code, title, plot, studio, year,
                        aired, rating, runtime, kind, strm_url,
                        poster_path, nfo_path, nfo_mtime, strm_mtime,
                        folder_name, mid,
                    ),
                )
                conn.execute("DELETE FROM movie_actors WHERE movie_id=?", (mid,))
                conn.execute("DELETE FROM movie_genres WHERE movie_id=?", (mid,))
                conn.execute("DELETE FROM movies_fts WHERE rowid=?", (mid,))
            else:
                cur = conn.execute(
                    """INSERT INTO movies(
                        library_id, code, title, plot, studio, year, aired, rating,
                        runtime, kind, strm_path, strm_url, poster_path, nfo_path,
                        nfo_mtime, strm_mtime, folder_name
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        library_id, code, title, plot, studio, year, aired, rating,
                        runtime, kind, strm_path, strm_url, poster_path, nfo_path,
                        nfo_mtime, strm_mtime, folder_name,
                    ),
                )
                mid = int(cur.lastrowid)

            for a in actors:
                if not a.strip():
                    continue
                aid = self.get_or_create_actor(conn, a.strip())
                conn.execute(
                    "INSERT OR IGNORE INTO movie_actors(movie_id, actor_id) VALUES(?,?)",
                    (mid, aid),
                )
            for g in genres:
                if not g.strip():
                    continue
                gid = self.get_or_create_genre(conn, g.strip())
                conn.execute(
                    "INSERT OR IGNORE INTO movie_genres(movie_id, genre_id) VALUES(?,?)",
                    (mid, gid),
                )

            conn.execute(
                """INSERT INTO movies_fts(rowid, title, plot, code, studio, actors, genres)
                   VALUES(?,?,?,?,?,?,?)""",
                (
                    mid,
                    title or "",
                    plot or "",
                    code or "",
                    studio or "",
                    " ".join(actors),
                    " ".join(genres),
                ),
            )
            return mid

    def remove_missing(self, library_id: int, keep_paths: set[str]) -> int:
        with self.session() as conn:
            rows = conn.execute(
                "SELECT id, strm_path FROM movies WHERE library_id=?",
                (library_id,),
            ).fetchall()
            removed = 0
            for r in rows:
                if r["strm_path"] not in keep_paths:
                    mid = int(r["id"])
                    conn.execute("DELETE FROM movies WHERE id=?", (mid,))
                    conn.execute("DELETE FROM movies_fts WHERE rowid=?", (mid,))
                    removed += 1
            return removed

    def movie_count(self) -> int:
        with self.session() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM movies").fetchone()[0])

    def get_movie(self, movie_id: int) -> dict[str, Any] | None:
        with self.session() as conn:
            row = conn.execute(
                """SELECT m.*, l.name AS library_name, l.path AS library_path
                   FROM movies m JOIN libraries l ON l.id=m.library_id
                   WHERE m.id=?""",
                (movie_id,),
            ).fetchone()
            if not row:
                return None
            movie = dict(row)
            movie["actors"] = [
                r["name"]
                for r in conn.execute(
                    """SELECT a.name FROM actors a
                       JOIN movie_actors ma ON ma.actor_id=a.id
                       WHERE ma.movie_id=? ORDER BY a.name""",
                    (movie_id,),
                ).fetchall()
            ]
            movie["genres"] = [
                r["name"]
                for r in conn.execute(
                    """SELECT g.name FROM genres g
                       JOIN movie_genres mg ON mg.genre_id=g.id
                       WHERE mg.movie_id=? ORDER BY g.name""",
                    (movie_id,),
                ).fetchall()
            ]
            return movie

    def search_movies(
        self,
        *,
        q: str = "",
        actor: str = "",
        genre: str = "",
        studio: str = "",
        kind: str = "",
        library_id: int | None = None,
        year: int | None = None,
        sort: str = "updated",
        page: int = 1,
        page_size: int = 48,
    ) -> dict[str, Any]:
        where: list[str] = ["1=1"]
        params: list[Any] = []
        joins: list[str] = []

        if q.strip():
            token = " ".join(t for t in q.strip().replace('"', " ").split() if t)
            if token:
                # Quote for FTS5 so '-' in codes like SSNI-077 is not NOT-operator
                fts_q = '"' + token.replace('"', "") + '"'
                where.append(
                    """(
                        m.id IN (SELECT rowid FROM movies_fts WHERE movies_fts MATCH ?)
                        OR m.title LIKE ? OR m.code LIKE ? OR IFNULL(m.studio,'') LIKE ?
                    )"""
                )
                like = f"%{token}%"
                params.extend([fts_q, like, like, like])

        if actor:
            joins.append(
                "JOIN movie_actors ma ON ma.movie_id=m.id "
                "JOIN actors a ON a.id=ma.actor_id"
            )
            where.append("a.name=?")
            params.append(actor)

        if genre:
            joins.append(
                "JOIN movie_genres mg ON mg.movie_id=m.id "
                "JOIN genres g ON g.id=mg.genre_id"
            )
            where.append("g.name=?")
            params.append(genre)

        if studio:
            where.append("m.studio=?")
            params.append(studio)
        if kind:
            where.append("m.kind=?")
            params.append(kind)
        if library_id:
            where.append("m.library_id=?")
            params.append(library_id)
        if year:
            where.append("m.year=?")
            params.append(year)

        order = {
            "title": "m.title COLLATE NOCASE ASC",
            "year": "CASE WHEN m.year IS NULL THEN 1 ELSE 0 END, m.year DESC, m.title ASC",
            "rating": "CASE WHEN m.rating IS NULL THEN 1 ELSE 0 END, m.rating DESC",
            "code": "m.code ASC",
            "updated": "m.updated_at DESC",
            "aired": "m.aired DESC",
        }.get(sort, "m.updated_at DESC")

        join_sql = " ".join(dict.fromkeys(joins))  # dedupe
        where_sql = " AND ".join(where)
        page = max(1, page)
        page_size = max(1, min(page_size, 200))
        offset = (page - 1) * page_size

        with self.session() as conn:
            count_sql = f"SELECT COUNT(DISTINCT m.id) FROM movies m {join_sql} WHERE {where_sql}"
            total = int(conn.execute(count_sql, params).fetchone()[0])
            list_sql = f"""
                SELECT DISTINCT m.id, m.code, m.title, m.studio, m.year, m.rating,
                       m.runtime, m.kind, m.poster_path, m.library_id, m.aired,
                       l.name AS library_name
                FROM movies m
                JOIN libraries l ON l.id=m.library_id
                {join_sql}
                WHERE {where_sql}
                ORDER BY {order}
                LIMIT ? OFFSET ?
            """
            rows = conn.execute(list_sql, [*params, page_size, offset]).fetchall()
            items = [dict(r) for r in rows]
            # attach actors briefly
            for item in items:
                item["actors"] = [
                    r["name"]
                    for r in conn.execute(
                        """SELECT a.name FROM actors a
                           JOIN movie_actors ma ON ma.actor_id=a.id
                           WHERE ma.movie_id=? ORDER BY a.name LIMIT 5""",
                        (item["id"],),
                    ).fetchall()
                ]
            return {
                "total": total,
                "page": page,
                "page_size": page_size,
                "pages": max(1, (total + page_size - 1) // page_size),
                "items": items,
            }

    def facet_actors(self, limit: int = 200) -> list[dict[str, Any]]:
        with self.session() as conn:
            rows = conn.execute(
                """SELECT a.name, COUNT(*) AS cnt
                   FROM actors a JOIN movie_actors ma ON ma.actor_id=a.id
                   GROUP BY a.id ORDER BY cnt DESC, a.name LIMIT ?""",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def facet_genres(self, limit: int = 200) -> list[dict[str, Any]]:
        with self.session() as conn:
            rows = conn.execute(
                """SELECT g.name, COUNT(*) AS cnt
                   FROM genres g JOIN movie_genres mg ON mg.genre_id=g.id
                   GROUP BY g.id ORDER BY cnt DESC, g.name LIMIT ?""",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def facet_studios(self, limit: int = 200) -> list[dict[str, Any]]:
        with self.session() as conn:
            rows = conn.execute(
                """SELECT studio AS name, COUNT(*) AS cnt FROM movies
                   WHERE studio IS NOT NULL AND studio != ''
                   GROUP BY studio ORDER BY cnt DESC, studio LIMIT ?""",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def list_for_deovr(
        self, *, kind: str | None = None, library_id: int | None = None, limit: int = 500
    ) -> list[dict[str, Any]]:
        where = ["1=1"]
        params: list[Any] = []
        if kind:
            where.append("kind=?")
            params.append(kind)
        if library_id:
            where.append("library_id=?")
            params.append(library_id)
        params.append(limit)
        with self.session() as conn:
            rows = conn.execute(
                f"""SELECT id, title, runtime, poster_path, kind, code
                    FROM movies WHERE {' AND '.join(where)}
                    ORDER BY updated_at DESC LIMIT ?""",
                params,
            ).fetchall()
            return [dict(r) for r in rows]

    def stats(self) -> dict[str, Any]:
        with self.session() as conn:
            by_kind = {
                r["kind"]: r["cnt"]
                for r in conn.execute(
                    "SELECT kind, COUNT(*) AS cnt FROM movies GROUP BY kind"
                ).fetchall()
            }
            by_lib = [
                dict(r)
                for r in conn.execute(
                    """SELECT l.name, COUNT(m.id) AS cnt
                       FROM libraries l LEFT JOIN movies m ON m.library_id=l.id
                       GROUP BY l.id ORDER BY l.id"""
                ).fetchall()
            ]
            return {
                "movies": self.movie_count(),
                "actors": int(conn.execute("SELECT COUNT(*) FROM actors").fetchone()[0]),
                "genres": int(conn.execute("SELECT COUNT(*) FROM genres").fetchone()[0]),
                "by_kind": by_kind,
                "by_library": by_lib,
            }