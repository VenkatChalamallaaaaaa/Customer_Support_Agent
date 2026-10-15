import os, re
import psycopg
from dotenv import load_dotenv
from pgvector.psycopg import register_vector
from sentence_transformers import SentenceTransformer

load_dotenv()
text = open("policies/return_policy.md", encoding="utf-8").read()

# One chunk per "## " section. The title stays in the text so it helps the embedding.
chunks = []
for part in re.split(r"(?m)^## ", text)[1:]:
    title, _, body = part.partition("\n")
    chunks.append((title.strip(), f"{title.strip()}\n{body.strip()}"))

model = SentenceTransformer("all-MiniLM-L6-v2")
embeddings = model.encode([c[1] for c in chunks], normalize_embeddings=True)

with psycopg.connect(os.environ["ADMIN_DB_URL"], autocommit=True) as conn:
    conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    register_vector(conn)
    conn.execute("DROP TABLE IF EXISTS policy_chunks")
    conn.execute("""CREATE TABLE policy_chunks (
        id SERIAL PRIMARY KEY,
        section TEXT NOT NULL,
        content TEXT NOT NULL,
        embedding vector(384) NOT NULL)""")
    for (section, content), emb in zip(chunks, embeddings):
        conn.execute(
            "INSERT INTO policy_chunks (section, content, embedding) VALUES (%s, %s, %s)",
            (section, content, emb))
    conn.execute("GRANT SELECT ON policy_chunks TO agent_support")

print(f"Stored {len(chunks)} chunks:")
for section, _ in chunks:
    print(" -", section)