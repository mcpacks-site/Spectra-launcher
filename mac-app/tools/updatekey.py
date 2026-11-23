#!/usr/bin/env python3
"""Spectra update signing (Ed25519, your own key — nothing to do with Apple).

  python3 tools/updatekey.py gen  <private.key> <update-public.key>
  python3 tools/updatekey.py sign <private.key> <version> <zip> <url> <out latest.json> [notes]
                                  [--updater <version> <updater zip> <updater url>]

Needs:  pip install cryptography
Keep private.key secret (add its contents as the GitHub secret SPECTRA_UPDATE_KEY). The public
key is safe to commit; the Updater only accepts updates signed by the matching private key.
"""
import sys, json, base64, hashlib
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization as S

def raw_priv(k):  return k.private_bytes(S.Encoding.Raw, S.PrivateFormat.Raw, S.NoEncryption())
def raw_pub(k):   return k.public_key().public_bytes(S.Encoding.Raw, S.PublicFormat.Raw)

def message(version, sha256, url):          # must match SpectraShared/Manifest.swift
    return f"spectra-update\n{version}\n{sha256}\n{url}".encode()

def updater_message(version, sha256, url):  # must match SpectraShared UpdaterInfo.signedMessage
    return f"spectra-updater\n{version}\n{sha256}\n{url}".encode()

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
        rest = a[:]
        upd = None
        if "--updater" in rest:
            i = rest.index("--updater")
            upd = rest[i + 1:i + 4]
            rest = rest[:i]
            if len(upd) != 3:
                print(__doc__); sys.exit(1)
        key, version, zp, url, out = load(rest[2]), rest[3], rest[4], rest[5], rest[6]
        notes = rest[7] if len(rest) > 7 else ""
        digest = sha256_file(zp)
        sig = base64.b64encode(key.sign(message(version, digest, url))).decode()
        data = {"version": version, "notes": notes, "url": url, "sha256": digest, "sig": sig}
        if upd:
            uv, uz, uu = upd
            ud = sha256_file(uz)
            data["updater"] = {"version": uv, "url": uu, "sha256": ud,
                               "sig": base64.b64encode(key.sign(updater_message(uv, ud, uu))).decode()}
        json.dump(data, open(out, "w"), indent=2)
        print(f"Wrote {out} for {version}" + (f" (+ updater {upd[0]})" if upd else ""))
    else:
        print(__doc__); sys.exit(1)

main(sys.argv)
