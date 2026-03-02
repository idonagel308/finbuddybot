import unittest
from unittest.mock import MagicMock, AsyncMock, patch

# Mock the client BEFORE importing the service to prevent ADC error
mock_db = AsyncMock()
with patch('google.cloud.firestore.AsyncClient', return_value=mock_db):
    import database.expense_operations as expense_operations
    import database.user_management as user_management
    import database as db_mod

class TestFirestorePackage(unittest.IsolatedAsyncioTestCase):
    async def test_logic(self):
        # Verify that the service is using our mock
        self.assertEqual(db_mod.db, mock_db)
        
        # Test add_expense logic
        mock_doc = MagicMock()
        mock_doc.set = AsyncMock()
        mock_doc.id = "test_id"
        mock_db.collection.return_value.document.return_value.collection.return_value.document.return_value = mock_doc
        
        res = await expense_operations.add_expense(123, 50.0, "Food", "Pizza")
        self.assertEqual(res, "test_id")
        
        # Test get_profile logic
        mock_profile_doc = AsyncMock()
        mock_profile_doc.exists = True
        mock_profile_doc.to_dict.return_value = {"profile": {"age": 25}}
        mock_db.collection.return_value.document.return_value.get.return_value = mock_profile_doc
        
        profile = await user_management.get_profile(123)
        self.assertEqual(profile['age'], 25)
        
        print("\n--- NEW PACKAGE MOCK LOGIC VERIFIED ---")

if __name__ == '__main__':
    unittest.main()
