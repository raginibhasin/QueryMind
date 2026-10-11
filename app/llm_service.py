"""
LLM Service -- wraps calls to the Anthropic API for:
  1. Text-to-SQL generation (with schema + conversation history as context)
  2. Plain-English explanation of a generated query

Kept deliberately thin: all safety checks happen afterwards in
sql_validator.py. This module should never be trusted to enforce security
on its own.
"""
import json
import re
from typing import List, Dict, Optional

import anthropic

from app.config import ANTHROPIC_API_KEY, LLM_MODEL

_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None


def _fallback_sql_for_question(question: str, schema_text: str, history: Optional[List[Dict]] = None) -> Dict[str, str]:
    """Generate a safe, deterministic SQL query for common demo questions when the LLM API is unavailable."""
    q = question.lower()

    if "table students" in schema_text.lower() and ("gpa" in q or "grade point" in q):
        return {
            "sql": (
                "SELECT p.program_name, ROUND(AVG(s.gpa), 2) AS average_gpa "
                "FROM programs p JOIN students s ON s.program_id = p.program_id "
                "GROUP BY p.program_name ORDER BY average_gpa DESC"
            ),
            "explanation": "Compares average student GPA across academic programs.",
        }

    if "table students" in schema_text.lower() and any(term in q for term in ("enrollment", "student count", "students by")):
        return {
            "sql": (
                "SELECT p.program_name, COUNT(s.student_id) AS student_count "
                "FROM programs p LEFT JOIN students s ON s.program_id = p.program_id "
                "GROUP BY p.program_name ORDER BY student_count DESC"
            ),
            "explanation": "Counts students in each academic program.",
        }

    if "table courses" in schema_text.lower() and any(term in q for term in ("popular course", "most popular course", "course enrollment", "most enrollments")):
        return {
            "sql": (
                "SELECT c.course_name, COUNT(e.enrollment_id) AS enrollment_count "
                "FROM courses c LEFT JOIN enrollments e ON e.course_id = c.course_id "
                "GROUP BY c.course_name ORDER BY enrollment_count DESC LIMIT 10"
            ),
            "explanation": "Ranks courses by the number of student enrollments.",
        }

    if "table order_items" in schema_text.lower() and any(term in q for term in ("revenue", "sales", "category")):
        return {
            "sql": (
                "SELECT p.category, SUM(oi.quantity * oi.unit_price) AS revenue "
                "FROM products p JOIN order_items oi ON oi.product_id = p.product_id "
                "GROUP BY p.category ORDER BY revenue DESC"
            ),
            "explanation": "Totals order revenue by product category.",
        }

    if "table order_items" in schema_text.lower() and any(term in q for term in ("top selling", "best selling", "popular product")):
        return {
            "sql": (
                "SELECT p.product_name, SUM(oi.quantity) AS units_sold "
                "FROM products p JOIN order_items oi ON oi.product_id = p.product_id "
                "GROUP BY p.product_name ORDER BY units_sold DESC LIMIT 10"
            ),
            "explanation": "Ranks products by total units sold.",
        }

    if "average salary" in q or "avg salary" in q or "salary in each department" in q:
        return {
            "sql": (
                "SELECT d.department_name, AVG(e.salary) AS average_salary "
                "FROM departments d JOIN employees e ON e.department_id = d.department_id "
                "GROUP BY d.department_name ORDER BY average_salary DESC"
            ),
            "explanation": "Calculates the average salary for each department.",
        }

    if "total sales" in q or "sales by" in q or "product category" in q:
        return {
            "sql": (
                "SELECT s.product_category, SUM(s.sale_amount) AS total_sales "
                "FROM sales s GROUP BY s.product_category ORDER BY total_sales DESC"
            ),
            "explanation": "Totals sales by product category.",
        }

    if "highest salary" in q or "salary" in q and "employees" in q:
        return {
            "sql": (
                "SELECT e.first_name, e.last_name, e.salary "
                "FROM employees e ORDER BY e.salary DESC LIMIT 10"
            ),
            "explanation": "Lists employees with the highest salaries.",
        }

    # Generic fallback: inspect schema and do a read-only aggregate query if possible.
    if "department" in schema_text.lower():
        return {
            "sql": "SELECT * FROM departments LIMIT 10",
            "explanation": "Shows sample data from the relevant department table.",
        }

    return {
        "sql": "SELECT 1 AS ok",
        "explanation": "Returns a simple safe placeholder query while the model service is unavailable.",
    }

SQL_SYSTEM_PROMPT = """You are a Text-to-SQL engine inside a product called QueryMind.

Rules:
- Output ONLY a single read-only SQL SELECT statement. Never INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE, or any DDL/DML.
- Use only the tables and columns given in the schema below. Never invent column or table names.
- If the user's question refers to something from earlier in the conversation ("only for 2026", "as a bar chart"), incorporate that context into a complete, standalone SQL query.
- Prefer explicit column names over SELECT *.
- Return your answer as JSON with exactly two keys: "sql" and "explanation".
  "explanation" is one short plain-English sentence describing what the query does.
- Do not wrap the JSON in markdown code fences.
"""


def _build_user_message(question: str, schema_text: str, history: List[Dict]) -> str:
    parts = [f"DATABASE SCHEMA:\n{schema_text}\n"]

    if history:
        parts.append("CONVERSATION SO FAR:")
        for turn in history:
            parts.append(f'User asked: "{turn["question"]}"')
            parts.append(f"Generated SQL: {turn['sql']}")
        parts.append("")

    parts.append(f'CURRENT QUESTION: "{question}"')
    parts.append("\nRespond with JSON only: {\"sql\": \"...\", \"explanation\": \"...\"}")
    return "\n".join(parts)


def generate_sql(question: str, schema_text: str, history: Optional[List[Dict]] = None) -> Dict[str, str]:
    """
    Returns {"sql": "...", "explanation": "..."}.
    Uses the Anthropic API when available, but falls back to a deterministic SQL
    template for common demo questions if the API key is missing or billing is exhausted.
    """
    if _client is None:
        return _fallback_sql_for_question(question, schema_text, history)

    history = history or []
    user_message = _build_user_message(question, schema_text, history)

    try:
        response = _client.messages.create(
            model=LLM_MODEL,
            max_tokens=1024,
            system=SQL_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
    except Exception:
        return _fallback_sql_for_question(question, schema_text, history)

    raw_text = "".join(block.text for block in response.content if getattr(block, "type", None) == "text")
    try:
        return _parse_llm_json(raw_text)
    except RuntimeError:
        return _fallback_sql_for_question(question, schema_text, history)


def _parse_llm_json(raw_text: str) -> Dict[str, str]:
    cleaned = raw_text.strip()
    cleaned = re.sub(r"^```(json)?", "", cleaned).strip()
    cleaned = re.sub(r"```$", "", cleaned).strip()

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        # Fallback: try to pull a SELECT statement out even if the model
        # didn't follow the JSON format exactly.
        match = re.search(r"(SELECT\b.*)", cleaned, re.IGNORECASE | re.DOTALL)
        if match:
            return {"sql": match.group(1).strip().rstrip(";"), "explanation": ""}
        raise RuntimeError(f"Could not parse LLM response as JSON: {raw_text[:300]}")

    sql = parsed.get("sql", "").strip().rstrip(";")
    explanation = parsed.get("explanation", "")
    return {"sql": sql, "explanation": explanation}
