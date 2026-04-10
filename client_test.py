import requests

URL = "http://localhost:8000/generate"

payload = {"model": "live-narrator", "prompt": "テスト: こんにちは"}

resp = requests.post(URL, json=payload)
print(resp.status_code)
print(resp.text)
