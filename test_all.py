import unittest
from config.config import Config
from database.database_manager import DatabaseManager
from broker.angel_client import AngelOneClient

class TestConfig(unittest.TestCase):
    def test_validate_missing(self):
        with self.assertRaises(ValueError):
            Config.validate()

class TestDatabase(unittest.TestCase):
    def setUp(self):
        self.db = DatabaseManager(":memory:")
    
    def test_save_signal(self):
        signal = {'symbol':'NIFTY','direction':'BUY','entry':100,'stop_loss':99,'take_profit':101,'timestamp':'2025-01-01'}
        self.db.save_signal(signal)
        # No exception means success

if __name__ == '__main__':
    unittest.main()
