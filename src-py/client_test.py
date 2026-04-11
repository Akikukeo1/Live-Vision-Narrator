import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests


def get_test_config():
	"""編集しやすい設定をまとめる関数。

	- min_chars: Payload に入れる「X文字以上」の数値
	- concurrency: 同時実行するワーカー数
	- total_requests: 合計で送るリクエスト数
	- url: エンドポイント（ストリーミングを想定）
	- timeout: リクエストタイムアウト（秒）
	"""
	return {
		"min_chars": 1000,
		"concurrency": 4,
		"total_requests": 8,
		"url": "http://localhost:8000/generate/stream",
		# mode: "sequential" = send next request after previous completes
		#       "parallel"   = send requests concurrently (uses concurrency)
		"mode": "sequential",
		"timeout": 120,
	}


def make_payload(min_chars: int) -> dict:
	prompt = (
		"こんにちは、私は開発者です。あなたは、テストのために呼びされました。"
		"このテストに協力してください。内容としては、{min}文字以上の長い文章を生成してください。"
		"内容は何でもいいです。1往復で完結させるため、このプロンプトに対して、"
		"あなたが生成する文章は、{min}文字以上で完結させてください。質問で返したり、"
		"続きを促すような文章は避けてください。"
	).format(min=min_chars)

	return {"model": "live-narrator", "prompt": prompt}


def run_request(task_id: str, url: str, payload: dict, timeout: int):
	info = {"task_id": task_id, "ok": False, "status": None, "error": None}
	start = time.time()
	try:
		with requests.post(url, json=payload, stream=True, timeout=timeout) as resp:
			info["status"] = resp.status_code
			print(f"[{task_id}] Status: {resp.status_code}")
			# Collect chunks until connection closes
			buf = bytearray()
			chunk_count = 0
			for chunk in resp.iter_content(chunk_size=4096):
				if not chunk:
					continue
				buf.extend(chunk)
				print(f"[{task_id}] chunk {chunk_count} (len={len(chunk)})")
				chunk_count += 1

			full = bytes(buf)
			text = full.decode("utf-8", errors="replace")

			# Parse NDJSON lines and collect response parts
			response_parts = []
			for raw_line in text.splitlines():
				line = raw_line.strip()
				if not line:
					continue
				try:
					obj = json.loads(line)
				except Exception:
					print(f"[{task_id}] could not parse line as JSON: {line!r}")
					continue
				# Pretty print each parsed chunk (concise)
				print(f"[{task_id}] parsed: {json.dumps(obj, ensure_ascii=False)}")
				if isinstance(obj, dict):
					part = obj.get("response")
					if isinstance(part, str):
						response_parts.append(part)

			full_response = "".join(response_parts)
			info.update({
				"ok": True,
				"chunk_count": chunk_count,
				"full_response": full_response,
				"full_length": len(full_response),
				"elapsed_s": time.time() - start,
			})

	except Exception as e:
		info["error"] = str(e)
		print(f"[{task_id}] error: {e}")

	return info


def main():
	cfg = get_test_config()
	payload = make_payload(cfg["min_chars"])

	results = []
	if cfg.get("mode") == "parallel":
		tasks = []
		for i in range(cfg["total_requests"]):
			tasks.append((str(i + 1), payload))

		with ThreadPoolExecutor(max_workers=cfg["concurrency"]) as ex:
			futures = {ex.submit(run_request, tid, cfg["url"], pl, cfg["timeout"]): tid for tid, pl in tasks}
			for fut in as_completed(futures):
				res = fut.result()
				results.append(res)
				print(f"[summary {res['task_id']}] ok={res.get('ok')} status={res.get('status')} "
					  f"chunks={res.get('chunk_count')} len={res.get('full_length')} elapsed={res.get('elapsed_s')}")
	else:
		# sequential mode: send next request only after previous completes
		for i in range(cfg["total_requests"]):
			tid = str(i + 1)
			print(f"Starting sequential task {tid}...")
			res = run_request(tid, cfg["url"], payload, cfg["timeout"])
			results.append(res)
			print(f"[summary {res['task_id']}] ok={res.get('ok')} status={res.get('status')} "
				  f"chunks={res.get('chunk_count')} len={res.get('full_length')} elapsed={res.get('elapsed_s')}")

	# final aggregate
	success = sum(1 for r in results if r.get("ok"))
	print(f"\nCompleted {len(results)} requests ({success} successful)")


if __name__ == "__main__":
	main()
