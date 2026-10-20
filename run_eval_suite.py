import json
import time
import urllib.request
import urllib.error
import re
import sys
import os

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

API_KEY = os.environ.get("GROQ_API_KEY", "")
MODEL = "openai/gpt-oss-120b"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

QUESTIONS = [
    {
        "id": "Q1",
        "topic": "Binary Search Bug",
        "core_challenge": "Two distinct bugs (infinite loop + wrong boundary)",
        "why_hard": "Naive 'off-by-one' answer misses the worse bug",
        "task": """The following Python binary search has a subtle bug. Find it, explain exactly why it is wrong, give a concrete input that produces the wrong answer, fix it, and prove the fix is correct with a working Python test covering: empty list, single element, target at index 0, target at last index, and target not present.

def binary_search(arr, target):
    lo, hi = 0, len(arr)
    while lo < hi:
        mid = (lo + hi) // 2
        if arr[mid] == target:
            return mid
        elif arr[mid] < target:
            lo = mid
        else:
            hi = mid - 1
    return -1
""",
        "expected_points": [
            ("Bug 1: Infinite loop on lo = mid", ["infinite loop", "lo = mid", "never terminates", "stuck"]),
            ("Bug 2: Boundary issue / hi skipping mid", ["hi = mid - 1", "skips", "half-open", "hi = mid", "boundary"]),
            ("Concrete failing input", ["[1, 2, 3]", "[1, 2]", "target"]),
            ("Corrected code provided", ["def binary_search", "lo = mid + 1"]),
            ("Comprehensive test suite", ["empty", "single", "not present"])
        ]
    },
    {
        "id": "Q2",
        "topic": "SQL Race Condition",
        "core_challenge": "TOCTOU + deadlock in bank transfers",
        "why_hard": "FOR SHARE looks correct but isn't sufficient",
        "task": """A bank's transfer endpoint runs this SQL inside a READ COMMITTED transaction.
Identify every concurrency hazard, give a concrete scenario showing money being lost
or doubled, then rewrite it (PostgreSQL dialect) to be fully safe. Raw SQL only, no ORM.

-- Transfer $amount from account A to account B
SELECT balance FROM accounts WHERE id = A FOR SHARE;
-- application checks balance >= amount
UPDATE accounts SET balance = balance - amount WHERE id = A;
UPDATE accounts SET balance = balance + amount WHERE id = B;
""",
        "expected_points": [
            ("TOCTOU / Non-exclusive lock race", ["toctou", "race", "for share", "shared lock", "concurrent"]),
            ("Concrete loss/overdraw scenario", ["double", "overdraft", "negative", "both read", "concurrent"]),
            ("Deadlock hazard (A->B vs B->A)", ["deadlock", "lock order", "simultaneous", "reverse"]),
            ("Safe rewrite: FOR UPDATE or conditional UPDATE", ["for update", "where balance >=", "strictly"]),
            ("Deadlock prevention via ordering", ["order by", "least", "greatest", "id <", "lock order"])
        ]
    },
    {
        "id": "Q3",
        "topic": "Algorithm Selection",
        "core_challenge": "Counting array beats hash and sort for this domain",
        "why_hard": "The 'obvious' O(n) answer (hash) is still suboptimal",
        "task": """Choose the best algorithm for finding all pairs summing to T from this dataset:
n = 10,000,000 integers in range 0..999, T = 500.
Want ALL unique pairs; duplicates in input count (e.g. [3,3] gives pair (3,3) if count>=2).

Candidates:
  A: Two nested loops - O(n^2) time, O(1) space
  B: Sort + two-pointer - O(n log n) time, O(1) space
  C: Hash set - O(n) average time, O(n) space

Give numeric justification for your choice, then implement it in Python passing:
  find_pairs([1,2,3,4], 5)  -> {(1,4),(2,3)}
  find_pairs([3,3,3], 6)    -> {(3,3)}
  find_pairs([1,2,3], 10)   -> set()
  find_pairs([], 5)          -> set()
""",
        "expected_points": [
            ("Identifies counting / frequency array / bucket", ["counting", "frequency", "array of size", "1000", "bucket"]),
            ("Explains why hash/sort are suboptimal for 0..999", ["overhead", "memory", "cache", "hash", "sort"]),
            ("Numeric comparison for n=10M", ["10,000,000", "10m", "mb", "operations", "ops"]),
            ("Handles identical elements a == b (count >= 2)", [">= 2", "a == b", "same element", "pair (3,3)"]),
            ("Passes all 4 test cases", ["{(1,4),(2,3)}", "{(3,3)}", "set()"])
        ]
    },
    {
        "id": "Q4",
        "topic": "Docker Security",
        "core_challenge": "docker history secret leak + 6 distinct vulns",
        "why_hard": "Many only find 2-3 issues",
        "task": """Audit this Dockerfile. For each vulnerability: name it, explain the exact attack vector,
assign severity (CRITICAL/HIGH/MEDIUM/LOW), and give the corrected line(s).

FROM ubuntu:latest
RUN apt-get install -y curl wget git
RUN echo "DB_PASSWORD=supersecret123" >> /etc/environment
COPY . /app
WORKDIR /app
RUN pip install -r requirements.txt
EXPOSE 22
EXPOSE 80
CMD ["/bin/sh", "-c", "chmod 777 /app && python app.py"]
""",
        "expected_points": [
            ("Unpinned / latest tag vulnerability", ["latest", "pinned", "digest", "ubuntu"]),
            ("Secret in image layer / docker history leak", ["history", "secret", "db_password", "environment", "layer"]),
            ("SSH / port 22 exposed", ["22", "ssh"]),
            ("chmod 777 / excessive permissions", ["777", "permissions", "world-writable"]),
            ("Running as root / missing USER", ["root", "user", "non-root"]),
            ("Apt clean / cache / recommends", ["recommends", "lists", "cache", "clean"])
        ]
    },
    {
        "id": "Q5",
        "topic": "Regex Email",
        "core_challenge": "12 cases, consecutive dots + label hyphens",
        "why_hard": "Most regex solutions fail 2-3 edge cases",
        "task": """Write a single Python regex pattern (only re.VERBOSE allowed) validating emails with:
1. Local part: 1-64 chars, a-zA-Z0-9._+- allowed, no consecutive dots, no leading/trailing dot
2. Exactly one @
3. Domain: labels separated by dots, each 1-63 chars alphanumeric+hyphen, no leading/trailing hyphen
4. TLD: 2-6 alpha chars only
5. Total length max 254 chars

Show pass/fail for each:
  VALID:   user@example.com, user.name+tag@sub.domain.co.uk, a@b.io, x@x.xx
  INVALID: @example.com, user@, user..name@example.com, user@example.c,
           user@-bad.com, user@bad-.com, user@example.toolong,
           (string of 253 a chars)@b.co
""",
        "expected_points": [
            ("Single regex with re.VERBOSE", ["re.VERBOSE", "re.compile"]),
            ("Consecutive dots prevention", ["consecutive", r"\.\.", r"(?!\.)"]),
            ("Domain label hyphen restrictions", ["hyphen", "leading", "trailing"]),
            ("TLD length 2-6 alpha restriction", ["{2,6}", "tld", "[a-zA-Z]"]),
            ("Total length limit <= 254", ["254", "(?=.{1,254}$)"]),
            ("Evaluation of all 12 test cases", ["user@example.com", "user@-bad.com", "valid", "invalid"])
        ]
    },
    {
        "id": "Q6",
        "topic": "CAP Theorem",
        "core_challenge": "CP vs AP misunderstanding + oversell design",
        "why_hard": "Engineers routinely conflate 'unavailable' and 'inconsistent'",
        "task": """A lead engineer says: "We'll use CP for inventory and AP for the cart.
During a partition, cart additions succeed but inventory deductions block."

Identify every technical flaw. Then design a concrete architecture handling:
  - No overselling (inventory must be exact)
  - Cart available even during region outages
  - Checkout completes in under 3 seconds p99
  - 100,000 concurrent checkouts

Specify real technologies, not just patterns. Give exact failure modes.
""",
        "expected_points": [
            ("Critique of 'blocks' vs rejection/unavailability", ["block", "reject", "partition", "cp", "timeout", "unavailable"]),
            ("Oversell window between AP cart and CP inventory", ["oversell", "stale", "drift", "discrepancy"]),
            ("Concrete tech choices (e.g. Redis, Cassandra/DynamoDB, Kafka)", ["redis", "dynamodb", "cassandra", "kafka", "postgres", "spanner"]),
            ("Atomic reservation mechanism (e.g. Lua, conditional)", ["decr", "lua", "atomic", "reservation", "decrement"]),
            ("Latency breakdown (<3s p99 for 100k checkouts)", ["latency", "p99", "ms", "seconds", "budget"]),
            ("Failure modes & compensation/saga", ["saga", "compensation", "rollback", "outbox", "failure"])
        ]
    },
    {
        "id": "Q7",
        "topic": "Memory Leak",
        "core_challenge": "3 bugs in asyncio server, 1 MiB per connection",
        "why_hard": "Primary bug is obvious but two subtle ones are often missed",
        "task": """This Python echo server leaks memory. Identify the exact cause(s), prove it with a
tracemalloc snapshot sequence, and fix it without changing observable server behavior.

import asyncio
from collections import defaultdict

class MetricsServer:
    def __init__(self):
        self.request_callbacks = defaultdict(list)
        self.active_connections = {}
        self._loop = asyncio.get_event_loop()

    def register_callback(self, endpoint, fn):
        self.request_callbacks[endpoint].append(fn)

    async def handle_connection(self, reader, writer):
        conn_id = id(writer)
        self.active_connections[conn_id] = {
            'writer': writer,
            'buffer': bytearray(1024 * 1024)
        }
        try:
            while True:
                data = await reader.read(4096)
                if not data:
                    break
                writer.write(data)
                await writer.drain()
        finally:
            writer.close()

    async def run(self, host, port):
        server = await asyncio.start_server(self.handle_connection, host, port)
        async with server:
            await server.serve_forever()
""",
        "expected_points": [
            ("Primary leak: active_connections not cleared in finally", ["active_connections", "del", "pop", "finally", "bytearray"]),
            ("Secondary leak: writer.close() without wait_closed()", ["wait_closed", "writer.close", "transport"]),
            ("Callback / defaultdict accumulation risk", ["request_callbacks", "callback", "unbounded", "endpoint"]),
            ("tracemalloc demonstration / code", ["tracemalloc", "snapshot", "take_snapshot", "compare_to"]),
            ("Corrected code provided", ["def handle_connection", "del self.active_connections", "wait_closed"])
        ]
    },
    {
        "id": "Q8",
        "topic": "Crypto Flaws",
        "core_challenge": "Length extension attack with Python PoC",
        "why_hard": "Must distinguish collision attack from length extension",
        "task": """Find every cryptographic flaw in this auth token system, explain the exact attack
for each (with a concrete exploit), and provide a secure replacement using only
Python stdlib: hmac, hashlib, secrets, base64.

import hashlib, time, json, base64
SECRET = "my_app_secret_2024"

def generate_token(user_id: int) -> str:
    payload = json.dumps({"user": user_id, "exp": time.time() + 3600})
    sig = hashlib.md5(SECRET.encode() + payload.encode()).hexdigest()
    return base64.b64encode(f"{payload}:{sig}".encode()).decode()

def verify_token(token: str) -> dict | None:
    try:
        decoded = base64.b64decode(token).decode()
        payload_str, sig = decoded.rsplit(":", 1)
        expected = hashlib.md5(SECRET.encode() + payload_str.encode()).hexdigest()
        if sig == expected:
            payload = json.loads(payload_str)
            if payload["exp"] > time.time():
                return payload
    except Exception:
        pass
    return None
""",
        "expected_points": [
            ("Length extension attack on hash(secret + message)", ["length extension", "merkle-damgard", "hash(secret"]),
            ("MD5 weakness / collision attack", ["md5", "collision", "broken"]),
            ("Timing attack on string comparison", ["timing", "compare_digest", "constant time"]),
            ("Hardcoded secret in code", ["hardcoded", "secret", "token_bytes", "env"]),
            ("HMAC-SHA256 replacement using stdlib", ["hmac.new", "sha256", "secrets.token_bytes", "hmac.compare_digest"])
        ]
    },
    {
        "id": "Q9",
        "topic": "Rate Limiter",
        "core_challenge": "Sliding window Lua script + clock skew",
        "why_hard": "Clock skew via redis.call('TIME') is almost always missed",
        "task": """Design a distributed rate limiter for an API gateway:
  - 50,000 req/sec across 20 servers
  - Limit: 1000 req/min per API key (sliding window semantics)
  - Accuracy: <= 5% overshoot
  - Decision latency: < 2ms p99
  - No single point of failure
  - Handle up to 500ms clock skew between servers

Explain why naive Redis INCR + EXPIRE fails for sliding window.
Give the exact Redis Lua script for your chosen algorithm.
Explain failure modes under Redis partition (fail-open vs fail-closed tradeoff).
""",
        "expected_points": [
            ("Explains why INCR + EXPIRE fails (boundary burst / 2x burst)", ["boundary", "burst", "fixed window", "2x", "window edge"]),
            ("Redis Lua script using sorted set (ZADD, ZREMRANGEBYSCORE, ZCARD)", ["zadd", "zremrangebyscore", "zcard", "lua"]),
            ("Solves clock skew via redis.call('TIME')", ["redis.call('time')", "redis.call(\"time\")", "redis time", "server time", "skew"]),
            ("High availability architecture (Cluster/Sentinel)", ["cluster", "sentinel", "replica"]),
            ("Fail-open vs fail-closed analysis under partition", ["fail-open", "fail-closed", "partition", "availability"])
        ]
    },
    {
        "id": "Q10",
        "topic": "XOR Three Uniques",
        "core_challenge": "XOR partition with 2-singles-in-one-group case",
        "why_hard": "Nearly all naive XOR attempts fail this edge case",
        "task": """You have an array where every element appears exactly twice EXCEPT three elements
that each appear exactly once. Find all three in O(n) time and O(1) space.
You may NOT sort, use a hash map, or use more than O(1) extra integer variables.

Prove your algorithm is correct. Implement in Python. Pass all tests:
  find_three([1,1,2,2,3,3,4,4,5,6,7]) -> {5,6,7}
  find_three([1,2,3])                  -> {1,2,3}
  find_three([0,0,1,1,2,3,4,2])        -> {3,4}   (wait: 3 and 4 appear once; check count)

Note: XOR of all elements gives X^Y^Z. Extend the classic single-unique trick to three.
Show your reasoning step by step, including how you handle the case where a bit partition
puts 2 singles in one group.
""",
        "expected_points": [
            ("XOR all elements to get X ^ Y ^ Z", ["x ^ y ^ z", "xor all", "total xor"]),
            ("Bit partitioning logic and bit selection", ["bit", "partition", "lowest set bit", "set bit"]),
            ("Handling 2-singles in one group and 1 in other", ["2 singles", "two singles", "one single", "sub-partition", "group"]),
            ("Correct handling/observation on test cases", ["{5,6,7}", "{1,2,3}", "{3,4}", "frequency"]),
            ("Working Python implementation and proof", ["def find_three", "o(1) space", "o(n) time", "proof"])
        ]
    }
]

def call_groq(prompt, retries=5):
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": "You are an expert computer scientist, systems architect, and security engineer. Provide rigorous, complete, and fully verified answers."},
            {"role": "user", "content": prompt}
        ],
        "max_completion_tokens": 3500,
        "temperature": 0.2
    }
    data = json.dumps(payload).encode("utf-8")
    
    for attempt in range(retries):
        req = urllib.request.Request(
            GROQ_URL,
            data=data,
            headers={
                "Authorization": f"Bearer {API_KEY}",
                "Content-Type": "application/json",
                "User-Agent": "arena-evaluator/1.0"
            }
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                res_body = resp.read().decode("utf-8")
                res_json = json.loads(res_body)
                content = res_json["choices"][0]["message"]["content"]
                usage = res_json.get("usage", {})
                return content, usage
        except urllib.error.HTTPError as e:
            err_text = e.read().decode("utf-8", errors="ignore")
            print(f"HTTPError {e.code}: {err_text[:200]}")
            if e.code == 429:
                wait_sec = 15 + (attempt * 10)
                # Check for retry-after
                retry_after = e.headers.get("retry-after")
                if retry_after:
                    try:
                        wait_sec = max(wait_sec, float(retry_after) + 2)
                    except ValueError:
                        pass
                print(f"Rate limited (429). Sleeping {wait_sec}s before retry {attempt+1}/{retries}...")
                time.sleep(wait_sec)
            else:
                time.sleep(5)
        except Exception as e:
            print(f"Exception during call: {e}")
            time.sleep(5)
            
    raise RuntimeError("Failed to get response from Groq after retries")

def evaluate_response(q, response_text):
    text_lower = response_text.lower()
    scores = []
    total_weight = len(q["expected_points"])
    matched_count = 0
    details = []
    
    for point_name, keywords in q["expected_points"]:
        matched = any(kw.lower() in text_lower for kw in keywords)
        if matched:
            matched_count += 1
            details.append({"criterion": point_name, "status": "PASS"})
        else:
            details.append({"criterion": point_name, "status": "MISS"})
            
    pct = (matched_count / total_weight) * 100
    return {
        "score_pct": pct,
        "matched": matched_count,
        "total": total_weight,
        "details": details
    }

def main():
    results = []
    os.makedirs("eval_results", exist_ok=True)
    
    print(f"Starting Evaluation of 10 Hard Arena Questions on Groq ({MODEL})...")
    print("=" * 70)
    
    for i, q in enumerate(QUESTIONS, 1):
        print(f"\n[Running {q['id']}/Q10]: {q['topic']} ...")
        print(f"  Core Challenge: {q['core_challenge']}")
        print(f"  Why It's Hard: {q['why_hard']}")
        
        t0 = time.time()
        try:
            answer, usage = call_groq(q["task"])
            elapsed = time.time() - t0
            eval_res = evaluate_response(q, answer)
            
            print(f"  [OK] Answer received in {elapsed:.1f}s (completion tokens: {usage.get('completion_tokens', 'N/A')})")
            print(f"  Score: {eval_res['score_pct']:.1f}% ({eval_res['matched']}/{eval_res['total']} criteria met)")
            for d in eval_res['details']:
                mark = "[PASS]" if d['status'] == "PASS" else "[MISS]"
                print(f"    {mark} {d['criterion']}")
                
            q_result = {
                "id": q["id"],
                "topic": q["topic"],
                "core_challenge": q["core_challenge"],
                "why_hard": q["why_hard"],
                "prompt": q["task"],
                "answer": answer,
                "usage": usage,
                "elapsed_sec": elapsed,
                "eval": eval_res
            }
            results.append(q_result)
            
            # Save progress after each question
            with open(f"eval_results/{q['id'].lower()}_result.json", "w", encoding="utf-8") as f:
                json.dump(q_result, f, indent=2)
                
            # Sleep 5 seconds to respect TPM quota
            time.sleep(5)
            
        except Exception as e:
            print(f"  [FAIL] Failed {q['id']}: {e}")
            results.append({
                "id": q["id"],
                "topic": q["topic"],
                "error": str(e)
            })

    # Save full summary
    with open("eval_results/full_eval_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
        
    print("\n" + "=" * 70)
    print("ALL QUESTIONS EVALUATED. Results saved to eval_results/")

if __name__ == "__main__":
    main()
