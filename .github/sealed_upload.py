#!/usr/bin/env python3
"""Sealed upload of reel files to Zernio storage (nua, Stay With Me).

Presigned upload URLs are write tokens, so they never sit in this public repo in plain text:

1. Each run makes a throwaway RSA key pair. The private key stays on this runner and is never printed.
2. The public key is committed to the uploader-results branch as keys/<run sha>.pem.
3. Claude encrypts the presigned URLs with that key and pushes jobs/<run sha>.enc and
   jobs/<run sha>.key to this branch (commit marked [skip ci], so it starts no new run).
4. This run decrypts them, uploads every file after checking it against the sha256 in request.json,
   downloads each public URL again to confirm the bytes match, and commits results/<run sha>.json
   (ids and status codes only, no URLs).
"""
import base64
import concurrent.futures as cf
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import time

REPO = os.environ["GITHUB_REPOSITORY"]
SHA = os.environ["GITHUB_SHA"]
TMP = pathlib.Path(os.environ.get("RUNNER_TEMP", "/tmp")) / "sealed"
FILES = TMP / "files"
FILES.mkdir(parents=True, exist_ok=True)
WAIT_MINUTES = 55


def run(args, data=None):
    """Run a command without ever echoing its arguments (they can hold URLs)."""
    r = subprocess.run(args, input=data, capture_output=True)
    return r.returncode, r.stdout, r.stderr.decode(errors="replace")[-300:]


def publish(path, payload, msg):
    body = json.dumps({"message": msg, "branch": "uploader-results",
                       "content": base64.b64encode(payload).decode()}).encode()
    for attempt in range(6):
        code, _, err = run(["gh", "api", "-X", "PUT", f"repos/{REPO}/contents/{path}", "--input", "-"], body)
        if code == 0:
            return True
        print(f"publish {path} failed (try {attempt + 1}): {err}", flush=True)
        time.sleep(3 + 3 * attempt)
    return False


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch_source(item):
    dest = FILES / f"{item['id']}.mp4"
    for attempt in range(4):
        code, out, err = run(["curl", "-sSfL", "--retry", "3", "-o", str(dest), "-w", "%{http_code}", item["src"]])
        if code == 0 and dest.exists() and dest.stat().st_size == item["size"] and sha256(dest) == item["sha256"]:
            return item["id"], "ok"
        time.sleep(5 * (attempt + 1))
    return item["id"], f"source check failed ({code}) {err[-120:]}"


def upload(job, src_status):
    out = {"source": src_status}
    if src_status != "ok":
        return job["id"], out
    path = FILES / f"{job['id']}.mp4"
    for attempt in range(3):
        code, stdout, err = run(["curl", "-sS", "-o", "/dev/null", "-w", "%{http_code}", "-X", "PUT",
                                 "-H", "Content-Type: video/mp4", "--data-binary", f"@{path}", job["put"]])
        out["put"] = stdout.decode().strip() or f"curl {code}"
        if out["put"] == "200":
            break
        time.sleep(4 * (attempt + 1))
    if out["put"] != "200":
        return job["id"], out
    check = FILES / f"{job['id']}.check"
    want = sha256(path)
    for attempt in range(4):
        code, stdout, err = run(["curl", "-sSL", "-o", str(check), "-w", "%{http_code} %{content_type}", job["public"]])
        out["get"] = stdout.decode().strip()
        if code == 0 and out["get"].startswith("200") and check.exists() and sha256(check) == want:
            out["verify"] = "sha256 match"
            break
        out["verify"] = "mismatch or unreachable"
        time.sleep(5 * (attempt + 1))
    check.unlink(missing_ok=True)
    return job["id"], out


def main():
    request = json.load(open("request.json"))
    items = {f["id"]: f for f in request["files"]}
    print(f"batch {request.get('batch')} with {len(items)} files", flush=True)

    key, pub = TMP / "k.pem", TMP / "pub.pem"
    subprocess.run(["openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:3072",
                    "-out", str(key)], check=True, capture_output=True)
    os.chmod(key, 0o600)
    subprocess.run(["openssl", "pkey", "-in", str(key), "-pubout", "-out", str(pub)], check=True, capture_output=True)
    if not publish(f"keys/{SHA}.pem", pub.read_bytes(), f"public key for {SHA} [skip ci]"):
        sys.exit("could not publish the public key")
    print("public key published", flush=True)

    with cf.ThreadPoolExecutor(4) as ex:
        sources = dict(ex.map(fetch_source, items.values()))
    print("sources:", json.dumps(sources), flush=True)

    enc, sealed_key = TMP / "jobs.enc", TMP / "jobs.key"
    deadline = time.time() + WAIT_MINUTES * 60
    while time.time() < deadline:
        run(["git", "fetch", "-q", "--depth", "1", "origin", "uploader"])
        c1, data_enc, _ = run(["git", "show", f"FETCH_HEAD:jobs/{SHA}.enc"])
        c2, data_key, _ = run(["git", "show", f"FETCH_HEAD:jobs/{SHA}.key"])
        if c1 == 0 and c2 == 0:
            enc.write_bytes(data_enc)
            sealed_key.write_bytes(data_key)
            break
        time.sleep(10)
    else:
        publish(f"results/{SHA}.json", json.dumps({"error": "no sealed jobs arrived", "sources": sources}, indent=1).encode(),
                f"upload results {SHA} [skip ci]")
        sys.exit("no sealed jobs arrived in time")

    passfile, plain = TMP / "pass.txt", TMP / "jobs.json"
    subprocess.run(["openssl", "pkeyutl", "-decrypt", "-inkey", str(key), "-pkeyopt", "rsa_padding_mode:oaep",
                    "-pkeyopt", "rsa_oaep_md:sha256", "-pkeyopt", "rsa_mgf1_md:sha256",
                    "-in", str(sealed_key), "-out", str(passfile)], check=True, capture_output=True)
    subprocess.run(["openssl", "enc", "-d", "-aes-256-cbc", "-pbkdf2", "-iter", "200000", "-md", "sha256",
                    "-pass", f"file:{passfile}", "-in", str(enc), "-out", str(plain)], check=True, capture_output=True)
    jobs = json.load(open(plain))
    for p in (plain, passfile, key):
        p.unlink(missing_ok=True)
    print(f"{len(jobs)} sealed jobs decrypted", flush=True)

    results = {}
    with cf.ThreadPoolExecutor(4) as ex:
        futures = [ex.submit(upload, j, sources.get(j["id"], "not in request")) for j in jobs]
        for fut in cf.as_completed(futures):
            jid, out = fut.result()
            results[jid] = out
            print(jid, json.dumps(out), flush=True)
    ok = sum(1 for r in results.values() if r.get("verify") == "sha256 match")
    summary = {"batch": request.get("batch"), "ok": ok, "total": len(jobs), "results": dict(sorted(results.items()))}
    publish(f"results/{SHA}.json", json.dumps(summary, indent=1).encode(), f"upload results {SHA}: {ok}/{len(jobs)} [skip ci]")
    print(f"done: {ok}/{len(jobs)} verified", flush=True)


if __name__ == "__main__":
    main()
