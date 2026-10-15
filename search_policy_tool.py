import json
from support_tools import search_policy

for q in [
    "What happens if my package never shows up?",
    "How many days do I have to return an item?",
    "Can I change my delivery address after it shipped?",
]:
    print("\n", q)
    for r in json.loads(search_policy.invoke({"question": q})):
        print(f"   {r['similarity']:.2f}  {r['section']}")

    