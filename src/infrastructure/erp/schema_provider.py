"""
ERP schema description for the SQL generator's prompt.

Given only table names, the model picks the right table and then invents the
columns — plausible ones, which is worse than obvious nonsense:

    "stock below reorder level"
    -> SELECT id, sku, name, quantity_on_hand, reorder_level FROM inventory ...
    -> column "name" does not exist

It cannot know a schema it has never been shown. This reads the real one from
information_schema and hands it over, so the generator writes SQL against the
database that actually exists.

Introspected once and cached: the schema does not change between requests, and
paying a round trip per query to discover that would be wasteful.
"""
from __future__ import annotations

from src.observability.structured_logger import get_logger

logger = get_logger(__name__)

_INTROSPECT_SQL = """
SELECT table_name, column_name, data_type
FROM information_schema.columns
WHERE table_schema = 'public'
ORDER BY table_name, ordinal_position
"""

# Postgres type names are verbose and the distinctions the model needs are
# coarse: is it a number it can sum, a date it can filter, or text?
_TYPE_ALIASES = {
    "character varying": "text",
    "character": "text",
    "timestamp with time zone": "timestamp",
    "timestamp without time zone": "timestamp",
    "double precision": "numeric",
    "integer": "int",
    "bigint": "int",
    "boolean": "bool",
}


def _short_type(data_type: str) -> str:
    return _TYPE_ALIASES.get(data_type, data_type)


class ErpSchemaProvider:
    """Describe the ERP tables and columns for use in a prompt.

    Args:
        dsn: PostgreSQL DSN. Empty means no database is configured, in which
            case ``describe()`` returns the bare table list — the generator
            still works, it just has less to go on.
        allowed_tables: restricts the description to tables the generator may
            reference, so the prompt cannot advertise something Stage 2 would
            reject.
    """

    def __init__(self, dsn: str, allowed_tables: tuple[str, ...]) -> None:
        self._dsn = dsn
        self._allowed = tuple(allowed_tables)
        self._cached: str | None = None

    def describe(self) -> str:
        """Return the schema description, introspecting on first use.

        Never raises. A schema lookup that fails degrades to table names —
        worse SQL, but the pipeline keeps answering, and the reason is logged
        rather than surfacing as a failed query.
        """
        if self._cached is not None:
            return self._cached

        self._cached = self._introspect() if self._dsn else self._table_names_only()
        return self._cached

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _table_names_only(self) -> str:
        return ", ".join(self._allowed)

    def _introspect(self) -> str:
        try:
            import psycopg2  # type: ignore

            with psycopg2.connect(self._dsn) as conn, conn.cursor() as cur:
                cur.execute(_INTROSPECT_SQL)
                rows = cur.fetchall()
        # Deliberately broad: a schema lookup is an optimisation for prompt
        # quality, and no failure of it should stop the pipeline answering.
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "sql.schema.introspection_failed",
                error_type=type(exc).__name__,
                error=str(exc)[:200],
            )
            return self._table_names_only()

        columns: dict[str, list[str]] = {}
        for table, column, data_type in rows:
            if table in self._allowed:
                columns.setdefault(table, []).append(f"{column} {_short_type(data_type)}")

        if not columns:
            logger.warning("sql.schema.no_allowed_tables_found")
            return self._table_names_only()

        described = "\n".join(
            f"  {table}({', '.join(cols)})" for table, cols in sorted(columns.items())
        )
        logger.info("sql.schema.introspected", table_count=len(columns))
        return described


__all__ = ["ErpSchemaProvider"]
