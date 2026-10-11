# QueryMind

QueryMind turns questions about a database into SQL, checks the SQL, runs it,
and displays the results as a table or chart. It uses FastAPI, SQLite or
PostgreSQL, SQLAlchemy, and the Anthropic API. The frontend is a single HTML
file, so there is no separate JavaScript build step.

## Project files

```
app/                 API, database connections, SQL validation, and chart choice
frontend/index.html  Query Studio and dashboard
sample_data/         Sample database generator and SQLite files
evaluation/          Query evaluation script
requirements.txt     Python dependencies
.env.example         Example local configuration
```

## Setup

Open the `querymind` folder in VS Code and open a terminal at the project root.
Python 3.11 or 3.13 is recommended.

In PowerShell on Windows:

```powershell
py -3.13 -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

On macOS or Linux:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## Configuration

For the local sample questions, an Anthropic API key is optional. Without one,
QueryMind uses built-in SQL examples for a small set of supported questions.
To use model-generated SQL, copy `.env.example` to `.env` and set
`ANTHROPIC_API_KEY` to your key. API access may require an account with
available credits.

Set `ENCRYPTION_KEY` in `.env` to encrypt saved database credentials. Generate
one from the activated environment with:

```powershell
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Keep `.env` private. It is excluded by `.gitignore`.

## Sample databases

Run the generator from the project root:

```powershell
python sample_data/create_sample_db.py
```

It creates these SQLite databases in `sample_data/`:

- `sample_company.db`: departments, employees, and sales.
- `sample_university.db`: departments, programs, students, instructors,
  courses, and enrollments.
- `sample_retail.db`: customers, products, orders, and order items.

To create just the university and retail samples, without rebuilding the
company database:

```powershell
python sample_data/create_sample_db.py --additional-only
```

## Run the app

From the project root, with the virtual environment active:

```powershell
python -m uvicorn app.main:app --reload
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). API documentation is at
[http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs).

The Welcome page links to the **Database Library** and **Query Studio**. Choose
a bundled sample from the library, or connect your own database in the studio.
For a SQLite database on your computer, use **Or browse for a SQLite database**
and select a `.db`, `.sqlite`, or `.sqlite3` file up to 50 MB. QueryMind stores
a copy in `sample_data/uploads/`; it does not change the original file. You can
also enter a path that the running app can access.

Some questions to try:

- What is the average salary in each department?
- Show total sales by product category.
- Which employees have the highest salary?
- What is the average GPA by program?
- Which courses have the most enrollments?
- Show revenue by product category.

Follow-up questions share context within the current conversation. For example,
ask "Only for 2026" after a sales question. Try "Delete all employees" to see
the SQL validator reject a request that is not read-only.

## PostgreSQL

In Query Studio, choose **PostgreSQL** and enter the host, database name,
username, and password. Use a database account with `SELECT`-only access,
especially outside a local demo. The SQL validator is an additional safeguard,
not a replacement for database permissions.

## Evaluation

Connect a database in the app and copy its `connection_id` from the API response.
In PowerShell, set the ID and run the evaluation script:

```powershell
$env:EVAL_CONNECTION_ID = "<connection-id>"
python evaluation/run_eval.py
```

The script reports execution accuracy, latency, errors, and how many unsafe
queries were blocked. It writes results to `evaluation/eval_results.json`.

## Implementation notes

- `app/sql_validator.py` parses SQL with `sqlglot` and allows only a single
  read-only `SELECT` statement.
- `app/schema_analyzer.py` selects tables using lexical relevance before
  building the prompt. It is a basic token-overlap approach.
- `app/viz_selector.py` chooses a visualization from the shape of the results.
- Queries are stored with a `conversation_id`; later questions in that
  conversation can use earlier question/SQL pairs as context.
