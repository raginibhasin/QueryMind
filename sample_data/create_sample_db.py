"""
Creates sample_company.db: a small SQLite database to demo QueryMind
against, so you have something to point it at immediately without
setting up Postgres or hunting for a Spider database.

Run:  python sample_data/create_sample_db.py
"""
import sqlite3
import os
import random
import datetime
import sys

ADDITIONAL_ONLY = "--additional-only" in sys.argv
DB_PATH = ":memory:" if ADDITIONAL_ONLY else os.path.join(os.path.dirname(__file__), "sample_company.db")
random.seed(17)

if os.path.exists(DB_PATH):
    os.remove(DB_PATH)

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

cur.executescript("""
CREATE TABLE departments (
    department_id INTEGER PRIMARY KEY,
    department_name TEXT NOT NULL
);

CREATE TABLE employees (
    employee_id INTEGER PRIMARY KEY,
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    department_id INTEGER NOT NULL,
    salary REAL NOT NULL,
    hire_date TEXT NOT NULL,
    FOREIGN KEY (department_id) REFERENCES departments(department_id)
);

CREATE TABLE sales (
    sale_id INTEGER PRIMARY KEY,
    employee_id INTEGER NOT NULL,
    sale_amount REAL NOT NULL,
    sale_date TEXT NOT NULL,
    product_category TEXT NOT NULL,
    FOREIGN KEY (employee_id) REFERENCES employees(employee_id)
);
""")

departments = ["Engineering", "Sales", "Marketing", "HR", "Finance", "Support"]
for i, name in enumerate(departments, start=1):
    cur.execute("INSERT INTO departments VALUES (?, ?)", (i, name))

first_names = ["Aarav", "Priya", "Rohan", "Ananya", "Vikram", "Neha", "Karan", "Meera",
               "Arjun", "Divya", "Sanjay", "Kavya", "Rahul", "Isha", "Aditya", "Sneha"]
last_names = ["Sharma", "Verma", "Patel", "Gupta", "Reddy", "Nair", "Iyer", "Singh",
              "Rao", "Mehta", "Kapoor", "Joshi"]

employee_ids = []
cur_id = 1
for _ in range(60):
    dept_id = random.randint(1, len(departments))
    base_salary = {1: 95000, 2: 70000, 3: 65000, 4: 55000, 5: 75000, 6: 50000}[dept_id]
    salary = round(base_salary + random.uniform(-8000, 20000), 2)
    hire_date = (datetime.date(2019, 1, 1) + datetime.timedelta(days=random.randint(0, 2500))).isoformat()
    cur.execute(
        "INSERT INTO employees VALUES (?, ?, ?, ?, ?, ?)",
        (cur_id, random.choice(first_names), random.choice(last_names), dept_id, salary, hire_date),
    )
    employee_ids.append(cur_id)
    cur_id += 1

product_categories = ["Software", "Hardware", "Consulting", "Support Plan", "Training"]
sale_id = 1
for _ in range(400):
    emp_id = random.choice(employee_ids)
    amount = round(random.uniform(500, 25000), 2)
    year = random.choice([2024, 2025, 2026])
    month = random.randint(1, 12)
    day = random.randint(1, 28)
    sale_date = datetime.date(year, month, day).isoformat()
    category = random.choice(product_categories)
    cur.execute(
        "INSERT INTO sales VALUES (?, ?, ?, ?, ?)",
        (sale_id, emp_id, amount, sale_date, category),
    )
    sale_id += 1

conn.commit()
conn.close()


def create_university_db():
    path = os.path.join(os.path.dirname(__file__), "sample_university.db")
    if os.path.exists(path):
        print(f"Already exists; leaving unchanged: {path}")
        return path
    db = sqlite3.connect(path)
    db.executescript("""
    CREATE TABLE departments (
        department_id INTEGER PRIMARY KEY,
        department_name TEXT NOT NULL,
        building TEXT NOT NULL
    );
    CREATE TABLE programs (
        program_id INTEGER PRIMARY KEY,
        program_name TEXT NOT NULL,
        degree_level TEXT NOT NULL,
        department_id INTEGER NOT NULL REFERENCES departments(department_id)
    );
    CREATE TABLE students (
        student_id INTEGER PRIMARY KEY,
        first_name TEXT NOT NULL,
        last_name TEXT NOT NULL,
        program_id INTEGER NOT NULL REFERENCES programs(program_id),
        enrollment_year INTEGER NOT NULL,
        status TEXT NOT NULL,
        gpa REAL NOT NULL
    );
    CREATE TABLE instructors (
        instructor_id INTEGER PRIMARY KEY,
        first_name TEXT NOT NULL,
        last_name TEXT NOT NULL,
        department_id INTEGER NOT NULL REFERENCES departments(department_id),
        title TEXT NOT NULL
    );
    CREATE TABLE courses (
        course_id INTEGER PRIMARY KEY,
        course_code TEXT NOT NULL,
        course_name TEXT NOT NULL,
        credits INTEGER NOT NULL,
        department_id INTEGER NOT NULL REFERENCES departments(department_id),
        instructor_id INTEGER NOT NULL REFERENCES instructors(instructor_id)
    );
    CREATE TABLE enrollments (
        enrollment_id INTEGER PRIMARY KEY,
        student_id INTEGER NOT NULL REFERENCES students(student_id),
        course_id INTEGER NOT NULL REFERENCES courses(course_id),
        term TEXT NOT NULL,
        academic_year INTEGER NOT NULL,
        grade TEXT NOT NULL
    );
    """)
    departments = ["Computer Science", "Business", "Engineering", "Arts", "Health Sciences"]
    db.executemany("INSERT INTO departments VALUES (?, ?, ?)", [
        (i, name, f"Building {chr(65 + i)}") for i, name in enumerate(departments, 1)
    ])
    programs = [
        (1, "Computer Science", "Bachelor", 1), (2, "Data Science", "Master", 1),
        (3, "Business Administration", "Bachelor", 2), (4, "Mechanical Engineering", "Bachelor", 3),
        (5, "Digital Arts", "Bachelor", 4), (6, "Public Health", "Master", 5),
    ]
    db.executemany("INSERT INTO programs VALUES (?, ?, ?, ?)", programs)
    names = [("Avery", "Morgan"), ("Jordan", "Lee"), ("Taylor", "Patel"), ("Casey", "Kim"),
             ("Riley", "Garcia"), ("Quinn", "Brown"), ("Morgan", "Shah"), ("Jamie", "Chen")]
    students = []
    for student_id in range(1, 121):
        first, last = names[(student_id - 1) % len(names)]
        students.append((student_id, first, last, (student_id - 1) % len(programs) + 1,
                         2022 + (student_id % 5), "active" if student_id % 9 else "graduated",
                         round(random.uniform(2.1, 4.0), 2)))
    db.executemany("INSERT INTO students VALUES (?, ?, ?, ?, ?, ?, ?)", students)
    instructors = [(i, names[(i - 1) % len(names)][0], names[(i - 1) % len(names)][1], (i - 1) % 5 + 1,
                    ["Lecturer", "Assistant Professor", "Professor"][i % 3]) for i in range(1, 16)]
    db.executemany("INSERT INTO instructors VALUES (?, ?, ?, ?, ?)", instructors)
    courses = [(i, f"C{i:03}", name, 3 + i % 2, (i - 1) % 5 + 1, (i - 1) % 15 + 1)
               for i, name in enumerate(["Data Structures", "Microeconomics", "Design Studio", "Anatomy",
                                         "Statistics", "Thermodynamics", "Research Methods", "Algorithms",
                                         "Accounting", "Public Policy", "Machine Learning", "Organic Chemistry"], 1)]
    db.executemany("INSERT INTO courses VALUES (?, ?, ?, ?, ?, ?)", courses)
    grades = ["A", "A-", "B+", "B", "B-", "C+"]
    enrollments = [(i, (i * 7) % 120 + 1, (i - 1) % len(courses) + 1,
                    "Fall" if i % 2 else "Spring", 2024 + i % 3, grades[i % len(grades)])
                   for i in range(1, 481)]
    db.executemany("INSERT INTO enrollments VALUES (?, ?, ?, ?, ?, ?)", enrollments)
    db.commit()
    db.close()
    return path


def create_retail_db():
    path = os.path.join(os.path.dirname(__file__), "sample_retail.db")
    if os.path.exists(path):
        print(f"Already exists; leaving unchanged: {path}")
        return path
    db = sqlite3.connect(path)
    db.executescript("""
    CREATE TABLE customers (
        customer_id INTEGER PRIMARY KEY,
        customer_name TEXT NOT NULL,
        city TEXT NOT NULL,
        segment TEXT NOT NULL
    );
    CREATE TABLE products (
        product_id INTEGER PRIMARY KEY,
        product_name TEXT NOT NULL,
        category TEXT NOT NULL,
        unit_price REAL NOT NULL
    );
    CREATE TABLE orders (
        order_id INTEGER PRIMARY KEY,
        customer_id INTEGER NOT NULL REFERENCES customers(customer_id),
        order_date TEXT NOT NULL,
        status TEXT NOT NULL
    );
    CREATE TABLE order_items (
        order_item_id INTEGER PRIMARY KEY,
        order_id INTEGER NOT NULL REFERENCES orders(order_id),
        product_id INTEGER NOT NULL REFERENCES products(product_id),
        quantity INTEGER NOT NULL,
        unit_price REAL NOT NULL
    );
    """)
    cities = ["Seattle", "Austin", "Chicago", "Boston", "Denver", "Atlanta"]
    segments = ["Consumer", "Small Business", "Enterprise"]
    db.executemany("INSERT INTO customers VALUES (?, ?, ?, ?)", [
        (i, f"Customer {i:03}", cities[i % len(cities)], segments[i % len(segments)])
        for i in range(1, 61)
    ])
    categories = ["Home", "Electronics", "Outdoor", "Office", "Wellness"]
    products = [(i, f"Product {i:02}", categories[(i - 1) % len(categories)],
                 round(12.5 + i * 7.35, 2)) for i in range(1, 26)]
    db.executemany("INSERT INTO products VALUES (?, ?, ?, ?)", products)
    orders = []
    items = []
    for order_id in range(1, 181):
        customer_id = (order_id - 1) % 60 + 1
        date = datetime.date(2024 + order_id % 3, (order_id - 1) % 12 + 1, (order_id - 1) % 27 + 1)
        orders.append((order_id, customer_id, date.isoformat(),
                       ["shipped", "delivered", "processing"][order_id % 3]))
        for offset in range(2):
            product_id = (order_id * (offset + 3)) % len(products) + 1
            quantity = (order_id + offset) % 4 + 1
            items.append((len(items) + 1, order_id, product_id, quantity, products[product_id - 1][3]))
    db.executemany("INSERT INTO orders VALUES (?, ?, ?, ?)", orders)
    db.executemany("INSERT INTO order_items VALUES (?, ?, ?, ?, ?)", items)
    db.commit()
    db.close()
    return path


university_path = create_university_db()
retail_path = create_retail_db()

if not ADDITIONAL_ONLY:
    print(f"Created {DB_PATH}")
    print("Tables: departments, employees, sales")
print(f"Ready: {university_path}")
print("Tables: departments, programs, students, instructors, courses, enrollments")
print(f"Ready: {retail_path}")
print("Tables: customers, products, orders, order_items")
print("Try asking QueryMind things like:")
print('  - "What is the average salary in each department?"')
print('  - "Show total sales by product category"')
print('  - "Which employees have the highest salary?"')
print('  - Then follow up with: "Only show sales from 2026"')