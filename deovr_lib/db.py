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
    region TEXT NOT NULL DEFAULT 'western',
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
            self._migrate_schema(conn)
            self._ensure_fts(conn)
            self._reclassify_movies(conn)

    def _migrate_schema(self, conn: sqlite3.Connection) -> None:
        cols = {str(r[1]) for r in conn.execute("PRAGMA table_info(movies)").fetchall()}
        if "region" not in cols:
            conn.execute(
                "ALTER TABLE movies ADD COLUMN region TEXT NOT NULL DEFAULT 'western'"
            )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_movies_region ON movies(region)"
        )

    def _reclassify_movies(self, conn: sqlite3.Connection) -> None:
        """用已入库 genres/code 回填 kind、region（无需重扫文件）。"""
        from .classify import detect_kind, detect_region

        # 分类规则变更时递增；已达版本则跳过，避免每次启动全表 UPDATE
        CLASSIFY_VER = 3
        ver = int(conn.execute("PRAGMA user_version").fetchone()[0] or 0)
        if ver >= CLASSIFY_VER:
            return

        rows = conn.execute(
            "SELECT id, code, title, folder_name, strm_path, studio FROM movies"
        ).fetchall()
        for r in rows:
            mid = int(r["id"])
            genres = [
                x["name"]
                for x in conn.execute(
                    """SELECT g.name FROM genres g
                       JOIN movie_genres mg ON mg.genre_id=g.id
                       WHERE mg.movie_id=?""",
                    (mid,),
                ).fetchall()
            ]
            kind = detect_kind(
                genres=genres,
                title=r["title"] or "",
                path=r["strm_path"] or "",
                studio=r["studio"] or "",
            )
            region = detect_region(
                code=r["code"] or "",
                title=r["title"] or "",
                folder=r["folder_name"] or "",
                path=r["strm_path"] or "",
            )
            conn.execute(
                "UPDATE movies SET kind=?, region=? WHERE id=?",
                (kind, region, mid),
            )
        conn.execute(f"PRAGMA user_version={CLASSIFY_VER}")

    def _fts_sql_ok(self, sql: str) -> bool:
        """普通（非 contentless）+ trigram 才允许 DELETE/UPDATE。"""
        s = (sql or "").lower().replace(" ", "")
        if "trigram" not in (sql or "").lower():
            return False
        if "content=''" in s or 'content=""' in s or "contentless" in s:
            return False
        return True

    def _rebuild_fts(self, conn: sqlite3.Connection) -> None:
        conn.execute("DROP TABLE IF EXISTS movies_fts")
        conn.execute(
            """CREATE VIRTUAL TABLE movies_fts USING fts5(
                title, plot, code, studio, actors, genres,
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

    def _ensure_fts(self, conn: sqlite3.Connection) -> None:
        """Ensure FTS is updatable trigram index; migrate old contentless tables."""
        try:
            row = conn.execute(
                "SELECT sql FROM sqlite_master WHERE name='movies_fts'"
            ).fetchone()
            sql = (row[0] or "") if row else ""
            if sql and self._fts_sql_ok(sql):
                return
            self._rebuild_fts(conn)
        except Exception:
            try:
                self._rebuild_fts(conn)
            except Exception:
                pass

    def _fts_delete(self, conn: sqlite3.Connection, mid: int) -> None:
        """Delete FTS row; compatible with legacy contentless tables."""
        try:
            conn.execute("DELETE FROM movies_fts WHERE rowid=?", (mid,))
            return
        except sqlite3.OperationalError:
            pass
        # contentless FTS5: special delete command
        try:
            conn.execute(
                "INSERT INTO movies_fts(movies_fts, rowid) VALUES('delete', ?)",
                (mid,),
            )
            return
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute(
                """INSERT INTO movies_fts(
                       movies_fts, rowid, title, plot, code, studio, actors, genres
                   ) VALUES('delete', ?, '', '', '', '', '', '')""",
                (mid,),
            )
        except sqlite3.OperationalError:
            # 彻底重建为可更新索引后再删
            self._rebuild_fts(conn)
            conn.execute("DELETE FROM movies_fts WHERE rowid=?", (mid,))

    def _fts_upsert(
        self,
        conn: sqlite3.Connection,
        mid: int,
        *,
        title: str,
        plot: str,
        code: str,
        studio: str,
        actors: str,
        genres: str,
    ) -> None:
        self._fts_delete(conn, mid)
        try:
            conn.execute(
                """INSERT INTO movies_fts(rowid, title, plot, code, studio, actors, genres)
                   VALUES(?,?,?,?,?,?,?)""",
                (mid, title, plot, code, studio, actors, genres),
            )
        except sqlite3.IntegrityError:
            # rowid 仍在：重建后重试
            self._rebuild_fts(conn)
            conn.execute("DELETE FROM movies_fts WHERE rowid=?", (mid,))
            conn.execute(
                """INSERT INTO movies_fts(rowid, title, plot, code, studio, actors, genres)
                   VALUES(?,?,?,?,?,?,?)""",
                (mid, title, plot, code, studio, actors, genres),
            )

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
        region: str = "western",
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
        region = (region or "western").lower()
        if region not in ("jp", "western"):
            region = "western"
        with self.session() as conn:
            existing = conn.execute(
                "SELECT id FROM movies WHERE strm_path=?", (strm_path,)
            ).fetchone()
            if existing:
                mid = int(existing["id"])
                conn.execute(
                    """UPDATE movies SET
                        library_id=?, code=?, title=?, plot=?, studio=?, year=?,
                        aired=?, rating=?, runtime=?, kind=?, region=?, strm_url=?,
                        poster_path=?, nfo_path=?, nfo_mtime=?, strm_mtime=?,
                        folder_name=?, updated_at=datetime('now')
                    WHERE id=?""",
                    (
                        library_id, code, title, plot, studio, year,
                        aired, rating, runtime, kind, region, strm_url,
                        poster_path, nfo_path, nfo_mtime, strm_mtime,
                        folder_name, mid,
                    ),
                )
                conn.execute("DELETE FROM movie_actors WHERE movie_id=?", (mid,))
                conn.execute("DELETE FROM movie_genres WHERE movie_id=?", (mid,))
            else:
                cur = conn.execute(
                    """INSERT INTO movies(
                        library_id, code, title, plot, studio, year, aired, rating,
                        runtime, kind, region, strm_path, strm_url, poster_path, nfo_path,
                        nfo_mtime, strm_mtime, folder_name
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        library_id, code, title, plot, studio, year, aired, rating,
                        runtime, kind, region, strm_path, strm_url, poster_path, nfo_path,
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

            self._fts_upsert(
                conn,
                mid,
                title=title or "",
                plot=plot or "",
                code=code or "",
                studio=studio or "",
                actors=" ".join(actors),
                genres=" ".join(genres),
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
                    self._fts_delete(conn, mid)
                    conn.execute("DELETE FROM movies WHERE id=?", (mid,))
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
                {"id": int(r["id"]), "name": r["name"]}
                for r in conn.execute(
                    """SELECT g.id, g.name FROM genres g
                       JOIN movie_genres mg ON mg.genre_id=g.id
                       WHERE mg.movie_id=? ORDER BY g.name""",
                    (movie_id,),
                ).fetchall()
            ]
            return movie

    def _build_movie_filters(
        self,
        *,
        q: str = "",
        actor: str = "",
        genre: str = "",
        studio: str = "",
        kind: str = "",
        region: str = "",
        library_id: int | None = None,
        year: int | None = None,
        hide_strm_without_nfo_poster: bool = False,
        skip: frozenset[str] | set[str] | None = None,
    ) -> tuple[list[str], list[str], list[Any]]:
        """返回 (joins, where, params)。skip 可排除 actor/genre/studio 自身筛选。"""
        skip = set(skip or ())
        where: list[str] = ["1=1"]
        params: list[Any] = []
        joins: list[str] = []

        if q.strip():
            token = " ".join(t for t in q.strip().replace('"', " ").split() if t)
            if token:
                # Quote for FTS5 so '-' in codes like TT-1234 is not NOT-operator
                fts_q = '"' + token.replace('"', "") + '"'
                where.append(
                    """(
                        m.id IN (SELECT rowid FROM movies_fts WHERE movies_fts MATCH ?)
                        OR m.title LIKE ? OR m.code LIKE ? OR IFNULL(m.studio,'') LIKE ?
                    )"""
                )
                like = f"%{token}%"
                params.extend([fts_q, like, like, like])

        if actor and "actor" not in skip:
            joins.append(
                "JOIN movie_actors ma ON ma.movie_id=m.id "
                "JOIN actors a ON a.id=ma.actor_id"
            )
            where.append("a.name=?")
            params.append(actor)

        if genre and "genre" not in skip:
            joins.append(
                "JOIN movie_genres mg ON mg.movie_id=m.id "
                "JOIN genres g ON g.id=mg.genre_id"
            )
            where.append("g.name=?")
            params.append(genre)

        if studio and "studio" not in skip:
            where.append("m.studio=?")
            params.append(studio)
        if kind:
            where.append("m.kind=?")
            params.append(kind)
        if region:
            where.append("m.region=?")
            params.append(region)
        if library_id:
            where.append("m.library_id=?")
            params.append(library_id)
        if year:
            where.append("m.year=?")
            params.append(year)
        if hide_strm_without_nfo_poster:
            where.append(
                """(
                    LOWER(IFNULL(m.strm_path,'')) NOT LIKE '%.strm'
                    OR (
                        IFNULL(m.poster_path,'') != ''
                        AND IFNULL(m.nfo_path,'') != ''
                    )
                )"""
            )
        return joins, where, params

    def search_movies(
        self,
        *,
        q: str = "",
        actor: str = "",
        genre: str = "",
        studio: str = "",
        kind: str = "",
        region: str = "",
        library_id: int | None = None,
        year: int | None = None,
        sort: str = "updated",
        page: int = 1,
        page_size: int = 48,
        hide_strm_without_nfo_poster: bool = False,
    ) -> dict[str, Any]:
        joins, where, params = self._build_movie_filters(
            q=q,
            actor=actor,
            genre=genre,
            studio=studio,
            kind=kind,
            region=region,
            library_id=library_id,
            year=year,
            hide_strm_without_nfo_poster=hide_strm_without_nfo_poster,
        )

        order = {
            "title": "m.title COLLATE NOCASE ASC",
            "year": "CASE WHEN m.year IS NULL THEN 1 ELSE 0 END, m.year DESC, m.title ASC",
            "rating": "CASE WHEN m.rating IS NULL THEN 1 ELSE 0 END, m.rating DESC",
            "code": "m.code ASC",
            "updated": "m.updated_at DESC",
            "aired": "m.aired DESC",
        }.get(sort, "m.updated_at DESC")

        join_sql = " ".join(dict.fromkeys(joins))
        where_sql = " AND ".join(where)
        page = max(1, page)
        page_size = max(1, min(page_size, 200))
        offset = (page - 1) * page_size

        with self.session() as conn:
            count_sql = f"SELECT COUNT(DISTINCT m.id) FROM movies m {join_sql} WHERE {where_sql}"
            total = int(conn.execute(count_sql, params).fetchone()[0])
            list_sql = f"""
                SELECT DISTINCT m.id, m.code, m.title, m.studio, m.year, m.rating,
                       m.runtime, m.kind, m.region, m.poster_path, m.library_id, m.aired,
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

    def facet_actors(
        self,
        limit: int = 200,
        *,
        q: str = "",
        kind: str = "",
        region: str = "",
        library_id: int | None = None,
        genre: str = "",
        studio: str = "",
        hide_strm_without_nfo_poster: bool = False,
    ) -> list[dict[str, Any]]:
        joins, where, params = self._build_movie_filters(
            q=q,
            kind=kind,
            region=region,
            library_id=library_id,
            genre=genre,
            studio=studio,
            hide_strm_without_nfo_poster=hide_strm_without_nfo_poster,
            skip={"actor"},
        )
        join_sql = " ".join(dict.fromkeys(joins))
        where_sql = " AND ".join(where)
        with self.session() as conn:
            rows = conn.execute(
                f"""SELECT a.id, a.name, COUNT(DISTINCT m.id) AS cnt,
                          (SELECT m2.id FROM movies m2
                           JOIN movie_actors ma2 ON ma2.movie_id=m2.id
                           WHERE ma2.actor_id=a.id AND m2.poster_path IS NOT NULL
                             AND m2.poster_path != ''
                           ORDER BY m2.updated_at DESC LIMIT 1) AS sample_id
                   FROM actors a
                   JOIN movie_actors ma ON ma.actor_id=a.id
                   JOIN movies m ON m.id=ma.movie_id
                   {join_sql}
                   WHERE {where_sql}
                   GROUP BY a.id ORDER BY cnt DESC, a.name LIMIT ?""",
                [*params, limit],
            ).fetchall()
            return [dict(r) for r in rows]

    def facet_genres(
        self,
        limit: int = 200,
        *,
        q: str = "",
        kind: str = "",
        region: str = "",
        library_id: int | None = None,
        actor: str = "",
        studio: str = "",
        hide_strm_without_nfo_poster: bool = False,
    ) -> list[dict[str, Any]]:
        joins, where, params = self._build_movie_filters(
            q=q,
            kind=kind,
            region=region,
            library_id=library_id,
            actor=actor,
            studio=studio,
            hide_strm_without_nfo_poster=hide_strm_without_nfo_poster,
            skip={"genre"},
        )
        join_sql = " ".join(dict.fromkeys(joins))
        where_sql = " AND ".join(where)
        with self.session() as conn:
            rows = conn.execute(
                f"""SELECT g.id, g.name, COUNT(DISTINCT m.id) AS cnt,
                          (SELECT m2.id FROM movies m2
                           JOIN movie_genres mg2 ON mg2.movie_id=m2.id
                           WHERE mg2.genre_id=g.id AND m2.poster_path IS NOT NULL
                             AND m2.poster_path != ''
                           ORDER BY m2.updated_at DESC LIMIT 1) AS sample_id
                   FROM genres g
                   JOIN movie_genres mg ON mg.genre_id=g.id
                   JOIN movies m ON m.id=mg.movie_id
                   {join_sql}
                   WHERE {where_sql}
                   GROUP BY g.id ORDER BY cnt DESC, g.name LIMIT ?""",
                [*params, limit],
            ).fetchall()
            return [dict(r) for r in rows]

    def genre_name(self, genre_id: int) -> str | None:
        with self.session() as conn:
            row = conn.execute("SELECT name FROM genres WHERE id=?", (genre_id,)).fetchone()
            return row["name"] if row else None

    def actor_name(self, actor_id: int) -> str | None:
        with self.session() as conn:
            row = conn.execute("SELECT name FROM actors WHERE id=?", (actor_id,)).fetchone()
            return row["name"] if row else None

    def facet_studios(
        self,
        limit: int = 200,
        *,
        q: str = "",
        kind: str = "",
        region: str = "",
        library_id: int | None = None,
        actor: str = "",
        genre: str = "",
        hide_strm_without_nfo_poster: bool = False,
    ) -> list[dict[str, Any]]:
        joins, where, params = self._build_movie_filters(
            q=q,
            kind=kind,
            region=region,
            library_id=library_id,
            actor=actor,
            genre=genre,
            hide_strm_without_nfo_poster=hide_strm_without_nfo_poster,
            skip={"studio"},
        )
        join_sql = " ".join(dict.fromkeys(joins))
        where_sql = " AND ".join(where)
        with self.session() as conn:
            rows = conn.execute(
                f"""SELECT m.studio AS name, COUNT(DISTINCT m.id) AS cnt,
                          (SELECT m2.id FROM movies m2
                           WHERE m2.studio=m.studio AND m2.poster_path IS NOT NULL
                             AND m2.poster_path != ''
                           ORDER BY m2.updated_at DESC LIMIT 1) AS sample_id
                   FROM movies m
                   {join_sql}
                   WHERE {where_sql}
                     AND m.studio IS NOT NULL AND m.studio != ''
                   GROUP BY m.studio ORDER BY cnt DESC, m.studio LIMIT ?""",
                [*params, limit],
            ).fetchall()
            return [dict(r) for r in rows]

    def list_for_deovr(
        self,
        *,
        kind: str | None = None,
        region: str | None = None,
        library_id: int | None = None,
        limit: int = 500,
        hide_strm_without_nfo_poster: bool = False,
    ) -> list[dict[str, Any]]:
        where = ["1=1"]
        params: list[Any] = []
        if kind:
            where.append("kind=?")
            params.append(kind)
        if region:
            where.append("region=?")
            params.append(region)
        if library_id:
            where.append("library_id=?")
            params.append(library_id)
        if hide_strm_without_nfo_poster:
            where.append(
                """(
                    LOWER(IFNULL(strm_path,'')) NOT LIKE '%.strm'
                    OR (
                        IFNULL(poster_path,'') != ''
                        AND IFNULL(nfo_path,'') != ''
                    )
                )"""
            )
        params.append(limit)
        with self.session() as conn:
            rows = conn.execute(
                f"""SELECT id, title, runtime, poster_path, kind, region, code
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
            by_region = {
                r["region"]: r["cnt"]
                for r in conn.execute(
                    "SELECT region, COUNT(*) AS cnt FROM movies GROUP BY region"
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
                "by_region": by_region,
                "by_library": by_lib,
            }
