"""
SQL Validator -- the critical security layer.

Design goal: never trust the LLM's output. Validation is done with a real
SQL parser (sqlglot), not string/regex matching on keywords, because regex
is trivially bypassed (comments, string literals containing the word
"DROP", alternate casing, etc).

Defense in depth: this module is layer 1 (static analysis). Layer 2 is
running the query through a database role that only has SELECT privileges
(see database.py / README). A generated query should never be able to do
damage even if this validator had a bug.
"""
import re
from dataclasses import dataclass

import sqlglot
from sqlglot import exp

# Statement types we will NEVER allow, regardless of dialect.
#
# Built via getattr() rather than direct attribute access: sqlglot's exact
# set of Expression subclasses has shifted across versions (e.g. whether
# TRUNCATE/ATTACH/GRANT get their own dedicated class or fall back to a
# generic Command node), and a missing name would otherwise raise
# AttributeError at import time and take down the whole app. Any class that
# doesn't exist in the installed sqlglot version is simply skipped here --
# the regex keyword scan at the bottom of validate_sql() is the
# dialect-independent backstop that still catches it either way.
_FORBIDDEN_TYPE_NAMES = (
    "Insert", "Update", "Delete", "Drop", "Alter", "AlterTable", "Create",
    "TruncateTable", "Grant", "Attach", "Command", "Pragma",
)
FORBIDDEN_EXPRESSION_TYPES = tuple(
    cls for cls in (getattr(exp, name, None) for name in _FORBIDDEN_TYPE_NAMES) if cls is not None
)

# Function/keyword names that can read/write the filesystem or exfiltrate
# data even from inside a SELECT, on some dialects (defense against clever
# prompt injections that stay within a single SELECT statement).
BLOCKED_FUNCTIONS = {
    "pg_read_file",
    "pg_read_binary_file",
    "pg_ls_dir",
    "lo_import",
    "lo_export",
    "load_extension",
    "load_file",
    "into outfile",
    "into dumpfile",
}


@dataclass
class ValidationResult:
    is_safe: bool
    reason: str = ""
    normalized_sql: str = ""


def validate_sql(sql: str, dialect: str = "sqlite") -> ValidationResult:
    if not sql or not sql.strip():
        return ValidationResult(False, "Empty query.")

    # Reject stacked/multiple statements outright (e.g. "SELECT 1; DROP TABLE x;")
    try:
        statements = sqlglot.parse(sql, read=dialect)
    except Exception as e:
        return ValidationResult(False, f"SQL failed to parse: {e}")

    statements = [s for s in statements if s is not None]
    if len(statements) != 1:
        return ValidationResult(False, "Only a single SQL statement is allowed per query.")

    statement = statements[0]

    # Must be a SELECT (or a WITH ... SELECT CTE) at the top level.
    if isinstance(statement, exp.With):
        inner = statement.this
    else:
        inner = statement

    if not isinstance(inner, exp.Select):
        return ValidationResult(
            False,
            f"Only read-only SELECT queries are permitted (got {type(inner).__name__}).",
        )

    # Walk the entire AST looking for forbidden node types anywhere nested
    # (e.g. a subquery containing an INSERT is not valid SQL anyway, but a
    # CTE or function call trying to sneak in a write-like clause should
    # still be caught defensively).
    for node in statement.walk():
        node_obj = node[0] if isinstance(node, tuple) else node
        if isinstance(node_obj, FORBIDDEN_EXPRESSION_TYPES):
            return ValidationResult(False, f"Disallowed operation detected: {type(node_obj).__name__}")

        if isinstance(node_obj, exp.Anonymous):
            fname = (node_obj.name or "").lower()
            if fname in BLOCKED_FUNCTIONS:
                return ValidationResult(False, f"Disallowed function call: {fname}")

    normalized = statement.sql(dialect=dialect)

    # Belt-and-suspenders keyword scan on the normalized SQL, in case a
    # dialect quirk produced an AST node type we didn't anticipate above.
    forbidden_keywords = r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|GRANT|ATTACH|EXEC|EXECUTE)\b"
    if re.search(forbidden_keywords, normalized, re.IGNORECASE):
        return ValidationResult(False, "Disallowed keyword detected in generated SQL.")

    return ValidationResult(True, "OK", normalized_sql=normalized)


def enforce_row_limit(sql: str, dialect: str, max_rows: int) -> str:
    """
    Append/adjust a LIMIT clause so a runaway query can't return millions of
    rows. If a LIMIT is already present and smaller than max_rows, leave it.
    """
    try:
        parsed = sqlglot.parse_one(sql, read=dialect)
    except Exception:
        return sql  # validate_sql() should already have rejected this; be safe

    select_node = parsed.this if isinstance(parsed, exp.With) else parsed
    if not isinstance(select_node, exp.Select):
        return sql

    existing_limit = select_node.args.get("limit")
    if existing_limit is not None:
        try:
            current = int(existing_limit.expression.this)
            if current <= max_rows:
                return parsed.sql(dialect=dialect)
        except Exception:
            pass

    select_node.set("limit", exp.Limit(expression=exp.Literal.number(max_rows)))
    return parsed.sql(dialect=dialect)
