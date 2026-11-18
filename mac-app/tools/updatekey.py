#!/usr/bin/env python3

import sys, json, base64, hashlib
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization as S

def raw_priv(k):  return k.private_bytes(S.Encoding.Raw, S.PrivateFormat.Raw, S.NoEncryption())
def raw_pub(k):   return k.public_key().public_bytes(S.Encoding.Raw, S.PublicFormat.Raw)

def message(version, sha256, url):          # must match SpectraShared/Manifest.swift
    return f"spectra-update\n{version}\n{sha256}\n{url}".encode()

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

def load(path):
    return Ed25519PrivateKey.from_private_bytes(base64.b64decode(open(path).read().strip()))

def main(a):
    if len(a) >= 4 and a[1] == "gen":
        k = Ed25519PrivateKey.generate()
        open(a[2], "w").write(base64.b64encode(raw_priv(k)).decode() + "\n")
        open(a[3], "w").write(base64.b64encode(raw_pub(k)).decode() + "\n")
        print(f"Wrote {a[2]} (SECRET) and {a[3]} (public, commit it).")
    elif len(a) >= 7 and a[1] == "sign":
        key, version, zp, url, out = load(a[2]), a[3], a[4], a[5], a[6]
        notes = a[7] if len(a) > 7 else ""
        digest = sha256_file(zp)
        sig = base64.b64encode(key.sign(message(version, digest, url))).decode()
        json.dump({"version": version, "notes": notes, "url": url, "sha256": digest, "sig": sig},
                  open(out, "w"), indent=2)
        print(f"Wrote {out} for {version}")
    else:
        print(__doc__); sys.exit(1)

main(sys.argv)
