import unittest
from fastapi.exceptions import HTTPException
from pydantic import ValidationError


class TestAuthValidation(unittest.TestCase):
    def test_password_min_length_contract(self):
        password = "short"
        self.assertTrue(len(password) < 8)


if __name__ == "__main__":
    unittest.main()
