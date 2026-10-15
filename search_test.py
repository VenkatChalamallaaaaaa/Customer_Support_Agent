import os
import psycopg
from dotenv import load_dotenv
from pgvector.psycopg import register_vector
from sentence_transformers import SentenceTransformer

load_dotenv()
model = SentenceTransformer("all-MiniLM-L6-v2")
url = os.environ["DATABASE_URL"].replace("+psycopg", "") 

questions = [
    "Can I send something back after three weeks?",
    "My package never arrived, what now?",
    "Will you refund the shipping fee?",
    "I paid with boleto, how do I get my money back?",
]

with psycopg.connect(url) as conn:
    register_vector(conn)
    for q in questions:
        emb = model.encode(q, normalize_embeddings=True)
        rows = conn.execute(
            "SELECT section, 1 - (embedding <=> %s) AS similarity "
            "FROM policy_chunks ORDER BY embedding <=> %s LIMIT 2", (emb, emb)).fetchall()
        print("\n", q)
        for section, sim in rows:
            print(f"   {sim:.2f}  {section}")