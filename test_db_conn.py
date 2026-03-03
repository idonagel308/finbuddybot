import asyncio
from google.cloud import firestore
from database.__init__ import db

async def test_db():
    try:
        print("Testing Firestore DB Connection...")
        doc_ref = db.collection('system_tests').document('connection_test')
        
        # 1. Write
        print("Writing to DB...")
        await doc_ref.set({'status': 'ok', 'timestamp': firestore.SERVER_TIMESTAMP})
        
        # 2. Read
        print("Reading from DB...")
        doc = await doc_ref.get()
        if doc.exists:
            print(f"✅ Success! Read data: {doc.to_dict()}")
            
            # 3. Cleanup
            print("Cleaning up...")
            await doc_ref.delete()
            print("✅ DB is fully functional!")
        else:
            print("❌ Failed to read written document.")
            
    except Exception as e:
        print(f"❌ Connection failed: {type(e).__name__} - {e}")

if __name__ == "__main__":
    asyncio.run(test_db())
