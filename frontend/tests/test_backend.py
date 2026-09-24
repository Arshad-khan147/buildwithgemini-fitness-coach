"""Enterprise Test suite for NovaSmart Fitness Coach Gateway API."""

import os
import unittest
from fastapi.testclient import TestClient

os.environ["AGENT_ENGINE_RESOURCE_NAME"] = "projects/943429364849/locations/us-east1/reasoningEngines/8579632168047738880"

import main

class TestBackendSecurity(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)

    def test_password_hashing(self):
        pwd = "secretfitness2026"
        h1 = main.hash_password(pwd)
        h2 = main.hash_password(pwd)
        self.assertEqual(h1, h2)
        self.assertTrue(main.verify_password(pwd, h1))
        self.assertFalse(main.verify_password("wrongpassword", h1))

    def test_jwt_token_flow(self):
        token = main.create_jwt_token("test@novasmart.ai", "Test User")
        self.assertIsInstance(token, str)
        decoded = main.decode_jwt_token(token)
        self.assertIsNotNone(decoded)
        self.assertEqual(decoded["sub"], "test@novasmart.ai")
        self.assertEqual(decoded["name"], "Test User")

    def test_unregistered_login_fails(self):
        res = self.client.post("/auth/login", json={"email": "nonexistent.user.123@test.com", "password": "anypassword"})
        self.assertEqual(res.status_code, 401)
        self.assertIn("No registered account found", res.json()["error"])

    def test_registration_and_login_flow(self):
        email = "unittest.athlete@novasmart.ai"
        password = "securepassword2026"
        
        # 1. Register new user
        reg_res = self.client.post("/auth/register", json={"email": email, "password": password, "name": "UnitTest Athlete"})
        self.assertEqual(reg_res.status_code, 200)
        self.assertTrue(reg_res.json()["success"])
        self.assertIn("token", reg_res.json())

        # 2. Duplicate registration attempt should fail
        dup_res = self.client.post("/auth/register", json={"email": email, "password": password})
        self.assertEqual(dup_res.status_code, 400)
        self.assertIn("already registered", dup_res.json()["error"])

        # 3. Login with registered user should succeed
        login_res = self.client.post("/auth/login", json={"email": email, "password": password})
        self.assertEqual(login_res.status_code, 200)
        self.assertTrue(login_res.json()["success"])
        self.assertIn("token", login_res.json())

    def test_security_headers(self):
        res = self.client.get("/")
        self.assertEqual(res.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(res.headers.get("X-Frame-Options"), "DENY")
        self.assertIn("X-Process-Time", res.headers)

if __name__ == "__main__":
    unittest.main()
