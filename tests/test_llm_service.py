import unittest
from unittest.mock import patch

from app import llm_service


class LLMFallbackTest(unittest.TestCase):
    def test_generate_sql_falls_back_for_average_salary_by_department(self):
        class FakeClient:
            class messages:
                @staticmethod
                def create(*args, **kwargs):
                    raise Exception("Your credit balance is too low to access the Anthropic API.")

        with patch.object(llm_service, "_client", FakeClient()):
            result = llm_service.generate_sql(
                "What is the average salary in each department?",
                "TABLE departments (department_id INTEGER, department_name TEXT)\n\nTABLE employees (employee_id INTEGER, department_id INTEGER, salary REAL)",
                [],
            )

        self.assertIn("AVG", result["sql"].upper())
        self.assertIn("GROUP BY", result["sql"].upper())
        self.assertIn("department_name", result["sql"].lower())


if __name__ == "__main__":
    unittest.main()
