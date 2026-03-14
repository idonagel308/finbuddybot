import os
import re

files_to_fix = [
    "database/user_management.py",
    "database/queries.py",
    "database/analytics_engine.py"
]

for filename in files_to_fix:
    with open(filename, "r", encoding="utf-8") as f:
        content = f.read()

    # Move user_ref
    pattern1 = r'(    user_ref = db\.collection\("users"\)\.document\(user_id_str\)\n\s*try:\n)'
    replacement1 = r'    try:\n        user_ref = db.collection("users").document(user_id_str)\n'
    content = re.sub(pattern1, replacement1, content)
    
    # Also handle the cases where data={ ... } is between user_ref and try:
    pattern2 = r'    user_ref = db\.collection\("users"\)\.document\(user_id_str\)\n([\s\S]*?)    try:\n'
    replacement2 = r'\1    try:\n        user_ref = db.collection("users").document(user_id_str)\n'
    content = re.sub(pattern2, replacement2, content)

    # Move expenses_ref
    pattern3 = r'(    expenses_ref = db\.collection\("users"\)\.document\(user_id_str\)\.collection\("expenses"\)\n\s*try:\n)'
    replacement3 = r'    try:\n        expenses_ref = db.collection("users").document(user_id_str).collection("expenses")\n'
    content = re.sub(pattern3, replacement3, content)

    with open(filename, "w", encoding="utf-8") as f:
        f.write(content)

print("Refactor complete.")
