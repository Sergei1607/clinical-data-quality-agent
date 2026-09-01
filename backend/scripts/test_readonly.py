import os
from dotenv import load_dotenv
import psycopg2

load_dotenv()
conn = psycopg2.connect(os.environ["AGENT_DATABASE_URL"])
cur = conn.cursor()

cur.execute("SELECT usubjid FROM subjects LIMIT 3;")
print("SELECT worked:", cur.fetchall())

try:
    cur.execute("DELETE FROM subjects WHERE usubjid = 'nonexistent';")
    conn.commit()
    print("WARNING: DELETE succeeded — the role is NOT actually read-only!")
except Exception as e:
    print("DELETE correctly blocked:", type(e).__name__, "-", e)

conn.close()