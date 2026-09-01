import json
import urllib.request

url = "https://clinical-data-quality-agent.onrender.com/chat"
payload = {"messages": [{"role": "user", "content": "Give me a high-level overview of this dataset."}]}
req = urllib.request.Request(
    url,
    data=json.dumps(payload).encode(),
    headers={"Content-Type": "application/json"},
)
with urllib.request.urlopen(req, timeout=60) as resp:
    print(resp.read().decode())