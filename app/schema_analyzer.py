"""
Schema Analyzer.

Given a live connection to a target database, extracts tables, columns,
data types, primary keys and foreign keys using SQLAlchemy's Inspector
(dialect-agnostic -- works the same for SQLite and PostgreSQL).
"""
from dataclasses import dataclass, field
from typing import List, Dict

from sqlalchemy import inspect, Engine


@dataclass
class ColumnInfo:
    name: str
    data_type: str
    is_primary_key: bool = False
    is_foreign_key: bool = False
    foreign_key_ref: str = ""


@dataclass
class TableInfo:
    name: str
    columns: List[ColumnInfo] = field(default_factory=list)

    def as_prompt_block(self) -> str:
        """Render this table as a compact block for the LLM prompt."""
        lines = [f"TABLE {self.name} ("]
        for col in self.columns:
            tags = []
            if col.is_primary_key:
                tags.append("PK")
            if col.is_foreign_key:
                tags.append(f"FK -> {col.foreign_key_ref}")
            tag_str = f"  -- {', '.join(tags)}" if tags else ""
            lines.append(f"  {col.name} {col.data_type}{tag_str}")
        lines.append(")")
        return "\n".join(lines)


def extract_schema(engine: Engine) -> Dict[str, TableInfo]:
    """Returns {table_name: TableInfo} for every table in the target database."""
    inspector = inspect(engine)
    tables: Dict[str, TableInfo] = {}

    for table_name in inspector.get_table_names():
        pk_cols = set(inspector.get_pk_constraint(table_name).get("constrained_columns") or [])

        fk_map = {}
        for fk in inspector.get_foreign_keys(table_name):
            for local_col, remote_col in zip(fk["constrained_columns"], fk["referred_columns"]):
                fk_map[local_col] = f"{fk['referred_table']}.{remote_col}"

        table_info = TableInfo(name=table_name)
        for col in inspector.get_columns(table_name):
            table_info.columns.append(
                ColumnInfo(
                    name=col["name"],
                    data_type=str(col["type"]),
                    is_primary_key=col["name"] in pk_cols,
                    is_foreign_key=col["name"] in fk_map,
                    foreign_key_ref=fk_map.get(col["name"], ""),
                )
            )
        tables[table_name] = table_info

    return tables


def select_relevant_tables(question: str, tables: Dict[str, TableInfo], max_tables: int = 6) -> Dict[str, TableInfo]:
    """
    Lightweight schema retrieval: instead of sending the ENTIRE schema to
    the LLM on every request, keep only tables whose name or column names
    are lexically related to the question. This keeps prompts small and is
    the "Relevant tables -> Relevant columns -> LLM" step from the design.

    This is a simple, explainable baseline (token overlap). For the report,
    a natural upgrade path is swapping this for embedding similarity
    (e.g. sentence-transformers) between the question and each table's
    schema text -- the interface (question, tables -> subset of tables)
    stays identical, so it's a drop-in replacement.
    """
    if len(tables) <= max_tables:
        return tables

    question_tokens = set(_tokenize(question))
    scored = []
    for name, info in tables.items():
        table_tokens = set(_tokenize(name))
        for col in info.columns:
            table_tokens.update(_tokenize(col.name))
        overlap = len(question_tokens & table_tokens)
        scored.append((overlap, name))

    scored.sort(reverse=True)
    keep = {name for _, name in scored[:max_tables]}
    # Always keep at least one table so the prompt isn't empty.
    if not keep:
        keep = set(list(tables.keys())[:max_tables])

    return {name: tables[name] for name in tables if name in keep}


def _tokenize(text: str) -> List[str]:
    return [t.lower() for t in "".join(c if c.isalnum() else " " for c in text).split()]


def schema_to_prompt(tables: Dict[str, TableInfo]) -> str:
    return "\n\n".join(t.as_prompt_block() for t in tables.values())
