import requests

URL = "http://localhost:8000/generate"

payload = {"model": "gemma-4-E4B-it-IQ4_XS", "prompt": "テスト: こんにちは"}

resp = requests.post(URL, json=payload)
print(resp.status_code)
print(resp.text)
