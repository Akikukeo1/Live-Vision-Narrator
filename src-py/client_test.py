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
	- request_interval_s: 各リクエスト間の待機時間（秒）（接続完全切断のため）
	"""
	return {
		"min_chars": 1000,
		"concurrency": 1,
        # シングルスレッドで連続してリクエストを送る場合は concurrency=1 にして、total_requests を増やすと良いでしょう。
		"total_requests": 10,
		"url": "http://localhost:8000/generate/stream",
		# mode: "sequential" = send next request after previous completes
		#       "parallel"   = send requests concurrently (uses concurrency)
		"mode": "sequential",
		"timeout": 120,
		# 各リクエスト完了後、接続完全クローズのための待機時間
		"request_interval_s": 5.0,
	}


def make_payload(min_chars: int) -> dict:
	prompt = (
		"こんにちは、私は開発者です。あなたは、テストのために呼びされました。"
		"このテストに協力してください。内容としては、{min}文字以上の長い文章を生成してください。"
		"内容は何でもいいです。1往復で完結させるため、このプロンプトに対して、"
		"あなたが生成する文章は、{min}文字以上で完結させてください。質問で返したり、"
		"続きを促すような文章は避けてください。"
	).format(min=min_chars)

	return {"model": "live-narrator-e2b", "prompt": prompt}


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
			ttft_s = None  # Time to First Token (server-measured from first response header)
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
			first_response_obj = None
			for raw_line in text.splitlines():
				line = raw_line.strip()
				if not line:
					continue
				try:
					obj = json.loads(line)
				except Exception:
					print(f"[{task_id}] could not parse line as JSON: {line!r}")
					continue
				# Capture first response object (likely has server-side timing)
				if first_response_obj is None:
					first_response_obj = obj
					print(f"[{task_id}] first response: {json.dumps(obj, ensure_ascii=False)}")
				# Pretty print each parsed chunk (concise)
				print(f"[{task_id}] parsed: {json.dumps(obj, ensure_ascii=False)}")
				if isinstance(obj, dict):
					part = obj.get("response")
					if isinstance(part, str):
						response_parts.append(part)

			full_response = "".join(response_parts)

			# Extract server-measured TTFT from first response object (header with elapsed_ms)
			if first_response_obj and isinstance(first_response_obj, dict):
				elapsed_ms = first_response_obj.get("elapsed_ms")
				if elapsed_ms is not None:
					ttft_s = elapsed_ms / 1000.0  # Convert ms to seconds
					print(f"[{task_id}] server-measured TTFT from first response: {ttft_s*1000:.2f}ms")

			info.update({
				"ok": True,
				"chunk_count": chunk_count,
				"full_response": full_response,
				"full_length": len(full_response),
				"elapsed_s": time.time() - start,
				"ttft_s": ttft_s,  # Time to First Token (server-measured, includes queue time)
            })
	except Exception as e:
		info["error"] = str(e)
		print(f"[{task_id}] error: {e}")

	return info


def print_statistics(results, exclude_first=True):
	"""Calculate and print statistics for all requests.

	exclude_first: Skip the first request (warm-up effect, ~5000ms)
	"""
	if exclude_first and len(results) > 1:
		eval_results = results[1:]
		print(f"\n=== Statistics (excluding first request for warm-up) ===")
	else:
		eval_results = results
		print(f"\n=== Statistics (all requests) ===")

	successful = [r for r in eval_results if r.get("ok")]
	if not successful:
		print("No successful requests.")
		return

	# Extract metrics
	elapsed_times = []  # full client-side elapsed time
	ttft_times = []    # time to first token
	response_lengths = []

	for r in successful:
		elapsed_times.append(r.get("elapsed_s", 0))
		ttft = r.get("ttft_s")
		if ttft is not None:
			ttft_times.append(ttft)
		response_lengths.append(r.get("full_length", 0))

	# Calculate statistics
	if ttft_times:
		avg_ttft = sum(ttft_times) / len(ttft_times)
		min_ttft = min(ttft_times)
		max_ttft = max(ttft_times)
		print(f"Time to First Token (TTFT):")
		print(f"  Average: {avg_ttft*1000:.2f}ms")
		print(f"  Min:     {min_ttft*1000:.2f}ms")
		print(f"  Max:     {max_ttft*1000:.2f}ms")

	if elapsed_times:
		avg_elapsed = sum(elapsed_times) / len(elapsed_times)
		min_elapsed = min(elapsed_times)
		max_elapsed = max(elapsed_times)
		print(f"Client-side latency:")
		print(f"  Average: {avg_elapsed:.2f}s")
		print(f"  Min:     {min_elapsed:.2f}s")
		print(f"  Max:     {max_elapsed:.2f}s")

	if response_lengths:
		avg_len = sum(response_lengths) / len(response_lengths)
		min_len = min(response_lengths)
		max_len = max(response_lengths)
		print(f"Response length (chars):")
		print(f"  Average: {avg_len:.0f}")
		print(f"  Min:     {min_len}")
		print(f"  Max:     {max_len}")

	print(f"Success rate: {len(successful)}/{len(eval_results)}")


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
				ttft_info = f" ttft={res.get('ttft_s', 0)*1000:.2f}ms" if res.get('ttft_s') else ""
				print(f"[summary {res['task_id']}] ok={res.get('ok')} status={res.get('status')} "
                    f"chunks={res.get('chunk_count')} len={res.get('full_length')} elapsed={res.get('elapsed_s')}{ttft_info}")
	else:
		# sequential mode: send next request only after previous completes
		for i in range(cfg["total_requests"]):
			tid = str(i + 1)
			print(f"Starting sequential task {tid}...")
			res = run_request(tid, cfg["url"], payload, cfg["timeout"])
			results.append(res)
			ttft_info = f" ttft={res.get('ttft_s', 0)*1000:.2f}ms" if res.get('ttft_s') else ""
			print(f"[summary {res['task_id']}] ok={res.get('ok')} status={res.get('status')} "
                f"chunks={res.get('chunk_count')} len={res.get('full_length')} elapsed={res.get('elapsed_s')}{ttft_info}")

			# Wait for connection to fully close before sending next request
			if i < cfg["total_requests"] - 1:
				interval = cfg.get("request_interval_s", 1.0)
				print(f"Waiting {interval}s before next request...")
				time.sleep(interval)
	# Print statistics, excluding first request for warm-up effect
	print_statistics(results, exclude_first=True)


if __name__ == "__main__":
	main()
