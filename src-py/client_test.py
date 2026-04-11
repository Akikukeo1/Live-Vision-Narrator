import json

import requests

URL = "http://localhost:8000/generate/stream"

payload = {"model": "live-narrator", "prompt": "テスト: こんにちは"}

with requests.post(URL, json=payload, stream=True, timeout=60) as resp:
	print("Status:", resp.status_code)
	print("Headers:")
	for k, v in resp.headers.items():
		print(f"  {k}: {v}")

	resp.raise_for_status()

	buf = bytearray()
	print("\nChunks:")
	for i, chunk in enumerate(resp.iter_content(chunk_size=4096)):
		if not chunk:
			continue
		buf.extend(chunk)
		print(f"  chunk {i} (len={len(chunk)}):", repr(chunk))

	full = bytes(buf)
	print("\n--- Diagnostics ---")
	print("Raw bytes length:", len(full))
	print("Raw bytes repr:", repr(full))

	text = full.decode("utf-8", errors="replace")
	print("Text repr:", repr(text))

	print("\nParsed lines:")
	response_text_parts = []
	for line in text.splitlines():
		line = line.strip()
		if not line:
			continue
		obj = json.loads(line)
		print(json.dumps(obj, ensure_ascii=False, indent=2))
		if isinstance(obj, dict):
			part = obj.get("response")
			if isinstance(part, str):
				response_text_parts.append(part)

	if response_text_parts:
		full_response = "".join(response_text_parts)
		print("\nFull response:")
		print(full_response)
		print("Full response length:", len(full_response))
