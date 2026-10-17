#!/usr/bin/env python3
"""
Spectra Launcher  -  a free, open-source launcher for Minecraft: Java Edition with Fabric
=========================================================================================
Not an official Minecraft product. Not affiliated with Mojang, Microsoft or the Fabric project.

* Multiple instances, each with its own Minecraft version, mods, memory, Java args
* Downloads Minecraft, libraries, assets, Fabric Loader and Fabric API automatically
* Downloads a matching Java runtime (Eclipse Temurin) if yours is too old
* Mod manager: search Modrinth, install with required dependencies, enable/disable/remove
* Microsoft account sign-in (device-code flow). Only accounts that own
  Minecraft: Java Edition can sign in and launch the game.

Requires Python 3.8+ with tkinter. No third-party packages.
Run:  python fabric_launcher.py

MICROSOFT SIGN-IN
  Uses the Azure app ID in CLIENT_ID below. Mojang must approve the app before the
  Minecraft login step works: https://aka.ms/AppRegInfo
  The Azure app must allow personal Microsoft accounts and "Allow public client flows" = Yes.
"""
import hashlib
import json
import os
import platform
import queue
import re
import shlex
import shutil
import ssl
import subprocess
import tarfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import tkinter as tk
from tkinter import messagebox, ttk

# --------------------------------------------------------------------------
# Constants / paths
# --------------------------------------------------------------------------
APP_NAME = "Spectra Launcher"
APP_SLUG = "SpectraLauncher"
APP_VERSION = "2.1"
CLIENT_ID = "952311fd-b915-41d2-8183-9c3b425d7d3c"
UA = f"{APP_SLUG}/{APP_VERSION} (open-source launcher)"
MANIFEST_URL = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
FABRIC_META = "https://meta.fabricmc.net/v2"
FABRIC_MAVEN = "https://maven.fabricmc.net/"
ASSET_URL = "https://resources.download.minecraft.net"
MODRINTH = "https://api.modrinth.com/v2"
FABRIC_API_SLUG = "fabric-api"
NOWIN = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def _os_name():
    return {"Windows": "windows", "Darwin": "osx"}.get(platform.system(), "linux")


OS = _os_name()
MACHINE = platform.machine().lower()
IS_ARM64 = MACHINE in ("arm64", "aarch64")
IS_X86_32 = MACHINE in ("i386", "i686", "x86")


def default_root() -> Path:
    if OS == "windows":
        base = Path(os.environ.get("APPDATA", Path.home()))
    elif OS == "osx":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path.home() / ".local" / "share"
    return base / APP_SLUG


ROOT = default_root()
LIBS = ROOT / "libraries"
ASSETS = ROOT / "assets"
VERSIONS = ROOT / "versions"
INSTANCES = ROOT / "instances"
RUNTIME = ROOT / "runtime"
CONFIG = ROOT / "launcher_config.json"
ACCOUNTS = ROOT / "accounts.json"


# --------------------------------------------------------------------------
# TLS certificates
# Python from python.org on macOS ships without trusted root certificates until the
# user runs "Install Certificates.command". Load a CA bundle ourselves so downloads
# work out of the box. Certificate verification always stays ON.
# --------------------------------------------------------------------------
CA_BUNDLES = (
    "/etc/ssl/cert.pem",                      # macOS system bundle
    "/private/etc/ssl/cert.pem",
    "/etc/ssl/certs/ca-certificates.crt",     # Debian/Ubuntu
    "/etc/pki/tls/certs/ca-bundle.crt",       # Fedora/RHEL
    "/etc/ssl/ca-bundle.pem",                 # openSUSE
)


def make_ssl_context():
    try:
        import certifi  # optional; used if installed
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # noqa: BLE001
        pass
    ctx = ssl.create_default_context()
    if not ctx.get_ca_certs():
        for p in CA_BUNDLES:
            if os.path.exists(p):
                try:
                    ctx.load_verify_locations(cafile=p)
                    break
                except (ssl.SSLError, OSError):
                    continue
    return ctx


urllib.request.install_opener(
    urllib.request.build_opener(urllib.request.HTTPSHandler(context=make_ssl_context())))


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------
def load_json(path, default):
    try:
        return json.loads(Path(path).read_text())
    except Exception:  # noqa: BLE001
        return default


def save_json(path, data, private=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))
    if private and os.name != "nt":
        try:
            path.chmod(0o600)
        except OSError:
            pass


def open_path(p):
    p = Path(p)
    p.mkdir(parents=True, exist_ok=True)
    if OS == "windows":
        os.startfile(str(p))  # noqa: S606
    elif OS == "osx":
        subprocess.Popen(["open", str(p)])
    else:
        subprocess.Popen(["xdg-open", str(p)])


# --------------------------------------------------------------------------
# HTTP helpers
# --------------------------------------------------------------------------
def http_get(url, timeout=60):
    last = None
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise IOError(f"Failed to download {url}: {last}")


def get_json(url):
    return json.loads(http_get(url, 30))


def http_json(url, data=None, form=False, headers=None, timeout=30):
    """Single request returning (status, parsed_json). Never raises on HTTP errors."""
    hdrs = {"User-Agent": UA, "Accept": "application/json"}
    body = None
    if data is not None:
        if form:
            body = urllib.parse.urlencode(data).encode()
            hdrs["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            body = json.dumps(data).encode()
            hdrs["Content-Type"] = "application/json"
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, data=body, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except Exception:  # noqa: BLE001
            return e.code, {"raw": raw.decode("utf-8", "replace")}


def sha1_of(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url, dest, sha1=None, size=None):
    """Download url -> dest unless a valid copy exists. Returns True if downloaded."""
    dest = Path(dest)
    if dest.exists():
        if sha1:
            if sha1_of(dest) == sha1:
                return False
        elif size is None or dest.stat().st_size == size:
            return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    data = http_get(url)
    if sha1 and hashlib.sha1(data).hexdigest() != sha1:
        raise IOError(f"Checksum mismatch for {url}")
    tmp = dest.with_name(dest.name + ".part")
    tmp.write_bytes(data)
    tmp.replace(dest)
    return True


# --------------------------------------------------------------------------
# Mojang rules / maven helpers
# --------------------------------------------------------------------------
def _arch_match(arch):
    if arch == "x86":
        return IS_X86_32
    if arch == "arm64":
        return IS_ARM64
    return True


def _rule_matches(rule):
    if "features" in rule and any(rule["features"].values()):
        return False  # we enable no optional features (demo, custom resolution...)
    o = rule.get("os")
    if o:
        if "name" in o and o["name"] != OS:
            return False
        if "arch" in o and not _arch_match(o["arch"]):
            return False
    return True


def rules_ok(rules):
    if not rules:
        return True
    allowed = False
    for r in rules:
        if _rule_matches(r):
            allowed = r.get("action") == "allow"
    return allowed


def maven_path(name):
    ext = "jar"
    if "@" in name:
        name, ext = name.split("@", 1)
    p = name.split(":")
    g, a, v = p[0], p[1], p[2]
    c = p[3] if len(p) > 3 else None
    fn = f"{a}-{v}" + (f"-{c}" if c else "") + f".{ext}"
    return f"{g.replace('.', '/')}/{a}/{v}/{fn}"


def lib_key(name):
    p = name.split("@")[0].split(":")
    return ":".join([p[0], p[1], p[3] if len(p) > 3 else ""])


# --------------------------------------------------------------------------
# Java detection / download
# --------------------------------------------------------------------------
def java_major(exe):
    try:
        r = subprocess.run([str(exe), "-version"], capture_output=True, text=True,
                           timeout=20, creationflags=NOWIN)
        m = re.search(r'version "(\d+)(?:\.(\d+))?', r.stderr + r.stdout)
        if not m:
            return None
        a = int(m.group(1))
        return int(m.group(2) or 0) if a == 1 else a
    except Exception:  # noqa: BLE001
        return None


def find_java_in(folder: Path):
    exe = "java.exe" if OS == "windows" else "java"
    for p in folder.rglob(exe):
        if p.parent.name == "bin" and p.is_file():
            return p
    return None


# --------------------------------------------------------------------------
# Instances
# --------------------------------------------------------------------------
def list_instances():
    out = []
    for f in sorted(INSTANCES.glob("*/instance.json")):
        d = load_json(f, None)
        if d and d.get("id"):
            out.append(d)
    return out


def save_instance(inst):
    save_json(INSTANCES / inst["id"] / "instance.json", inst)


def new_instance_id(name):
    base = re.sub(r"[^\w]+", "-", name).strip("-").lower() or "instance"
    cand, n = base, 2
    while (INSTANCES / cand).exists():
        cand = f"{base}-{n}"
        n += 1
    return cand


def game_dir_of(inst):
    return INSTANCES / inst["id"] / "minecraft"


# --------------------------------------------------------------------------
# Microsoft / Xbox / Minecraft authentication (device-code flow)
# --------------------------------------------------------------------------
MS_BASE = "https://login.microsoftonline.com/consumers/oauth2/v2.0"
MS_SCOPE = "XboxLive.signin offline_access"
XERR = {
    2148916233: "This Microsoft account has no Xbox account. Sign in once at minecraft.net to create one.",
    2148916235: "Xbox Live is not available in your country/region.",
    2148916236: "This account needs adult verification on the Xbox page.",
    2148916237: "This account needs adult verification on the Xbox page.",
    2148916238: "This is a child account; add it to a Microsoft Family and allow multiplayer first.",
}


class AuthError(Exception):
    pass


class MSAuth:
    def __init__(self, client_id=CLIENT_ID):
        self.cid = client_id

    def start_device(self):
        st, j = http_json(f"{MS_BASE}/devicecode", {"client_id": self.cid, "scope": MS_SCOPE}, form=True)
        if st != 200:
            raise AuthError(j.get("error_description") or str(j))
        return j

    def poll_device(self, dc, cancel):
        interval = int(dc.get("interval", 5))
        deadline = time.time() + int(dc.get("expires_in", 900))
        while time.time() < deadline:
            for _ in range(interval * 2):
                if cancel.is_set():
                    raise AuthError("Sign-in cancelled.")
                time.sleep(0.5)
            st, j = http_json(f"{MS_BASE}/token", {
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "client_id": self.cid, "device_code": dc["device_code"]}, form=True)
            if st == 200:
                return j
            err = j.get("error")
            if err == "authorization_pending":
                continue
            if err == "slow_down":
                interval += 5
                continue
            raise AuthError(j.get("error_description") or err or str(j))
        raise AuthError("Sign-in timed out.")

    def refresh(self, refresh_token):
        st, j = http_json(f"{MS_BASE}/token", {
            "grant_type": "refresh_token", "client_id": self.cid,
            "refresh_token": refresh_token, "scope": MS_SCOPE}, form=True)
        if st != 200:
            raise AuthError("Your Microsoft session expired. Please sign in again from Accounts.")
        return j

    def minecraft_account(self, tok):
        """Exchange a Microsoft token response for a Minecraft account dict.
        Fails unless the account owns Minecraft: Java Edition."""
        st, x = http_json("https://user.auth.xboxlive.com/user/authenticate", {
            "Properties": {"AuthMethod": "RPS", "SiteName": "user.auth.xboxlive.com",
                           "RpsTicket": "d=" + tok["access_token"]},
            "RelyingParty": "http://auth.xboxlive.com", "TokenType": "JWT"})
        if st != 200:
            raise AuthError("Xbox Live sign-in failed.")
        xbl = x["Token"]
        st, x = http_json("https://xsts.auth.xboxlive.com/xsts/authorize", {
            "Properties": {"SandboxId": "RETAIL", "UserTokens": [xbl]},
            "RelyingParty": "rp://api.minecraftservices.com/", "TokenType": "JWT"})
        if st != 200:
            raise AuthError(XERR.get(x.get("XErr"), f"Xbox authorization failed ({x.get('XErr')})."))
        xsts, uhs = x["Token"], x["DisplayClaims"]["xui"][0]["uhs"]
        st, m = http_json("https://api.minecraftservices.com/authentication/login_with_xbox",
                          {"identityToken": f"XBL3.0 x={uhs};{xsts}"})
        if st != 200:
            raise AuthError("Minecraft login failed. This launcher may not be approved by Mojang yet. "
                            f"Details: {m.get('errorMessage') or m.get('error') or st}")
        mc_token = m["access_token"]
        st, p = http_json("https://api.minecraftservices.com/minecraft/profile",
                          headers={"Authorization": "Bearer " + mc_token})
        if st == 404:
            raise AuthError("This Microsoft account does not own Minecraft: Java Edition.")
        if st != 200:
            raise AuthError("Could not read your Minecraft profile.")
        return {"type": "msa", "username": p["name"], "uuid": p["id"],
                "access_token": mc_token,
                "expires_at": time.time() + int(m.get("expires_in", 86400)),
                "refresh_token": tok.get("refresh_token", "")}


def acct_key(a):
    return f"{a['type']}:{a.get('uuid') or a['username']}"


def acct_label(a):
    return a["username"]


# --------------------------------------------------------------------------
# Modrinth
# --------------------------------------------------------------------------
def install_project(mc, project, mods_dir: Path, installed: dict, log, seen=None):
    """Install the newest compatible Fabric build of a Modrinth project + required deps.
    `installed` maps project_id -> filename and is updated in place."""
    seen = seen if seen is not None else set()
    if project in seen:
        return
    seen.add(project)
    q = urllib.parse.urlencode({"game_versions": json.dumps([mc]), "loaders": json.dumps(["fabric"])})
    versions = get_json(f"{MODRINTH}/project/{project}/version?{q}")
    if not versions:
        log(f"No Fabric build of '{project}' for Minecraft {mc}.")
        return
    pick = next((v for v in versions if v.get("version_type") == "release"), versions[0])
    f = next((x for x in pick["files"] if x.get("primary")), pick["files"][0])
    pid = pick["project_id"]
    seen.add(pid)
    mods_dir.mkdir(parents=True, exist_ok=True)
    old = installed.get(pid)
    if old and old != f["filename"]:
        for suffix in ("", ".disabled"):
            p = mods_dir / (old + suffix)
            if p.exists():
                p.unlink()
    new = download(f["url"], mods_dir / f["filename"], f["hashes"].get("sha1"), f.get("size"))
    installed[pid] = f["filename"]
    log(f"{pick.get('name') or project}: {f['filename']} " + ("downloaded." if new else "up to date."))
    for d in pick.get("dependencies", []):
        if d.get("dependency_type") == "required" and d.get("project_id"):
            install_project(mc, d["project_id"], mods_dir, installed, log, seen)


# --------------------------------------------------------------------------
# Core installer / launcher
# --------------------------------------------------------------------------
class Core:
    def __init__(self, log, progress):
        self.log = log
        self.progress = progress

    def download_all(self, jobs, label, workers=16):
        total = len(jobs)
        if not total:
            return
        done = 0
        with ThreadPoolExecutor(workers) as ex:
            futs = [ex.submit(download, *j) for j in jobs]
            for f in as_completed(futs):
                f.result()
                done += 1
                if done % 5 == 0 or done == total:
                    self.progress(done, total, label)

    def ensure_java(self, required, user_path):
        if user_path:
            m = java_major(user_path)
            if m and m >= required:
                return user_path
            self.log(f"Configured Java is {m or 'invalid'}, need {required}+; looking elsewhere.")
        managed = RUNTIME / str(required)
        if managed.exists():
            j = find_java_in(managed)
            if j and (java_major(j) or 0) >= required:
                return str(j)
        cands = []
        if os.environ.get("JAVA_HOME"):
            cands.append(Path(os.environ["JAVA_HOME"]) / "bin" / ("java.exe" if OS == "windows" else "java"))
        w = shutil.which("java")
        if w:
            cands.append(w)
        for c in cands:
            m = java_major(c)
            if m and m >= required:
                return str(c)
        return self.download_java(required, managed)

    def download_java(self, major, dest: Path):
        os_ = {"windows": "windows", "osx": "mac", "linux": "linux"}[OS]
        arch = "aarch64" if IS_ARM64 else ("x64" if not IS_X86_32 else "x32")
        url = (f"https://api.adoptium.net/v3/binary/latest/{major}/ga/{os_}/{arch}"
               f"/jre/hotspot/normal/eclipse")
        self.log(f"Downloading Java {major} runtime (one-time, ~50 MB)...")
        data = http_get(url, 300)
        dest.mkdir(parents=True, exist_ok=True)
        tmp = dest / "download.tmp"
        tmp.write_bytes(data)
        self.log("Extracting Java...")
        if data[:2] == b"PK":
            with zipfile.ZipFile(tmp) as z:
                z.extractall(dest)
        else:
            with tarfile.open(tmp) as t:
                t.extractall(dest)
        tmp.unlink()
        j = find_java_in(dest)
        if not j:
            raise IOError("Could not find java executable after extracting runtime.")
        if OS != "windows":
            j.chmod(0o755)
        return str(j)

    def prepare(self, inst, acct):
        if acct.get("type") != "msa" or not acct.get("access_token"):
            raise IOError("Please sign in with a Microsoft account that owns Minecraft: Java Edition.")
        mc = inst["version"]
        self.log(f"Preparing '{inst['name']}' (Minecraft {mc} + Fabric)...")

        manifest = get_json(MANIFEST_URL)
        entry = next((v for v in manifest["versions"] if v["id"] == mc), None)
        if not entry:
            raise IOError(f"Minecraft version {mc} not found in Mojang manifest.")
        vdir = VERSIONS / mc
        vdir.mkdir(parents=True, exist_ok=True)
        vjson_path = vdir / f"{mc}.json"
        download(entry["url"], vjson_path, entry.get("sha1"))
        vanilla = json.loads(vjson_path.read_text())

        loaders = get_json(f"{FABRIC_META}/versions/loader/{mc}")
        if not loaders:
            raise IOError(f"Fabric does not support Minecraft {mc}.")
        pick = next((l for l in loaders if l["loader"].get("stable")), loaders[0])
        lv = pick["loader"]["version"]
        self.log(f"Using Fabric Loader {lv}")
        fabric = get_json(f"{FABRIC_META}/versions/loader/{mc}/{lv}/profile/json")
        fid = fabric["id"]
        fdir = VERSIONS / fid
        fdir.mkdir(parents=True, exist_ok=True)
        (fdir / f"{fid}.json").write_text(json.dumps(fabric, indent=2))

        client = vanilla["downloads"]["client"]
        client_jar = vdir / f"{mc}.jar"
        self.log("Checking Minecraft client...")
        download(client["url"], client_jar, client["sha1"], client["size"])

        jobs, cp, natives = [], {}, []
        for lib in vanilla["libraries"]:
            if not rules_ok(lib.get("rules")):
                continue
            dl = lib.get("downloads", {})
            if "natives" in lib:
                key = lib["natives"].get(OS)
                if key:
                    key = key.replace("${arch}", "32" if IS_X86_32 else "64")
                    c = dl.get("classifiers", {}).get(key)
                    if c:
                        p = LIBS / c["path"]
                        jobs.append((c["url"], p, c["sha1"], c["size"]))
                        natives.append((p, lib.get("extract", {}).get("exclude", [])))
            art = dl.get("artifact")
            if art:
                p = LIBS / art["path"]
                jobs.append((art["url"], p, art["sha1"], art["size"]))
                cp[lib_key(lib["name"])] = p
        for lib in fabric["libraries"]:
            rel = maven_path(lib["name"])
            base = lib.get("url", FABRIC_MAVEN)
            p = LIBS / rel
            jobs.append((base.rstrip("/") + "/" + rel, p, lib.get("sha1"), lib.get("size")))
            cp[lib_key(lib["name"])] = p
        self.log(f"Checking {len(jobs)} libraries...")
        self.download_all(jobs, "Libraries")

        natives_dir = vdir / "natives"
        natives_dir.mkdir(parents=True, exist_ok=True)
        for jar, excludes in natives:
            with zipfile.ZipFile(jar) as z:
                for n in z.namelist():
                    if n.endswith("/") or any(n.startswith(e) for e in excludes):
                        continue
                    target = natives_dir / n
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(n) as src, open(target, "wb") as dst:
                        shutil.copyfileobj(src, dst)

        ai = vanilla["assetIndex"]
        idx_path = ASSETS / "indexes" / f"{ai['id']}.json"
        download(ai["url"], idx_path, ai["sha1"])
        objects = json.loads(idx_path.read_text())["objects"]
        ajobs = []
        for o in objects.values():
            h = o["hash"]
            ajobs.append((f"{ASSET_URL}/{h[:2]}/{h}", ASSETS / "objects" / h[:2] / h, None, o["size"]))
        self.log(f"Checking {len(ajobs)} game assets (first run takes a few minutes)...")
        self.download_all(ajobs, "Assets", workers=24)

        game_dir = game_dir_of(inst)
        game_dir.mkdir(parents=True, exist_ok=True)
        if inst.get("auto_fabric_api", True):
            self.log("Checking Fabric API...")
            inst.setdefault("mods", {})
            try:
                install_project(mc, FABRIC_API_SLUG, game_dir / "mods", inst["mods"], self.log)
            except Exception as e:  # noqa: BLE001
                self.log(f"WARNING: could not update Fabric API: {e}")

        required = vanilla.get("javaVersion", {}).get("majorVersion", 8)
        java = self.ensure_java(required, inst.get("java", "").strip())
        self.log(f"Java: {java}")

        classpath = [str(p) for p in cp.values()] + [str(client_jar)]
        subs = {
            "auth_player_name": acct["username"],
            "version_name": fid,
            "game_directory": str(game_dir),
            "assets_root": str(ASSETS),
            "assets_index_name": vanilla["assets"],
            "auth_uuid": acct["uuid"],
            "auth_access_token": acct["access_token"],
            "clientid": "",
            "auth_xuid": "0",
            "user_type": "msa",
            "version_type": vanilla.get("type", "release"),
            "natives_directory": str(natives_dir),
            "launcher_name": APP_SLUG,
            "launcher_version": APP_VERSION,
            "classpath": os.pathsep.join(classpath),
            "library_directory": str(LIBS),
            "classpath_separator": os.pathsep,
        }

        def expand(args):
            out = []
            for a in args:
                if isinstance(a, str):
                    vals = [a]
                else:
                    if not rules_ok(a.get("rules")):
                        continue
                    v = a["value"]
                    vals = [v] if isinstance(v, str) else v
                for v in vals:
                    out.append(re.sub(r"\$\{(\w+)\}", lambda m: subs.get(m.group(1), m.group(0)), v))
            return out

        jvm = expand(vanilla["arguments"]["jvm"] + fabric.get("arguments", {}).get("jvm", []))
        game = expand(vanilla["arguments"]["game"] + fabric.get("arguments", {}).get("game", []))
        extra = shlex.split(inst.get("jvm_args", ""), posix=(os.name != "nt"))
        cmd = [java, f"-Xmx{int(float(inst.get('ram_gb', 4)) * 1024)}M", *extra, *jvm,
               fabric["mainClass"], *game]
        return cmd, game_dir


# --------------------------------------------------------------------------
# UI toolkit: theme, fonts and custom-drawn widgets (tkinter only, no extra packages)
# --------------------------------------------------------------------------
import atexit
import colorsys
import math
import tkinter.font as tkfont
from tkinter import filedialog

C = {
    "bg": "#0b100d", "side": "#080c09", "panel": "#101611", "card": "#151d17", "card2": "#1b261f",
    "line": "#243029", "line2": "#31423a", "text": "#ecf3ee", "muted": "#8f9f94", "dim": "#5f6f65",
    "accent": "#46e08a", "accent2": "#2cc7b5", "ink": "#04130a", "danger": "#ff6b7a", "warn": "#ffc15a",
}
SPECTRUM = ["#ff5d73", "#ffa94d", "#f6e05e", "#46e08a", "#38d5e8", "#5b8cff", "#a66bff"]


def hex_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def rgb_hex(c):
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(round(v)))) for v in c)


def mix(a, b, t):
    ca, cb = hex_rgb(a), hex_rgb(b)
    return rgb_hex([ca[i] + (cb[i] - ca[i]) * t for i in range(3)])


def spectrum_at(t):
    t = max(0.0, min(1.0, t)) * (len(SPECTRUM) - 1)
    i = min(int(t), len(SPECTRUM) - 2)
    return mix(SPECTRUM[i], SPECTRUM[i + 1], t - i)


_FONTS = {}


def _pick(cands, fallback):
    fams = set(tkfont.families())
    return next((f for f in cands if f in fams), fallback)


def font(size=10, weight="normal", mono=False):
    if "ui" not in _FONTS:
        _FONTS["ui"] = _pick(("Inter", "SF Pro Text", "Segoe UI Variable Text", "Segoe UI", "Helvetica Neue",
                              "Ubuntu", "Cantarell", "Noto Sans", "DejaVu Sans"), "TkDefaultFont")
        _FONTS["mono"] = _pick(("SF Mono", "Menlo", "Cascadia Mono", "Consolas", "JetBrains Mono",
                                "DejaVu Sans Mono", "Liberation Mono"), "Courier")
    k = 1.3 if OS == "osx" else 1.0
    return (_FONTS["mono" if mono else "ui"], int(round(size * k)), weight)


_MEASURE = {}


def text_width(text, f):
    if f not in _MEASURE:
        _MEASURE[f] = tkfont.Font(font=f)
    return _MEASURE[f].measure(text)


def fit_text(text, f, maxw):
    if text_width(text, f) <= maxw:
        return text
    while text and text_width(text + "…", f) > maxw:
        text = text[:-1]
    return text + "…"


def rrect(cv, x1, y1, x2, y2, r, **kw):
    r = max(0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2, x2 - r, y2,
           x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return cv.create_polygon(pts, smooth=True, **kw)


_IMGS = {}


def grad_image(master, w, h, c1, c2, radius=0, corners="all", vertical=False, cache=True):
    """A gradient PhotoImage with optionally rounded (transparent) corners."""
    w, h = int(w), int(h)
    key = (w, h, c1, c2, radius, corners, vertical)
    if cache and key in _IMGS:
        return _IMGS[key]
    img = tk.PhotoImage(master=master, width=w, height=h)
    if vertical:
        rows = ["{" + " ".join([mix(c1, c2, y / max(1, h - 1))] * w) + "}" for y in range(h)]
        img.put(" ".join(rows), to=(0, 0))
    else:
        row = "{" + " ".join(mix(c1, c2, x / max(1, w - 1)) for x in range(w)) + "}"
        img.put(" ".join([row] * h), to=(0, 0))
    if radius:
        r = int(radius)
        for dy in range(r):
            for dx in range(r):
                if (r - dx - 0.5) ** 2 + (r - dy - 0.5) ** 2 > r * r:
                    top, bottom = corners in ("all", "top"), corners in ("all", "bottom")
                    for (px, py, ok) in ((dx, dy, top), (w - 1 - dx, dy, top),
                                         (dx, h - 1 - dy, bottom), (w - 1 - dx, h - 1 - dy, bottom)):
                        if ok:
                            img.transparency_set(px, py, True)
    if cache:
        _IMGS[key] = img
    return img


def _bg_of(w):
    try:
        return w.cget("bg")
    except tk.TclError:
        return C["bg"]


def lbl(master, text="", size=10, weight="normal", color=None, mono=False, **kw):
    kw.setdefault("bg", _bg_of(master))
    return tk.Label(master, text=text, font=font(size, weight, mono), fg=color or C["text"], bd=0,
                    highlightthickness=0, **kw)


def entry(master, var, width=24, bg=None):
    f = tk.Frame(master, bg=C["line"], padx=1, pady=1)
    inner = tk.Frame(f, bg=bg or C["card2"])
    inner.pack(fill="x")
    inner.bind("<Button-1>", lambda _e: e.focus_set())
    e = tk.Entry(inner, textvariable=var, bg=bg or C["card2"], fg=C["text"], insertbackground=C["accent"],
                 relief="flat", bd=0, highlightthickness=0, font=font(10), width=width,
                 selectbackground=C["accent2"], selectforeground=C["ink"])
    e.pack(fill="x", padx=12, pady=9)
    e.bind("<FocusIn>", lambda _e: f.configure(bg=C["accent"]))
    e.bind("<FocusOut>", lambda _e: f.configure(bg=C["line"]))
    f.entry = e
    return f


def setup_style(root):
    s = ttk.Style(root)
    s.theme_use("clam")
    s.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
    s.configure("Treeview", background=C["card"], fieldbackground=C["card"], foreground=C["text"],
                rowheight=34, borderwidth=0, relief="flat", font=font(10))
    s.configure("Treeview.Heading", background=C["panel"], foreground=C["dim"], relief="flat",
                borderwidth=0, font=font(8, "bold"), padding=(8, 8))
    s.map("Treeview", background=[("selected", "#1d3a2a")], foreground=[("selected", C["text"])])
    s.map("Treeview.Heading", background=[("active", C["panel"])])
    s.layout("Vertical.TScrollbar", [("Vertical.Scrollbar.trough", {"sticky": "ns", "children": [
        ("Vertical.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})]})])
    for o in ("Vertical", "Horizontal"):
        s.configure(f"{o}.TScrollbar", background="#25322a", troughcolor=C["bg"], bordercolor=C["bg"],
                    arrowcolor=C["bg"], lightcolor="#25322a", darkcolor="#25322a", relief="flat",
                    gripcount=0, arrowsize=10)
        s.map(f"{o}.TScrollbar", background=[("active", "#35473c")])
    s.configure("TCombobox", fieldbackground=C["card2"], background=C["card2"], foreground=C["text"],
                arrowcolor=C["muted"], bordercolor=C["line"], lightcolor=C["line"], darkcolor=C["line"],
                padding=8, relief="flat")
    s.map("TCombobox", fieldbackground=[("readonly", C["card2"])], foreground=[("readonly", C["text"])],
          selectbackground=[("readonly", C["card2"])], selectforeground=[("readonly", C["text"])],
          bordercolor=[("focus", C["accent"])])
    root.option_add("*TCombobox*Listbox.background", C["card2"])
    root.option_add("*TCombobox*Listbox.foreground", C["text"])
    root.option_add("*TCombobox*Listbox.selectBackground", C["accent2"])
    root.option_add("*TCombobox*Listbox.selectForeground", C["ink"])
    root.option_add("*TCombobox*Listbox.font", font(10))
    root.option_add("*TCombobox*Listbox.borderWidth", 0)


# ---- icons / logo / avatar -------------------------------------------------
def draw_icon(cv, kind, cx, cy, size, color, tag="icon"):
    s = size / 2
    if kind == "grid":
        g = size * 0.1
        for dx in (-1, 1):
            for dy in (-1, 1):
                x, y = cx + dx * (s * 0.5), cy + dy * (s * 0.5)
                rrect(cv, x - s * 0.42, y - s * 0.42, x + s * 0.42, y + s * 0.42, 3, fill=color, outline="", tags=tag)
    elif kind == "user":
        cv.create_oval(cx - s * 0.38, cy - s * 0.85, cx + s * 0.38, cy - s * 0.09, outline=color, width=2, tags=tag)
        cv.create_arc(cx - s * 0.8, cy + s * 0.1, cx + s * 0.8, cy + s * 1.7, start=0, extent=180,
                      style="arc", outline=color, width=2, tags=tag)
    elif kind == "term":
        rrect(cv, cx - s * 0.9, cy - s * 0.75, cx + s * 0.9, cy + s * 0.75, 4, fill="", outline=color, width=2, tags=tag)
        cv.create_line(cx - s * 0.5, cy - s * 0.25, cx - s * 0.1, cy, cx - s * 0.5, cy + s * 0.25,
                       fill=color, width=2, tags=tag)
        cv.create_line(cx + s * 0.05, cy + s * 0.3, cx + s * 0.5, cy + s * 0.3, fill=color, width=2, tags=tag)
    elif kind == "info":
        cv.create_oval(cx - s * 0.85, cy - s * 0.85, cx + s * 0.85, cy + s * 0.85, outline=color, width=2, tags=tag)
        cv.create_line(cx, cy - s * 0.05, cx, cy + s * 0.42, fill=color, width=2, tags=tag)
        cv.create_oval(cx - 1.5, cy - s * 0.42 - 1.5, cx + 1.5, cy - s * 0.42 + 1.5, fill=color, outline=color, tags=tag)
    elif kind == "plus":
        cv.create_line(cx - s * 0.6, cy, cx + s * 0.6, cy, fill=color, width=2, capstyle="round", tags=tag)
        cv.create_line(cx, cy - s * 0.6, cx, cy + s * 0.6, fill=color, width=2, capstyle="round", tags=tag)
    elif kind == "skin":
        rrect(cv, cx - s * 0.45, cy - s * 0.9, cx + s * 0.45, cy - s * 0.1, 3, fill="", outline=color, width=2, tags=tag)
        rrect(cv, cx - s * 0.75, cy - s * 0.02, cx + s * 0.75, cy + s * 0.9, 3, fill="", outline=color, width=2, tags=tag)
    elif kind == "cursor":
        cv.create_polygon(cx - s * 0.55, cy - s * 0.8, cx - s * 0.55, cy + s * 0.7, cx - s * 0.15, cy + s * 0.35,
                          cx + s * 0.2, cy + s * 0.85, cx + s * 0.45, cy + s * 0.72, cx + s * 0.12, cy + s * 0.2,
                          cx + s * 0.7, cy + s * 0.2, fill="", outline=color, width=2, joinstyle="round", tags=tag)
    elif kind == "play":
        cv.create_polygon(cx - s * 0.32, cy - s * 0.5, cx - s * 0.32, cy + s * 0.5, cx + s * 0.55, cy,
                          fill=color, outline=color, joinstyle="round", tags=tag)


def draw_logo(cv, x, y, size, tag="logo"):
    """The Spectra prism mark, drawn from polygons."""
    k = size / 100.0
    A, B, Cc, G = (50, 8), (6, 88), (94, 88), (50, 62)

    def P(*pts):
        out = []
        for px, py in pts:
            out += [x + px * k, y + py * k]
        return out
    cv.create_polygon(P(A, B, G), fill="#4fe3c1", outline="", tags=tag)
    cv.create_polygon(P(A, Cc, G), fill="#7a7bff", outline="", tags=tag)
    cv.create_polygon(P(B, Cc, G), fill="#ff8fb0", outline="", tags=tag)
    w = max(1, int(size / 22))
    cv.create_polygon(P(A, B, Cc), fill="", outline="#f4fff8", width=w, joinstyle="round", tags=tag)
    for pt in (G,):
        for e in (A, B, Cc):
            cv.create_line(P(pt, e), fill="#f4fff8", width=max(1, w - 1), tags=tag)


def draw_avatar(cv, x, y, size, seed, tag="av"):
    """A small generated pixel-art face (not a real skin) so every account looks distinct."""
    h = hashlib.md5(seed.encode()).digest()
    skin = ("#f1c7a4", "#e0a67a", "#c98b62", "#8d5a3c", "#f6d9c0")[h[0] % 5]
    hair = ("#3b2417", "#1d1d1f", "#6b3f1d", "#caa14a", "#8a3d2f", "#3b4b8f")[h[1] % 6]
    eye = ("#3b6cff", "#2a2a2a", "#2f9e5a")[h[2] % 3]
    shirt = ("#2f9e8f", "#7a5cff", "#e0605b", "#3d8bff", "#e0a030")[h[3] % 5]
    mouth = mix(skin, "#000000", 0.35)
    grid = [[skin] * 8 for _ in range(8)]
    for c in range(8):
        grid[0][c] = hair
        grid[1][c] = hair if (c in (0, 7) or h[4] % 2) else skin
        grid[6][c] = shirt
        grid[7][c] = shirt
    grid[2][0] = grid[2][7] = hair
    grid[3][1] = grid[3][6] = "#ffffff"
    grid[3][2] = grid[3][5] = eye
    grid[5][3] = grid[5][4] = mouth
    p = size / 8.0
    for r in range(8):
        for c in range(8):
            cv.create_rectangle(x + c * p, y + r * p, x + (c + 1) * p, y + (r + 1) * p,
                                fill=grid[r][c], outline=grid[r][c], tags=tag)
    cv.create_rectangle(x, y, x + size, y + size, outline=C["line2"], tags=tag)


# ---- widgets -------------------------------------------------------------
class Btn(tk.Canvas):
    STYLES = {
        "primary": dict(c1="#46e08a", c2="#2cc7b5", fg="#04130a"),
        "secondary": dict(fill="#1c2820", bd="#2f4037", fg="#ecf3ee"),
        "ghost": dict(fill=None, bd=None, fg="#8f9f94"),
        "danger": dict(fill="#2a1519", bd="#51262d", fg="#ff7d8a"),
    }

    def __init__(self, master, text, command=None, style="secondary", w=None, h=38, size=10,
                 weight="bold", r=10, bg=None, icon=None):
        self.text, self.command, self.style, self.r, self.icon = text, command, style, r, icon
        self.fnt = font(size, weight)
        pad = 34 + (20 if icon else 0)
        self.bw = int(w or text_width(text, self.fnt) + pad)
        self.bh = int(h)
        super().__init__(master, width=self.bw, height=self.bh, bg=bg or _bg_of(master),
                         highlightthickness=0, bd=0, cursor="hand2")
        self.hover = self.down = False
        self.enabled = True
        self.bind("<Enter>", lambda _e: self._set(hover=True))
        self.bind("<Leave>", lambda _e: self._set(hover=False, down=False))
        self.bind("<ButtonPress-1>", lambda _e: self._set(down=True))
        self.bind("<ButtonRelease-1>", self._release)
        self.draw()

    def _set(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)
        self.draw()

    def _release(self, e):
        was = self.down
        self._set(down=False)
        if was and self.enabled and 0 <= e.x <= self.bw and 0 <= e.y <= self.bh and self.command:
            self.command()

    def configure_text(self, text):
        self.text = text
        self.draw()

    def set_enabled(self, on):
        self.enabled = on
        self.config(cursor="hand2" if on else "arrow")
        self.draw()

    def draw(self):
        self.delete("all")
        st = self.STYLES[self.style]
        w, h, r = self.bw, self.bh, self.r
        lift = 0.10 if (self.hover and self.enabled) else 0.0
        off = 1 if (self.down and self.enabled) else 0
        fg = st["fg"]
        if self.style == "primary":
            c1, c2 = st["c1"], st["c2"]
            if not self.enabled:
                c1, c2, fg = "#24332b", "#24332b", "#5f6f65"
            else:
                c1, c2 = mix(c1, "#ffffff", lift), mix(c2, "#ffffff", lift)
            self.create_image(0, off, anchor="nw", image=grad_image(self, w, h - 1, c1, c2, r))
        else:
            fill, bd = st["fill"], st["bd"]
            if self.style == "ghost":
                fill = C["card2"] if self.hover else None
                bd = None
            elif self.hover and self.enabled:
                fill, bd = mix(fill, "#ffffff", 0.07), mix(bd, "#ffffff", 0.15)
            if not self.enabled:
                fg = C["dim"]
            if fill:
                rrect(self, 1, 1 + off, w - 1, h - 1 + off, r, fill=fill, outline=bd or fill)
        cx = w / 2 + (10 if self.icon else 0)
        self.create_text(cx, h / 2 + off, text=self.text, fill=fg, font=self.fnt)
        if self.icon:
            tw = text_width(self.text, self.fnt)
            draw_icon(self, self.icon, cx - tw / 2 - 14, h / 2 + off, 14, fg)


class Switch(tk.Canvas):
    def __init__(self, master, var, command=None, bg=None):
        super().__init__(master, width=46, height=26, bg=bg or _bg_of(master), highlightthickness=0, bd=0,
                         cursor="hand2")
        self.var, self.command = var, command
        self.bind("<Button-1>", self._toggle)
        var.trace_add("write", lambda *_: self.draw())
        self.draw()

    def _toggle(self, _e):
        self.var.set(not self.var.get())
        if self.command:
            self.command()

    def draw(self):
        self.delete("all")
        on = bool(self.var.get())
        if on:
            self.create_image(1, 1, anchor="nw", image=grad_image(self, 44, 24, C["accent"], C["accent2"], 12))
        else:
            rrect(self, 1, 1, 45, 25, 12, fill="#26332b", outline="#34463b")
        x = 33 if on else 13
        self.create_oval(x - 9, 13 - 9, x + 9, 13 + 9, fill="#ffffff" if on else "#8f9f94", outline="")


class Slider(tk.Canvas):
    def __init__(self, master, var, lo, hi, step=0.5, width=320, bg=None):
        super().__init__(master, width=width, height=30, bg=bg or _bg_of(master), highlightthickness=0, bd=0,
                         cursor="hand2")
        self.var, self.lo, self.hi, self.step, self.sw = var, lo, hi, step, width
        self.bind("<Button-1>", self._drag)
        self.bind("<B1-Motion>", self._drag)
        var.trace_add("write", lambda *_: self.draw())
        self.bind("<Configure>", lambda e: (setattr(self, "sw", e.width), self.draw()))
        self.draw()

    def _drag(self, e):
        t = (e.x - 12) / max(1, self.sw - 24)
        v = self.lo + max(0.0, min(1.0, t)) * (self.hi - self.lo)
        self.var.set(round(round(v / self.step) * self.step, 2))

    def draw(self):
        self.delete("all")
        try:
            v = float(self.var.get())
        except (tk.TclError, ValueError):
            v = self.lo
        t = max(0.0, min(1.0, (v - self.lo) / (self.hi - self.lo)))
        x0, x1 = 12, self.sw - 12
        xv = x0 + t * (x1 - x0)
        rrect(self, x0 - 4, 11, x1 + 4, 19, 4, fill="#1d2a22", outline="#2b3b32")
        if xv > x0:
            self.create_image(x0 - 4, 11, anchor="nw",
                              image=grad_image(self, int(xv - x0 + 4), 8, C["accent2"], C["accent"], 4))
        self.create_oval(xv - 9, 15 - 9, xv + 9, 15 + 9, fill="#ffffff", outline=C["accent"], width=2)


class Meter(tk.Canvas):
    """Progress bar with a spectrum gradient; supports an indeterminate shimmer."""

    def __init__(self, master, height=10, bg=None):
        super().__init__(master, height=height, bg=bg or _bg_of(master), highlightthickness=0, bd=0)
        self.bh, self.frac, self.indet, self._job, self._phase = height, 0.0, False, None, 0.0
        self.bind("<Configure>", lambda _e: self.draw())

    def set(self, frac):
        self.frac, self.indet = max(0.0, min(1.0, frac)), False
        self.draw()

    def indeterminate(self, on=True):
        self.indet = on
        if on and not self._job:
            self._tick()
        self.draw()

    def _tick(self):
        if not self.indet:
            self._job = None
            return
        self._phase = (self._phase + 0.018) % 1.4
        self.draw()
        self._job = self.after(30, self._tick)

    def _fill(self, x0, x1, total):
        step = 4
        x = x0
        while x < x1:
            nx = min(x + step, x1)
            col = spectrum_at(x / max(1, total))
            self.create_rectangle(x, 1, nx + 1, self.bh - 1, fill=col, outline=col)
            x = nx

    def draw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.bh
        if w < 10:
            return
        rrect(self, 0, 0, w, h, h / 2, fill="#18221b", outline="#26352c")
        if self.indet:
            a = (self._phase - 0.4) * w
            x0, x1 = max(4, a), min(w - 4, a + 0.4 * w)
            if x1 > x0:
                self._fill(int(x0), int(x1), w)
        elif self.frac > 0:
            x1 = max(h, self.frac * w)
            self._fill(int(h / 2), int(x1 - h / 2), w)
            c = spectrum_at(0)
            self.create_oval(1, 1, h - 1, h - 1, fill=c, outline=c)
            c2 = spectrum_at(x1 / w)
            self.create_oval(x1 - h + 1, 1, x1 - 1, h - 1, fill=c2, outline=c2)


class Card(tk.Canvas):
    """A rounded panel. Put children in `.body`."""

    def __init__(self, master, height, fill=None, outline=None, radius=16, pad=18, bg=None):
        self.fill, self.outline, self.radius, self.pad = fill or C["card"], outline or C["line"], radius, pad
        super().__init__(master, height=height, bg=bg or _bg_of(master), highlightthickness=0, bd=0)
        self.body = tk.Frame(self, bg=self.fill)
        self._win = self.create_window(pad, pad, anchor="nw", window=self.body)
        self.bind("<Configure>", self._redraw)

    def _redraw(self, e):
        self.delete("bg")
        rrect(self, 1, 1, e.width - 2, e.height - 2, self.radius, fill=self.fill, outline=self.outline, tags="bg")
        self.tag_lower("bg")
        self.itemconfigure(self._win, width=max(1, e.width - 2 * self.pad), height=max(1, e.height - 2 * self.pad))


class NavItem(tk.Canvas):
    def __init__(self, master, text, icon, command):
        super().__init__(master, height=44, bg=C["side"], highlightthickness=0, bd=0, cursor="hand2")
        self.text, self.icon, self.command = text, icon, command
        self.active = self.hover = False
        self.bind("<Configure>", lambda _e: self.draw())
        self.bind("<Enter>", lambda _e: self._set(hover=True))
        self.bind("<Leave>", lambda _e: self._set(hover=False))
        self.bind("<Button-1>", lambda _e: self.command())

    def _set(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)
        self.draw()

    def draw(self):
        self.delete("all")
        w = self.winfo_width()
        if w < 20:
            return
        if self.active:
            rrect(self, 2, 2, w - 2, 42, 10, fill="#14261b", outline="#1f3a2a")
            rrect(self, 2, 12, 6, 32, 2, fill=C["accent"], outline=C["accent"])
        elif self.hover:
            rrect(self, 2, 2, w - 2, 42, 10, fill="#0f1611", outline="#0f1611")
        col = C["accent"] if self.active else (C["text"] if self.hover else C["muted"])
        draw_icon(self, self.icon, 28, 22, 18, col)
        self.create_text(50, 22, text=self.text, anchor="w", fill=C["text"] if self.active else col,
                         font=font(10, "bold" if self.active else "normal"))


class Dialog(tk.Toplevel):
    def __init__(self, app, title, w, h):
        super().__init__(app.root)
        self.app = app
        self.title(title)
        self.configure(bg=C["panel"], cursor=getattr(app, "cursor_tk", ""))
        r = app.root
        x = r.winfo_rootx() + max(0, (r.winfo_width() - w) // 2)
        y = r.winfo_rooty() + max(0, (r.winfo_height() - h) // 3)
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.transient(r)
        self.after(60, self._grab)

    def _grab(self):
        try:
            self.grab_set()
            self.focus_set()
        except tk.TclError:
            pass


def field_label(master, text):
    return lbl(master, text.upper(), 8, "bold", C["dim"])


def hint(master, text, wrap=380):
    return lbl(master, text, 9, color=C["muted"], wraplength=wrap, justify="left")


def pill(master, text, fg, fill, bd=None):
    f = font(8, "bold")
    w = text_width(text, f) + 22
    cv = tk.Canvas(master, width=w, height=24, bg=_bg_of(master), highlightthickness=0, bd=0)
    rrect(cv, 1, 1, w - 1, 23, 11, fill=fill, outline=bd or fill)
    cv.create_text(w / 2, 12, text=text, fill=fg, font=f)
    return cv


def switch_row(master, text, var, sub=None):
    row = tk.Frame(master, bg=_bg_of(master))
    left = tk.Frame(row, bg=_bg_of(master))
    left.pack(side="left", fill="x", expand=True)
    lbl(left, text, 10).pack(anchor="w")
    if sub:
        hint(left, sub, 330).pack(anchor="w")
    Switch(row, var).pack(side="right")
    return row


class Tabs(tk.Canvas):
    def __init__(self, master, names, command, bg=None):
        super().__init__(master, height=44, bg=bg or _bg_of(master), highlightthickness=0, bd=0, cursor="hand2")
        self.names, self.command, self.active, self.rects = names, command, 0, []
        self.bind("<Configure>", lambda _e: self.draw())
        self.bind("<Button-1>", self._click)

    def _click(self, e):
        for i, (x1, x2) in enumerate(self.rects):
            if x1 <= e.x <= x2 and i != self.active:
                self.active = i
                self.draw()
                self.command(i)

    def draw(self):
        self.delete("all")
        f = font(10, "bold")
        x, self.rects = 0, []
        for i, n in enumerate(self.names):
            w = text_width(n, f) + 36
            on = i == self.active
            self.create_text(x + w / 2, 20, text=n, fill=C["text"] if on else C["muted"], font=f)
            if on:
                self.create_rectangle(x + 10, 40, x + w - 10, 43, fill=C["accent"], outline=C["accent"])
            self.rects.append((x, x + w))
            x += w
        self.create_line(0, 43, self.winfo_width(), 43, fill=C["line"])
        self.tag_raise("all")


def tree_box(master, columns, heads, widths, stretch_col, height=8):
    box = tk.Frame(master, bg=C["line"], padx=1, pady=1)
    inner = tk.Frame(box, bg=C["card"])
    inner.pack(fill="both", expand=True)
    tv = ttk.Treeview(inner, columns=columns, show="headings", height=height, selectmode="extended")
    for c, t, w in zip(columns, heads, widths):
        tv.heading(c, text=t, anchor="w")
        tv.column(c, width=w, anchor="w", stretch=(c == stretch_col))
    sb = ttk.Scrollbar(inner, orient="vertical", command=tv.yview)
    tv.configure(yscrollcommand=sb.set)
    tv.pack(side="left", fill="both", expand=True)
    sb.pack(side="right", fill="y")
    return box, tv


# --------------------------------------------------------------------------
# Dialogs
# --------------------------------------------------------------------------
class AddInstanceDialog(Dialog):
    def __init__(self, app):
        super().__init__(app, "New instance", 500, 560)
        b = tk.Frame(self, bg=C["panel"])
        b.pack(fill="both", expand=True, padx=32, pady=28)
        lbl(b, "New instance", 20, "bold").pack(anchor="w")
        hint(b, "Pick a Minecraft version. Fabric Loader, Fabric API and a matching Java are set up for you "
                "the first time you play.", 430).pack(anchor="w", pady=(4, 20))
        field_label(b, "Name").pack(anchor="w", pady=(0, 6))
        self.name = tk.StringVar(value="New instance")
        e = entry(b, self.name)
        e.pack(fill="x")
        e.entry.focus_set()
        e.entry.select_range(0, "end")
        field_label(b, "Minecraft version").pack(anchor="w", pady=(18, 6))
        self.ver = tk.StringVar()
        self.box = ttk.Combobox(b, textvariable=self.ver, state="readonly", font=font(10))
        self.box.pack(fill="x")
        self.snap = tk.BooleanVar(value=False)
        self.api = tk.BooleanVar(value=True)
        sw = tk.Frame(b, bg=C["panel"])
        sw.pack(fill="x", pady=(22, 0))
        switch_row(sw, "Show snapshots", self.snap, "Include development snapshots in the list.").pack(fill="x", pady=6)
        self.snap.trace_add("write", lambda *_: self.refresh())
        switch_row(sw, "Install Fabric API", self.api, "Most Fabric mods need it. Kept up to date automatically.").pack(fill="x", pady=6)
        btns = tk.Frame(b, bg=C["panel"])
        btns.pack(side="bottom", fill="x")
        Btn(btns, "Create instance", self.create, "primary", h=44, size=10).pack(side="right")
        Btn(btns, "Cancel", self.destroy, "ghost", h=44).pack(side="right", padx=(0, 8))
        self.bind("<Return>", lambda _e: self.create())
        self.bind("<Escape>", lambda _e: self.destroy())
        self.refresh()

    def refresh(self):
        vs = [v for v, stable in self.app.game_versions if stable or self.snap.get()]
        self.box.configure(values=vs)
        if vs and self.ver.get() not in vs:
            self.ver.set(vs[0])

    def create(self):
        name = self.name.get().strip()
        if not name or not self.ver.get():
            messagebox.showwarning("New instance", "Enter a name and pick a version.", parent=self)
            return
        inst = {"id": new_instance_id(name), "name": name, "version": self.ver.get(),
                "ram_gb": 4, "java": "", "jvm_args": "", "auto_fabric_api": self.api.get(), "mods": {}}
        save_instance(inst)
        game_dir_of(inst).mkdir(parents=True, exist_ok=True)
        self.app.refresh_instances(select=inst["id"])
        self.app.toast(f"Created {name}")
        self.destroy()




class EditInstanceDialog(Dialog):
    def __init__(self, app, inst, tab=0):
        super().__init__(app, f"{inst['name']}", 1000, 680)
        self.inst = inst
        self.frames = []
        top = tk.Frame(self, bg=C["panel"])
        top.pack(fill="x", padx=32, pady=(26, 0))
        self.title_lbl = lbl(top, inst["name"], 20, "bold")
        self.title_lbl.pack(anchor="w")
        lbl(top, f"Minecraft {inst['version']}  ·  Fabric", 10, color=C["muted"]).pack(anchor="w", pady=(2, 10))
        self.tabs = Tabs(self, ["Settings", "Mods"], self.switch)
        self.tabs.pack(fill="x", padx=32)
        self.stage = tk.Frame(self, bg=C["panel"])
        self.stage.pack(fill="both", expand=True, padx=32, pady=(18, 24))
        self.frames = [self.build_settings(self.stage), self.build_mods(self.stage)]
        self.tabs.active = tab
        self.switch(tab)
        self.bind("<Escape>", lambda _e: self.destroy())

    def switch(self, i):
        for f in self.frames:
            f.pack_forget()
        self.frames[i].pack(fill="both", expand=True)

    # ---- settings tab
    def build_settings(self, parent):
        f = tk.Frame(parent, bg=C["panel"])
        i = self.inst
        self.v_name = tk.StringVar(value=i["name"])
        self.v_ram = tk.DoubleVar(value=float(i.get("ram_gb", 4)))
        self.v_java = tk.StringVar(value=i.get("java", ""))
        self.v_args = tk.StringVar(value=i.get("jvm_args", ""))
        self.v_api = tk.BooleanVar(value=i.get("auto_fabric_api", True))
        col = tk.Frame(f, bg=C["panel"])
        col.pack(anchor="nw", fill="x", ipadx=0)
        col.grid_columnconfigure(0, weight=1)
        field_label(col, "Name").grid(row=0, column=0, sticky="w", pady=(0, 6))
        entry(col, self.v_name).grid(row=1, column=0, sticky="ew")

        field_label(col, "Memory").grid(row=2, column=0, sticky="w", pady=(20, 4))
        mem = tk.Frame(col, bg=C["panel"])
        mem.grid(row=3, column=0, sticky="ew")
        self.mem_lbl = lbl(mem, "", 12, "bold", C["accent"], width=9, anchor="e")
        self.mem_lbl.pack(side="right")
        Slider(mem, self.v_ram, 1, 32, 0.5).pack(side="left", fill="x", expand=True)
        self.v_ram.trace_add("write", lambda *_: self.mem_lbl.config(text=f"{self._ram():g} GB"))
        self.mem_lbl.config(text=f"{self._ram():g} GB")

        field_label(col, "Java path (optional)").grid(row=4, column=0, sticky="w", pady=(18, 6))
        jr = tk.Frame(col, bg=C["panel"])
        jr.grid(row=5, column=0, sticky="ew")
        Btn(jr, "Browse", self.browse, "secondary", h=38).pack(side="right", padx=(8, 0))
        entry(jr, self.v_java).pack(side="left", fill="x", expand=True)
        hint(col, "Leave empty and Spectra downloads a matching Java for you.", 600).grid(row=6, column=0, sticky="w", pady=(6, 0))

        field_label(col, "Extra JVM arguments").grid(row=7, column=0, sticky="w", pady=(18, 6))
        entry(col, self.v_args).grid(row=8, column=0, sticky="ew")

        sw = switch_row(col, "Keep Fabric API installed and up to date", self.v_api)
        sw.grid(row=9, column=0, sticky="ew", pady=(22, 0))
        Btn(f, "Save changes", self.save, "primary", h=44).pack(side="bottom", anchor="e")
        return f

    def _ram(self):
        try:
            return float(self.v_ram.get())
        except (tk.TclError, ValueError):
            return 4.0

    def browse(self):
        p = filedialog.askopenfilename(parent=self, title="Select the java executable")
        if p:
            self.v_java.set(p)

    def save(self):
        self.inst.update(name=self.v_name.get().strip() or self.inst["name"], ram_gb=self._ram(),
                         java=self.v_java.get().strip(), jvm_args=self.v_args.get().strip(),
                         auto_fabric_api=self.v_api.get())
        save_instance(self.inst)
        self.app.refresh_instances(select=self.inst["id"])
        self.title_lbl.config(text=self.inst["name"])
        self.app.toast("Instance saved")

    # ---- mods tab
    @property
    def mods_dir(self):
        return game_dir_of(self.inst) / "mods"

    def build_mods(self, parent):
        f = tk.Frame(parent, bg=C["panel"])
        f.grid_columnconfigure(0, weight=1, uniform="c")
        f.grid_columnconfigure(1, weight=1, uniform="c")
        f.grid_rowconfigure(1, weight=1)

        # left: installed
        lh = tk.Frame(f, bg=C["panel"])
        lh.grid(row=0, column=0, sticky="ew", padx=(0, 12), pady=(0, 8))
        field_label(lh, "Installed").pack(side="left")
        self.count_lbl = lbl(lh, "", 9, color=C["dim"])
        self.count_lbl.pack(side="right")
        lb, self.inst_tree = tree_box(f, ("file", "state"), ("MOD FILE", "STATE"), (260, 70), "file")
        lb.grid(row=1, column=0, sticky="nsew", padx=(0, 12))
        self.inst_tree.tag_configure("off", foreground=C["dim"])
        bar = tk.Frame(f, bg=C["panel"])
        bar.grid(row=2, column=0, sticky="w", pady=(10, 0))
        Btn(bar, "Enable / disable", self.toggle, h=36).pack(side="left")
        Btn(bar, "Remove", self.remove, "danger", h=36).pack(side="left", padx=8)
        Btn(bar, "Folder", lambda: open_path(self.mods_dir), "ghost", h=36).pack(side="left")

        # right: modrinth
        rh = tk.Frame(f, bg=C["panel"])
        rh.grid(row=0, column=1, sticky="ew", padx=(12, 0), pady=(0, 8))
        field_label(rh, "Browse Modrinth").pack(side="left")
        rb, self.res = tree_box(f, ("title", "dl", "desc"), ("MOD", "DOWNLOADS", "DESCRIPTION"),
                                (150, 90, 220), "desc")
        rb.grid(row=1, column=1, sticky="nsew", padx=(12, 0))
        sbar = tk.Frame(f, bg=C["panel"])
        sbar.grid(row=2, column=1, sticky="ew", padx=(12, 0), pady=(10, 0))
        self.q = tk.StringVar()
        Btn(sbar, "Search", self.search, "secondary", h=38).pack(side="right", padx=(8, 0))
        e = entry(sbar, self.q)
        e.pack(side="left", fill="x", expand=True)
        e.entry.bind("<Return>", lambda _e: self.search())
        foot = tk.Frame(f, bg=C["panel"])
        foot.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(14, 0))
        self.msg = lbl(foot, f"Search mods that support Minecraft {self.inst['version']}.", 9, color=C["muted"])
        self.msg.pack(side="left")
        Btn(foot, "Install selected + dependencies", self.install, "primary", h=42).pack(side="right")
        self.reload_mods()
        return f

    def reload_mods(self):
        self.inst_tree.delete(*self.inst_tree.get_children())
        n = 0
        if self.mods_dir.exists():
            for p in sorted(self.mods_dir.iterdir()):
                if p.name.endswith(".jar"):
                    self.inst_tree.insert("", "end", iid=p.name, values=(p.name, "On"))
                    n += 1
                elif p.name.endswith(".jar.disabled"):
                    self.inst_tree.insert("", "end", iid=p.name, values=(p.name[:-9], "Off"), tags=("off",))
                    n += 1
        self.count_lbl.config(text=f"{n} file{'s' if n != 1 else ''}")

    def toggle(self):
        for iid in self.inst_tree.selection():
            p = self.mods_dir / iid
            p.rename(p.with_name(p.name[:-9] if iid.endswith(".disabled") else iid + ".disabled"))
        self.reload_mods()

    def remove(self):
        sel = self.inst_tree.selection()
        if sel and messagebox.askyesno("Remove", f"Delete {len(sel)} mod file(s)?", parent=self):
            for iid in sel:
                (self.mods_dir / iid).unlink(missing_ok=True)
            self.inst["mods"] = {k: v for k, v in self.inst.get("mods", {}).items()
                                 if (self.mods_dir / v).exists() or (self.mods_dir / (v + ".disabled")).exists()}
            save_instance(self.inst)
            self.reload_mods()

    def search(self):
        query = self.q.get().strip()
        if not query:
            return
        facets = json.dumps([["project_type:mod"], ["categories:fabric"], [f"versions:{self.inst['version']}"]])
        url = f"{MODRINTH}/search?" + urllib.parse.urlencode({"query": query, "facets": facets, "limit": 25})
        self.msg.config(text="Searching…")

        def done(data):
            if not self.winfo_exists():
                return
            self.res.delete(*self.res.get_children())
            for h in data.get("hits", []):
                self.res.insert("", "end", iid=h["project_id"],
                                values=(h["title"], f"{h['downloads']:,}", h["description"]))
            self.msg.config(text=f"{len(data.get('hits', []))} result(s) for Minecraft {self.inst['version']}.")

        self.app.bg(lambda: get_json(url), done,
                    lambda e: self.winfo_exists() and self.msg.config(text=f"Search failed: {e}"))

    def install(self):
        sel = self.res.selection()
        if not sel:
            self.msg.config(text="Select one or more mods from the results first.")
            return
        mc, installed = self.inst["version"], self.inst.setdefault("mods", {})
        self.msg.config(text="Installing…")

        def work():
            seen, logs = set(), []
            for pid in sel:
                install_project(mc, pid, self.mods_dir, installed, logs.append, seen)
            return logs

        def done(logs):
            save_instance(self.inst)
            if self.winfo_exists():
                self.reload_mods()
                self.msg.config(text=logs[-1] if logs else "Done.")
            for l in logs:
                self.app.log(l)
            self.app.refresh_instances()

        self.app.bg(work, done, lambda e: self.winfo_exists() and self.msg.config(text=f"Install failed: {e}"))


# --------------------------------------------------------------------------
# Instance grid (cards drawn on a canvas)
# --------------------------------------------------------------------------
def inst_colors(seed):
    h = int(hashlib.md5(seed.encode()).hexdigest()[:6], 16)
    hue = (h % 360) / 360.0
    a = colorsys.hsv_to_rgb(hue, 0.62, 0.86)
    b = colorsys.hsv_to_rgb((hue + 0.14) % 1.0, 0.78, 0.40)
    return rgb_hex([v * 255 for v in a]), rgb_hex([v * 255 for v in b])


class InstanceGrid(tk.Frame):
    CW, CH, GAP, PAD, BH = 256, 184, 20, 32, 92

    def __init__(self, master, app):
        super().__init__(master, bg=C["bg"])
        self.app = app
        self.cv = tk.Canvas(self, bg=C["bg"], highlightthickness=0, bd=0)
        self.sb = ttk.Scrollbar(self.cv, orient="vertical", command=self.cv.yview)
        self.cv.configure(yscrollcommand=self._sb_set)
        self.cv.pack(fill="both", expand=True)
        self.hit, self.hover, self._job = [], None, None
        self.cw, self._imgs, self._cache = self.CW, [], {}
        self.cv.bind("<Configure>", lambda _e: self.schedule())
        self.cv.bind("<Motion>", self._motion)
        self.cv.bind("<Button-1>", self._click)
        self.cv.bind("<Double-Button-1>", self._double)
        for seq in ("<Button-3>", "<Button-2>", "<Control-Button-1>"):
            self.cv.bind(seq, self._context)
        self.cv.bind("<Enter>", lambda _e: self._wheel(True))
        self.cv.bind("<Leave>", lambda _e: (self._set_hover(None), self._wheel(False)), add="+")

    # ---- scrolling
    def _sb_set(self, lo, hi):
        self.sb.set(lo, hi)
        if float(lo) <= 0.0 and float(hi) >= 1.0:
            self.sb.place_forget()
        else:
            self.sb.place(relx=1.0, rely=0, relheight=1.0, anchor="ne", width=10)

    def banner(self, w, h, c1, c2):
        key = (w, h, c1, c2)
        if key not in self._cache:
            self._cache[key] = grad_image(self.cv, w, h, c1, c2, 16, corners="top", cache=False)
        return self._cache[key]

    def _wheel(self, on):
        if on:
            self.cv.bind_all("<MouseWheel>", self._on_wheel)
            self.cv.bind_all("<Button-4>", lambda _e: self.cv.yview_scroll(-2, "units"))
            self.cv.bind_all("<Button-5>", lambda _e: self.cv.yview_scroll(2, "units"))
        else:
            for s in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                self.cv.unbind_all(s)

    def _on_wheel(self, e):
        d = -1 if e.delta > 0 else 1
        if OS == "windows":
            d = int(-e.delta / 120) or d
        self.cv.yview_scroll(d * 2, "units")

    # ---- drawing
    def schedule(self):
        if self._job:
            self.after_cancel(self._job)
        self._job = self.after(30, self.draw)

    def draw(self):
        self._job = None
        cv = self.cv
        cv.delete("all")
        if len(self._cache) > 150:
            self._cache.clear()
        self.hit = []
        w = max(cv.winfo_width(), 400)
        insts = self.app.instances
        if not insts:
            self._draw_empty(w)
            cv.configure(scrollregion=(0, 0, w, cv.winfo_height()))
            return
        cols = max(1, (w - 2 * self.PAD + self.GAP) // (self.CW + self.GAP))
        self.cw = min(340, (w - 2 * self.PAD - (cols - 1) * self.GAP) // cols)
        items = insts + [None]
        top = 14
        for n, inst in enumerate(items):
            r, c = divmod(n, cols)
            x, y = self.PAD + c * (self.cw + self.GAP), top + r * (self.CH + self.GAP)
            if inst is None:
                self._draw_new(x, y)
            else:
                self._draw_card(inst, x, y)
        rows = -(-len(items) // cols)
        cv.configure(scrollregion=(0, 0, w, max(top + rows * (self.CH + self.GAP) + self.PAD, cv.winfo_height())))

    def _draw_empty(self, w):
        cv = self.cv
        cx, cy = w / 2, max(180, cv.winfo_height() / 2 - 30)
        cv.create_oval(cx - 150, cy - 150, cx + 150, cy + 150, fill="#0e1510", outline="#121b14")
        draw_logo(cv, cx - 44, cy - 124, 88)
        cv.create_text(cx, cy - 12, text="Welcome to Spectra", fill=C["text"], font=font(20, "bold"))
        cv.create_text(cx, cy + 34, text="Create an instance and pick a Minecraft version.\n"
                       "Fabric, Fabric API and Java are set up automatically.",
                       fill=C["muted"], font=font(10), justify="center")
        b = Btn(cv, "New instance", self.app.add_instance, "primary", h=46, bg=C["bg"], icon="plus")
        cv.create_window(cx, cy + 100, window=b)

    def _draw_new(self, x, y):
        cv, w, h = self.cv, self.cw, self.CH
        hov = self.hover == ("new", None)
        rrect(cv, x, y, x + w, y + h, 18, fill="#0e1510" if not hov else "#122019",
              outline=C["accent"] if hov else C["line2"], dash=(5, 5), width=2)
        cx, cy = x + w / 2, y + h / 2 - 12
        cv.create_oval(cx - 24, cy - 24, cx + 24, cy + 24, fill=C["card2"], outline=C["accent"] if hov else C["line2"])
        draw_icon(cv, "plus", cx, cy, 22, C["accent"] if hov else C["muted"])
        cv.create_text(cx, cy + 46, text="New instance", fill=C["text"] if hov else C["muted"], font=font(10, "bold"))
        self.hit.append((x, y, x + w, y + h, "new", None))

    def _draw_card(self, inst, x, y):
        cv, w, h, bh = self.cv, self.cw, self.CH, self.BH
        iid = inst["id"]
        sel = iid == self.app.sel_id
        hov = self.hover and self.hover[1] == iid
        c1, c2 = inst_colors(inst["id"])
        rrect(cv, x + 2, y + 6, x + w + 2, y + h + 6, 18, fill="#070a08", outline="")
        rrect(cv, x, y, x + w, y + h, 18, fill=C["card2"] if hov else C["card"],
              outline=C["accent"] if sel else ("#3a4d42" if hov else C["line"]), width=2 if sel else 1)
        cv.create_image(x + 2, y + 2, anchor="nw", image=self.banner(w - 4, bh, c1, c2))
        # faceted decoration in the banner
        lite = mix(c1, "#ffffff", 0.16)
        cv.create_polygon(x + w - 150, y + bh + 1, x + w - 84, y + 14, x + w - 18, y + bh + 1,
                          fill=mix(c2, "#ffffff", 0.10), outline="")
        cv.create_polygon(x + w - 110, y + bh + 1, x + w - 84, y + 14, x + w - 52, y + bh + 1,
                          fill=lite, outline="")
        cv.create_text(x + 18, y + 22, text=inst["version"], anchor="w", fill="#ffffff", font=font(18, "bold"))
        fw = text_width("FABRIC", font(7, "bold")) + 16
        rrect(cv, x + 18, y + 46, x + 18 + fw, y + 64, 8, fill=mix(c2, "#000000", 0.35), outline="")
        cv.create_text(x + 18 + fw / 2, y + 55, text="FABRIC", fill="#e9fff3", font=font(7, "bold"))
        nm = fit_text(inst["name"], font(12, "bold"), w - 36 - 50)
        cv.create_text(x + 18, y + bh + 26, text=nm, anchor="w", fill=C["text"], font=font(12, "bold"))
        mods = len(inst.get("mods", {}))
        meta = f"{mods} mod{'s' if mods != 1 else ''}  ·  {inst.get('ram_gb', 4):g} GB"
        cv.create_text(x + 18, y + bh + 50, text=meta, anchor="w", fill=C["muted"], font=font(9))
        # hover actions
        if hov or sel:
            px, py = x + w - 38, y + bh + 4 + (h - bh) / 2 - 6
            busy = self.app.busy
            pc = C["dim"] if busy else (mix(C["accent"], "#ffffff", 0.2) if self.hover == ("play", iid) else C["accent"])
            cv.create_oval(px - 19, py - 19, px + 19, py + 19, fill=pc, outline="")
            draw_icon(cv, "play", px + 1, py, 20, C["ink"])
            self.hit.insert(0, (px - 19, py - 19, px + 19, py + 19, "play", iid))
            mx, my = x + w - 24, y + 24
            cv.create_oval(mx - 14, my - 14, mx + 14, my + 14,
                           fill=mix(c2, "#000000", 0.35 if self.hover != ("menu", iid) else 0.15), outline="")
            for dx in (-6, 0, 6):
                cv.create_oval(mx + dx - 1.8, my - 1.8, mx + dx + 1.8, my + 1.8, fill="#ffffff", outline="")
            self.hit.insert(0, (mx - 14, my - 14, mx + 14, my + 14, "menu", iid))
        self.hit.append((x, y, x + w, y + h, "card", iid))

    # ---- interaction
    def _at(self, e):
        x, y = self.cv.canvasx(e.x), self.cv.canvasy(e.y)
        for x1, y1, x2, y2, kind, iid in self.hit:
            if x1 <= x <= x2 and y1 <= y <= y2:
                return (kind, iid)
        return None

    def _motion(self, e):
        self._set_hover(self._at(e))

    def _set_hover(self, h):
        if h != self.hover:
            self.hover = h
            self.cv.config(cursor="hand2" if h else "")
            self.draw()

    def _click(self, e):
        h = self._at(e)
        if not h:
            return
        kind, iid = h
        if kind == "new":
            self.app.add_instance()
        elif kind == "play":
            self.app.select(iid)
            self.app.launch(iid)
        elif kind == "menu":
            self.app.select(iid)
            self.app.card_menu(e, iid)
        else:
            self.app.select(iid)

    def _double(self, e):
        h = self._at(e)
        if h and h[0] == "card":
            self.app.select(h[1])
            self.app.launch(h[1])

    def _context(self, e):
        h = self._at(e)
        if h and h[1]:
            self.app.select(h[1])
            self.app.card_menu(e, h[1])


# --------------------------------------------------------------------------
# Accounts page
# --------------------------------------------------------------------------
class AccountsPage(tk.Frame):
    def __init__(self, master, app):
        super().__init__(master, bg=C["bg"])
        self.app = app
        self.cancel = threading.Event()
        self.code = self.url = ""
        _, right, _ = app.header(self, "Accounts",
                                 "Sign in with the Microsoft account that owns Minecraft: Java Edition.")
        Btn(right, "Add Microsoft account", self.add_ms, "primary", h=42, icon="plus").pack(side="right")
        self.signin = Card(self, height=212, fill="#0f1a13", outline="#1f3a2a", pad=24)
        sb = self.signin.body
        lbl(sb, "SIGN IN WITH MICROSOFT", 8, "bold", C["accent"], bg="#0f1a13").pack(anchor="w")
        self.code_lbl = lbl(sb, "", 30, "bold", C["text"], mono=True, bg="#0f1a13")
        self.code_lbl.pack(anchor="w", pady=(8, 2))
        self.sub_lbl = lbl(sb, "", 10, color=C["muted"], bg="#0f1a13", wraplength=640, justify="left")
        self.sub_lbl.pack(anchor="w")
        row = tk.Frame(sb, bg="#0f1a13")
        row.pack(anchor="w", pady=(16, 0))
        Btn(row, "Copy code", self.copy, "secondary", h=36, bg="#0f1a13").pack(side="left")
        Btn(row, "Open sign-in page", self.reopen, "secondary", h=36, bg="#0f1a13").pack(side="left", padx=8)
        Btn(row, "Cancel", self.cancel_signin, "ghost", h=36, bg="#0f1a13").pack(side="left")
        self.listf = tk.Frame(self, bg=C["bg"])
        self.listf.pack(fill="x", padx=32, pady=(8, 0))
        self.reload()

    def reload(self):
        for w in self.listf.winfo_children():
            w.destroy()
        app = self.app
        if not app.accounts:
            c = Card(self.listf, height=120)
            c.pack(fill="x", pady=6)
            lbl(c.body, "No accounts yet", 13, "bold", bg=C["card"]).pack(anchor="w", pady=(8, 2))
            lbl(c.body, "Click “Add Microsoft account” to sign in. A Microsoft page opens and the code is copied to your clipboard.",
                10, color=C["muted"], bg=C["card"]).pack(anchor="w")
            return
        cur = app.current_account()
        for a in app.accounts:
            card = Card(self.listf, height=86)
            card.pack(fill="x", pady=6)
            b = card.body
            b.grid_columnconfigure(1, weight=1)
            b.grid_rowconfigure(0, weight=1)
            av = tk.Canvas(b, width=48, height=48, bg=C["card"], highlightthickness=0, bd=0)
            av.grid(row=0, column=0, padx=(0, 16), sticky="w")
            draw_avatar(av, 0, 0, 47, acct_key(a))
            mid = tk.Frame(b, bg=C["card"])
            mid.grid(row=0, column=1, sticky="w")
            lbl(mid, a["username"], 13, "bold", bg=C["card"]).pack(anchor="w")
            lbl(mid, "Microsoft account", 9,
                color=C["muted"], bg=C["card"]).pack(anchor="w")
            right = tk.Frame(b, bg=C["card"])
            right.grid(row=0, column=2, sticky="e")
            if cur and acct_key(a) == acct_key(cur):
                pill(right, "DEFAULT", C["ink"], C["accent"]).pack(side="left", padx=(0, 10))
            else:
                Btn(right, "Make default", lambda a=a: self.set_default(a), "secondary", h=34, bg=C["card"]).pack(
                    side="left", padx=(0, 8))
            Btn(right, "Remove", lambda a=a: self.remove(a), "danger", h=34, bg=C["card"]).pack(side="left")

    def set_default(self, a):
        self.app.cfg["account"] = acct_key(a)
        self.app.save_cfg()
        self.app.refresh_accounts()
        self.reload()

    def remove(self, a):
        if messagebox.askyesno("Remove account", f"Remove {a['username']}?"):
            self.app.accounts.remove(a)
            self.app.save_accounts()
            self.app.refresh_accounts()
            self.reload()


    # ---- Microsoft sign-in
    def show_signin(self, code, sub):
        self.code_lbl.config(text=code, fg=C["text"])
        self.sub_lbl.config(text=sub)
        self.signin.pack(fill="x", padx=32, pady=(4, 8), before=self.listf)

    def cancel_signin(self):
        self.cancel.set()
        self.signin.pack_forget()

    def copy(self):
        if self.code:
            self.clipboard_clear()
            self.clipboard_append(self.code)
            self.app.toast("Code copied")

    def reopen(self):
        if self.url:
            webbrowser.open(self.url)

    def add_ms(self):
        self.cancel.set()
        self.cancel = cancel = threading.Event()
        auth = MSAuth()
        self.code = self.url = ""
        self.show_signin("· · · · · ·", "Contacting Microsoft…")

        def got_code(dc):
            if cancel.is_set() or not self.winfo_exists():
                return
            url, code = dc["verification_uri"], dc["user_code"]
            self.code, self.url = code, url
            self.show_signin(code, f"A Microsoft page is opening at {url}. Paste or type this code there "
                                   "(it was copied to your clipboard), then sign in. Waiting for you to finish…")
            self.clipboard_clear()
            self.clipboard_append(code)
            webbrowser.open(url)
            self.app.bg(lambda: auth.minecraft_account(auth.poll_device(dc, cancel)),
                        self.signed_in, self.failed)

        self.app.bg(auth.start_device, got_code, self.failed)

    def signed_in(self, acct):
        self.app.add_account(acct)
        if self.winfo_exists():
            self.signin.pack_forget()
            self.reload()
        self.app.toast(f"Signed in as {acct['username']}")

    def failed(self, err):
        if self.cancel.is_set() or not self.winfo_exists():
            return
        self.code_lbl.config(text="Sign-in failed", fg=C["danger"])
        self.sub_lbl.config(text=str(err))


# --------------------------------------------------------------------------
# Cursor customisation
#   launcher only        - Tk cursor on Spectra's own windows (all systems)
#   launcher + Minecraft - also installs the "Cursors Extended" Fabric mod in your instances
#   entire system        - Windows only: swaps the Windows arrow cursor while Spectra is open
# --------------------------------------------------------------------------
CURSOR_MOD_SLUG = "minecraft-cursor"      # Modrinth: "Cursors Extended" (client-side, MIT)
ARROW_ART = (
    "k...............", "kk..............", "kwk.............", "kwwk............",
    "kwwwk...........", "kwwwwk..........", "kwwwwwk.........", "kwwwwwwk........",
    "kwwwwwwwk.......", "kwwwwwkkkk......", "kwwkwwk.........", "kwk.kwwk........",
    "kk..kwwk........", "k....kwwk.......", ".....kwwk.......", "......kk........",
)


def _dilate(shape, n=16):
    out = set()
    for (x, y) in shape:
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                p = (x + dx, y + dy)
                if 0 <= p[0] < n and 0 <= p[1] < n and p not in shape:
                    out.add(p)
    return out


def cursor_art(style):
    """Returns (grid 16x16 of colour-or-None, hotspot) for a built-in cursor style."""
    n = 16
    grid = [[None] * n for _ in range(n)]
    if style in ("default", "classic", "spectra"):
        for y, row in enumerate(ARROW_ART):
            for x, ch in enumerate(row):
                if ch == "k":
                    grid[y][x] = "#06140c" if style == "spectra" else "#000000"
                elif ch == "w":
                    grid[y][x] = mix(C["accent"], "#5b8cff", y / 15.0) if style == "spectra" else "#ffffff"
        return grid, (0, 0)
    shape = set()
    if style == "crosshair":
        for i in range(1, 15):
            if not 6 <= i <= 9:
                shape.add((i, 7))
                shape.add((7, i))
    elif style == "plus":
        for i in range(2, 14):
            for t in (7, 8):
                shape.add((i, t))
                shape.add((t, i))
    elif style in ("ring", "target"):
        for y in range(n):
            for x in range(n):
                d = math.hypot(x - 7.5, y - 7.5)
                if 4.2 <= d <= 5.6 or d <= 1.0:
                    shape.add((x, y))
    for (x, y) in _dilate(shape):
        grid[y][x] = "#000000"
    for (x, y) in shape:
        grid[y][x] = "#ffffff" if style != "ring" else C["accent"]
    return grid, (8, 8)


def make_cur(style):
    """Build a Windows .cur file (32x32, 32-bit colour) from the built-in art."""
    import struct
    grid, (hx, hy) = cursor_art(style)
    n, s = 16, 2
    w = h = n * s
    rows = []
    for y in range(h):
        row = bytearray()
        for x in range(w):
            c = grid[y // s][x // s]
            if c is None:
                row += b"\x00\x00\x00\x00"
            else:
                r, g, b = hex_rgb(c)
                row += bytes((b, g, r, 255))
        rows.append(bytes(row))
    pixels = b"".join(reversed(rows))                    # BMP is bottom-up
    mask = bytes(((w + 31) // 32) * 4 * h)
    header = struct.pack("<IiiHHIIiiII", 40, w, h * 2, 1, 32, 0, len(pixels) + len(mask), 0, 0, 0, 0)
    img = header + pixels + mask
    entry = struct.pack("<BBBBHHII", w, h, 0, 0, hx * s, hy * s, len(img), 22)
    return struct.pack("<HHH", 0, 2, 1) + entry + img


# (id, label, description, tk cursor name, art style) per system
if OS == "windows":
    CURSOR_STYLES = [("default", "System default", "", "default"), ("spectra", "Spectra", "", "spectra"),
                     ("classic", "Classic", "", "classic"), ("crosshair", "Crosshair", "", "crosshair"),
                     ("ring", "Ring", "", "ring"), ("plus", "Plus", "", "plus")]
elif OS == "osx":
    CURSOR_STYLES = [("default", "System default", "arrow", "default"), ("crosshair", "Crosshair", "crosshair", "crosshair"),
                     ("plus", "Plus", "plus", "plus")]
else:
    CURSOR_STYLES = [("default", "System default", "left_ptr", "default"), ("crosshair", "Crosshair", "crosshair", "crosshair"),
                     ("plus", "Plus", "plus", "plus"), ("target", "Target", "target", "target")]
CURSOR_SCOPES = [
    ("launcher", "Launcher only", "Changes the pointer inside Spectra's windows. Nothing else is touched."),
    ("minecraft", "Launcher + Minecraft", "Also adds the Cursors Extended mod to your instances so Minecraft gets "
                                          "custom pointers too. Pick its look in game."),
    ("system", "Entire system", "Windows only. Replaces your arrow pointer everywhere while Spectra is open and "
                                "puts it back when you close it."),
]


def win_cursor_api():
    import ctypes
    u = ctypes.windll.user32
    u.LoadImageW.restype = ctypes.c_void_p
    u.LoadImageW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
    u.SetSystemCursor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    u.SystemParametersInfoW.argtypes = [ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint]
    return u


def win_set_system_cursor(path):
    try:
        u = win_cursor_api()
        h = u.LoadImageW(None, str(path), 2, 0, 0, 0x10)           # IMAGE_CURSOR, LR_LOADFROMFILE
        return bool(h) and bool(u.SetSystemCursor(h, 32512))       # OCR_NORMAL (the arrow)
    except Exception:  # noqa: BLE001
        return False


def win_restore_cursors():
    try:
        win_cursor_api().SystemParametersInfoW(0x0057, 0, None, 0)  # SPI_SETCURSORS: reload the user's own
    except Exception:  # noqa: BLE001
        pass


def cursor_file(style):
    d = ROOT / "cursors"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{style}.cur"
    p.write_bytes(make_cur(style))
    return p


def tk_cursor_for(style, probe):
    """The value to give Tk's `cursor` option for this style ('' = default)."""
    if style == "default":
        return ""
    if OS == "windows":
        p = cursor_file(style)
        cands = [p.as_posix()]
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(520)
            if ctypes.windll.kernel32.GetShortPathNameW(str(p), buf, 520):
                cands.insert(0, buf.value.replace("\\", "/"))
        except Exception:  # noqa: BLE001
            pass
        for c in cands:
            for form in ("@" + c, "@{" + c + "}"):
                t = tk.Frame(probe)
                try:
                    t.config(cursor=form)
                    return form
                except tk.TclError:
                    continue
                finally:
                    t.destroy()
        return ""
    for sid, _label, name, _art in CURSOR_STYLES:
        if sid == style:
            return name
    return ""


def sync_cursor_mod(inst, wanted, log):
    """Install (or remove) the Cursors Extended mod in one instance."""
    mods_dir = game_dir_of(inst) / "mods"
    installed = inst.setdefault("mods", {})
    pid = inst.get("cursor_mod_pid")
    if wanted:
        if not pid:
            pid = get_json(f"{MODRINTH}/project/{CURSOR_MOD_SLUG}")["id"]
        before = installed.get(pid)
        install_project(inst["version"], pid, mods_dir, installed, log)
        if installed.get(pid):
            inst["cursor_mod_pid"] = pid
            if not before:
                log("Installed Cursors Extended. In game: Options > Controls > Mouse Settings > Cursor Settings.")
        else:
            log("The cursor mod is not available for this Minecraft version.")
    elif pid and installed.get(pid):
        fn = installed.pop(pid)
        for suffix in ("", ".disabled"):
            (mods_dir / (fn + suffix)).unlink(missing_ok=True)
        inst.pop("cursor_mod_pid", None)
        log("Removed the cursor mod (cursor scope is launcher only).")


class CursorPage(tk.Frame):
    PAD, GAP = 32, 14
    GW, GH = 128, 120

    def __init__(self, master, app):
        super().__init__(master, bg=C["bg"])
        self.app = app
        app.header(self, "Cursor", "Choose how your pointer looks, and where it applies.")
        self.cv = tk.Canvas(self, bg=C["bg"], highlightthickness=0, bd=0)
        self.cv.pack(fill="both", expand=True)
        self.hit, self.hover = [], None
        self.cv.bind("<Configure>", lambda _e: self.draw())
        self.cv.bind("<Motion>", self._motion)
        self.cv.bind("<Leave>", lambda _e: self._hover(None))
        self.cv.bind("<Button-1>", self._click)

    def scope_ok(self, sid):
        return sid != "system" or OS == "windows"

    def draw(self):
        cv, app = self.cv, self.app
        cv.delete("all")
        self.hit = []
        w = max(cv.winfo_width(), 600)
        P, G = self.PAD, self.GAP
        scope, style = app.cursor_scope(), app.cfg.get("cursor_style", "default")
        cv.create_text(P, 18, text="WHERE SHOULD IT APPLY?", anchor="w", fill=C["dim"], font=font(8, "bold"))
        cw = (w - 2 * P - 2 * G) // 3
        y = 36
        for i, (sid, title, desc) in enumerate(CURSOR_SCOPES):
            x = P + i * (cw + G)
            ok, sel = self.scope_ok(sid), sid == scope
            hov = ok and self.hover == ("scope", sid)
            rrect(cv, x, y, x + cw, y + 124, 16, fill="#12201a" if sel else (C["card2"] if hov else C["card"]),
                  outline=C["accent"] if sel else (C["line2"] if hov else C["line"]), width=2 if sel else 1)
            cv.create_oval(x + 18, y + 20, x + 38, y + 40, outline=C["accent"] if sel else C["line2"], width=2,
                           fill=C["accent"] if sel else "")
            if sel:
                cv.create_oval(x + 25, y + 27, x + 31, y + 33, fill=C["ink"], outline=C["ink"])
            cv.create_text(x + 50, y + 30, text=title, anchor="w", font=font(11, "bold"),
                           fill=C["text"] if ok else C["dim"])
            cv.create_text(x + 18, y + 58, text=desc, anchor="nw", width=cw - 36, font=font(9),
                           fill=C["muted"] if ok else C["dim"])
            if not ok:
                f = font(7, "bold")
                pw = text_width("WINDOWS ONLY", f) + 18
                rrect(cv, x + cw - pw - 14, y + 18, x + cw - 14, y + 38, 9, fill="#241d10", outline="#4a3a18")
                cv.create_text(x + cw - 14 - pw / 2, y + 28, text="WINDOWS ONLY", fill=C["warn"], font=f)
            else:
                self.hit.append((x, y, x + cw, y + 124, "scope", sid))
        y += 124 + 12
        if scope in ("minecraft", "system"):
            cv.create_text(P, y + 6, anchor="nw", width=w - 2 * P, font=font(9), fill=C["muted"],
                           text="Minecraft: Spectra adds the “Cursors Extended” mod (from Modrinth) to your instances the "
                                "next time you play. Choose its pointers in game under Options › Controls › "
                                "Mouse Settings › Cursor Settings.")
            y += 40
        y += 14
        cv.create_text(P, y, text="STYLE", anchor="w", fill=C["dim"], font=font(8, "bold"))
        y += 20
        cols = max(1, (w - 2 * P + G) // (self.GW + G))
        for n, (sid, label, _name, art) in enumerate(CURSOR_STYLES):
            r, c = divmod(n, cols)
            x, yy = P + c * (self.GW + G), y + r * (self.GH + G)
            sel, hov = sid == style, self.hover == ("style", sid)
            rrect(cv, x, yy, x + self.GW, yy + self.GH, 16, fill="#12201a" if sel else (C["card2"] if hov else C["card"]),
                  outline=C["accent"] if sel else (C["line2"] if hov else C["line"]), width=2 if sel else 1)
            grid, _hot = cursor_art(art)
            px, ox, oy = 4, x + self.GW / 2 - 32, yy + 18
            for gy, row in enumerate(grid):
                for gx, col in enumerate(row):
                    if col:
                        cv.create_rectangle(ox + gx * px, oy + gy * px, ox + (gx + 1) * px, oy + (gy + 1) * px,
                                            fill=col, outline=col)
            cv.create_text(x + self.GW / 2, yy + self.GH - 24, text=label, fill=C["text"] if sel else C["muted"],
                           font=font(10, "bold" if sel else "normal"))
            self.hit.append((x, yy, x + self.GW, yy + self.GH, "style", sid))
        rows = -(-len(CURSOR_STYLES) // cols)
        y += rows * (self.GH + G) + 4
        note = {"windows": "Pointers apply to the whole launcher right away. Move your mouse around to try it.",
                "osx": "On macOS the launcher can use your system's pointer shapes. Custom artwork pointers need "
                       "Windows (macOS doesn't let apps change the system pointer). In Minecraft, the mod above "
                       "gives you custom pointers on every system."}.get(
            OS, "Pointers apply to the whole launcher right away. Custom artwork pointers need Windows; "
                "the Minecraft mod works on every system.")
        cv.create_text(P, y + 6, text=note, anchor="nw", width=w - 2 * P, font=font(9), fill=C["dim"])

    def _at(self, e):
        for x1, y1, x2, y2, kind, ident in self.hit:
            if x1 <= e.x <= x2 and y1 <= e.y <= y2:
                return (kind, ident)
        return None

    def _motion(self, e):
        self._hover(self._at(e))

    def _hover(self, h):
        if h != self.hover:
            self.hover = h
            self.draw()

    def _click(self, e):
        h = self._at(e)
        if not h:
            return
        if h[0] == "scope":
            self.app.set_cursor(scope=h[1])
        else:
            self.app.set_cursor(style=h[1])
        self.draw()


# --------------------------------------------------------------------------
# Skins: PNG codec, skin model, 3D viewer
# --------------------------------------------------------------------------
import base64
import binascii
import struct
import zlib

TEMPLATE_B64 = "iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAYAAACqaXHeAAAC+ElEQVR4AexavYoUQRCu3UThLlLwFlZEUfEVLtfYQM0u8gnEn+gwMDDVdzBYzIwMFQzvAUwExR9c2BPTwzO5PWq4D5q6mqqZ673rnple+Kjuqa6vu76ug+6ZG5Pze//559LC/YfPlhYc+uRuVwBe4eaNy6SBjn7TjQlpOHJnbRoJkHUGkYsrAkQK2PnwUgGd38LIBBpVwM7X36QBc893F6QB/pzt+Pbi1dLC28VFsvDm5gWysP/tydJCanGqCtjcuEQasLirkzXSAP/atSukAf5z01ukAf6UthIg5QJSz91IgHtTIgYWy20G+l22jQTocoLe2hsJ8G5OxAAZtxnod9k2EqDLCXprrwTY2f1DGhD8Y7FHGuDf+/6LNMD/f/6FNMB/llbONf44eToK8fjvAwqxP3tBIWZ31kch1re3RyE+3d2iEB/+PaIQWy/HFEK+S5ALlH35bqJtvOSrKkA+xN0fz3HXR9+ziJcWceCTFn7PghfjwIN+G6sK0Iag62NVAXDuR3I456PvWcRLizjwSQu/Z8GLceBBv409dheQ5355zpfnenmPkPGyL/lmzw8oRFt+ySfjPTGqCsA9AINx7kcf53z0ca5Hvy4ePLAYX8cHXliMr+OHv44PfstWAlgD+u4rAvR9h738SgV4CvXdXyqg7zvs5VcqwFOo7/6qAvAuAMni7o8+7vro426Pfl08eGAxvo4PvLAYX8cPfx0f+z0cex8Q3vW5Hd71uX3++utRiPBdArc5xgJzhAi5tDZzhpDcIRe3JYcrgDeg7/7qT6DvSVr5FQEsdYbgKxUwhF22ciwVYKkzBF+pgCHsspVjqQBLnSH4SgUMYZetHHtXAVaymm/lAsR+v4+N15K0nq1cAJ4s9vt9bDyvoSlORYCmk+cw7lQEiP1+HxvfRthoAbz/D/C+38fGt0lWGxstAJPGfr+Pjec1nBQrEeCkk+cQVwTIYRdSrqFUQEr1c5i7VEAOu5ByDaUCUqqfw9wrqYDY7/cx8bEiHgIAAP//rCdZDQAAAAZJREFUAwCVozDeWe9Q4QAAAABJRU5ErkJggg=="
SKIN_API = "https://api.minecraftservices.com/minecraft/profile"


def png_decode(data):
    """Decode an 8-bit, non-interlaced PNG into (width, height, RGBA bytearray)."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("That file is not a PNG image.")
    pos, chunks, idat = 8, {}, []
    while pos + 8 <= len(data):
        ln, typ = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + ln]
        pos += 12 + ln
        if typ == b"IDAT":
            idat.append(body)
        else:
            chunks.setdefault(typ, body)
        if typ == b"IEND":
            break
    if b"IHDR" not in chunks:
        raise ValueError("Damaged PNG file.")
    w, h, depth, ctype, _comp, _flt, interlace = struct.unpack(">IIBBBBB", chunks[b"IHDR"])
    if depth != 8 or interlace:
        raise ValueError("Please re-save the PNG as a normal 8-bit, non-interlaced image.")
    ch = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(ctype)
    if not ch:
        raise ValueError("Unsupported PNG type.")
    raw = zlib.decompress(b"".join(idat))
    stride = w * ch
    out = bytearray(h * stride)
    prev = bytearray(stride)
    p = 0
    for y in range(h):
        ft = raw[p]
        line = bytearray(raw[p + 1:p + 1 + stride])
        p += 1 + stride
        if ft == 1:
            for i in range(ch, stride):
                line[i] = (line[i] + line[i - ch]) & 255
        elif ft == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 255
        elif ft == 3:
            for i in range(stride):
                a = line[i - ch] if i >= ch else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 255
        elif ft == 4:
            for i in range(stride):
                a = line[i - ch] if i >= ch else 0
                b = prev[i]
                c = prev[i - ch] if i >= ch else 0
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 255
        elif ft != 0:
            raise ValueError("Damaged PNG file.")
        out[y * stride:(y + 1) * stride] = line
        prev = line
    rgba = bytearray(w * h * 4)
    pal = chunks.get(b"PLTE", b"")
    trns = chunks.get(b"tRNS", b"")
    for i in range(w * h):
        o = i * ch
        if ctype == 6:
            px = out[o:o + 4]
        elif ctype == 2:
            px = bytes((out[o], out[o + 1], out[o + 2], 255))
        elif ctype == 0:
            px = bytes((out[o], out[o], out[o], 255))
        elif ctype == 4:
            px = bytes((out[o], out[o], out[o], out[o + 1]))
        else:
            k = out[o]
            px = bytes((pal[3 * k], pal[3 * k + 1], pal[3 * k + 2], trns[k] if k < len(trns) else 255))
        rgba[i * 4:i * 4 + 4] = px
    return w, h, rgba


def png_encode(w, h, rgba):
    raw = bytearray()
    for y in range(h):
        raw.append(0)
        raw += rgba[y * w * 4:(y + 1) * w * 4]

    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", binascii.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b""))


def blank_skin():
    return bytearray(64 * 64 * 4)


def _copy_flip(px, src, dst, w, h):
    sx, sy = src
    dx, dy = dst
    for y in range(h):
        for x in range(w):
            s = ((sy + y) * 64 + sx + (w - 1 - x)) * 4
            d = ((dy + y) * 64 + dx + x) * 4
            px[d:d + 4] = px[s:s + 4]


def skin_from_png(data):
    """PNG bytes -> 64x64 RGBA bytearray. Old 64x32 skins are converted to the modern layout."""
    w, h, rgba = png_decode(data)
    if (w, h) == (64, 64):
        return rgba
    if (w, h) == (64, 32):
        px = blank_skin()
        px[:len(rgba)] = rgba
        for (ox, oy), (nx, ny) in (((0, 16), (16, 48)), ((40, 16), (32, 48))):   # right limb -> left limb
            _copy_flip(px, (ox + 4, oy), (nx + 4, ny), 4, 4)           # top
            _copy_flip(px, (ox + 8, oy), (nx + 8, ny), 4, 4)           # bottom
            _copy_flip(px, (ox + 8, oy + 4), (nx, ny + 4), 4, 12)      # left -> right
            _copy_flip(px, (ox, oy + 4), (nx + 8, ny + 4), 4, 12)      # right -> left
            _copy_flip(px, (ox + 4, oy + 4), (nx + 4, ny + 4), 4, 12)  # front
            _copy_flip(px, (ox + 12, oy + 4), (nx + 12, ny + 4), 4, 12)  # back
        return px
    raise ValueError(f"Skins must be 64×64 (or old 64×32) pixels. This image is {w}×{h}.")


def template_skin():
    return skin_from_png(base64.b64decode(TEMPLATE_B64))


# ---- model geometry --------------------------------------------------------
def box_faces(u0, v0, w, h, d, pos, e, overlay):
    """The six faces of a Minecraft skin box: (origin, U vec, V vec, tex rect, normal, overlay)."""
    x0, y0, z0 = pos[0] - e, pos[1] - e, pos[2] - e
    W, H, D = w + 2 * e, h + 2 * e, d + 2 * e
    x1, y1, z1 = x0 + W, y0 + H, z0 + D
    return [
        ((x0, y1, z1), (W, 0, 0), (0, -H, 0), (u0 + d, v0 + d, w, h), (0, 0, 1), overlay),        # front
        ((x1, y1, z0), (-W, 0, 0), (0, -H, 0), (u0 + 2 * d + w, v0 + d, w, h), (0, 0, -1), overlay),  # back
        ((x0, y1, z0), (0, 0, D), (0, -H, 0), (u0, v0 + d, d, h), (-1, 0, 0), overlay),           # right side
        ((x1, y1, z1), (0, 0, -D), (0, -H, 0), (u0 + d + w, v0 + d, d, h), (1, 0, 0), overlay),   # left side
        ((x0, y1, z0), (W, 0, 0), (0, 0, D), (u0 + d, v0, w, d), (0, 1, 0), overlay),             # top
        ((x0, y0, z1), (W, 0, 0), (0, 0, -D), (u0 + d + w, v0, w, d), (0, -1, 0), overlay),       # bottom
    ]


def skin_parts(slim):
    aw = 3 if slim else 4
    spec = [  # name, (u,v) base, (u,v) overlay, size, position
        ("Head", (0, 0), (32, 0), (8, 8, 8), (-4, 24, -4), 0.5),
        ("Body", (16, 16), (16, 32), (8, 12, 4), (-4, 12, -2), 0.25),
        ("Right arm", (40, 16), (40, 32), (aw, 12, 4), (-4 - aw, 12, -2), 0.25),
        ("Left arm", (32, 48), (48, 48), (aw, 12, 4), (4, 12, -2), 0.25),
        ("Right leg", (0, 16), (0, 32), (4, 12, 4), (-4, 0, -2), 0.25),
        ("Left leg", (16, 48), (0, 48), (4, 12, 4), (0, 0, -2), 0.25),
    ]
    parts = []
    for name, uv, ouv, (w, h, d), pos, e in spec:
        base = box_faces(uv[0], uv[1], w, h, d, pos, 0, False)
        over = box_faces(ouv[0], ouv[1], w, h, d, pos, e, True)
        center = (pos[0] + w / 2.0, pos[1] + h / 2.0, pos[2] + d / 2.0)
        parts.append({"name": name, "base": base, "over": over, "center": center})
    # cape: a 10x16x1 slab behind the body; texture is 64x32 and its outer side is the "front" slot (1,1)
    cf = box_faces(0, 0, 10, 16, 1, (-5, 8, -3), 0, 2)
    cf[0] = cf[0][:3] + ((12, 1, 10, 16),) + cf[0][4:]   # inner side (faces the body)
    cf[1] = cf[1][:3] + ((1, 1, 10, 16),) + cf[1][4:]    # outer side (what you see from behind)
    parts.append({"name": "Cape", "cape": True, "base": cf, "over": [], "center": (0, 16, -2.5)})
    return parts


def cape_from_png(data):
    """Cape PNG -> 64x32 RGBA bytearray (HD capes are scaled down)."""
    w, h, rgba = png_decode(data)
    if w % 64 or h * 2 != w:
        raise ValueError(f"Unexpected cape size {w}x{h}.")
    k = w // 64
    if k == 1:
        return bytearray(rgba)
    out = bytearray(64 * 32 * 4)
    for y in range(32):
        for x in range(64):
            s = ((y * k) * w + x * k) * 4
            out[(y * 64 + x) * 4:(y * 64 + x) * 4 + 4] = rgba[s:s + 4]
    return out


FACE_LABELS = ("front", "back", "right", "left", "top", "bottom")


def net_rects(slim):
    """Texture rectangles for guides: (part, layer, label, x, y, w, h)."""
    out = []
    for p in skin_parts(slim):
        if p.get("cape"):
            continue
        for layer, faces in (("base", p["base"]), ("overlay", p["over"])):
            for lab, f in zip(FACE_LABELS, faces):
                out.append((p["name"], layer, lab) + tuple(f[3]))
    return out


_SHADES = {}


def shade_hex(rgb, f):
    q = max(0, min(40, int(f * 32)))
    k = (rgb, q)
    c = _SHADES.get(k)
    if c is None:
        c = "#%02x%02x%02x" % tuple(min(255, rgb[i] * q // 32) for i in range(3))
        _SHADES[k] = c
    return c


class SkinView(tk.Canvas):
    """A rotatable 3D player model drawn with textured quads (software rendering)."""

    LIGHT = (-0.35, 0.75, 0.55)

    def __init__(self, master, width=360, height=520, bg=None, on_paint=None):
        super().__init__(master, width=width, height=height, bg=bg or C["card"], highlightthickness=0, bd=0,
                         cursor="fleur")
        self.px = template_skin()
        self.cape_px = None
        self.slim, self.show_overlay = False, True
        self.yaw, self.pitch, self.zoom = -0.55, 0.28, 1.0
        self.auto, self.on_paint, self.paint_mode, self.paint_layer = False, on_paint, False, "base"
        self.parts, self._runs, self._ver, self._job, self._drag = None, {}, 0, None, None
        self._drawn = []
        self.set_slim(False)
        self.bind("<Configure>", lambda _e: self.redraw())
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<B1-Motion>", self._move)
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<Double-Button-1>", lambda _e: self.reset())
        self.bind("<MouseWheel>", lambda e: self._zoom(1.08 if e.delta > 0 else 1 / 1.08))
        self.bind("<Button-4>", lambda _e: self._zoom(1.08))
        self.bind("<Button-5>", lambda _e: self._zoom(1 / 1.08))
        self._tick()

    # ---- data
    def set_slim(self, slim):
        self.slim = bool(slim)
        self.parts = skin_parts(self.slim)
        self._runs.clear()
        self.redraw()

    def set_pixels(self, px, slim=None):
        self.px = px
        if slim is not None and bool(slim) != self.slim:
            self.set_slim(slim)
            return
        self.invalidate()

    def set_cape(self, px):
        """px: 64x32 RGBA bytes, or None for no cape."""
        self.cape_px = px
        self.invalidate()

    def invalidate(self, *_):
        self._runs.clear()
        self.redraw()

    def reset(self):
        self.yaw, self.pitch, self.zoom = -0.55, 0.28, 1.0
        self.redraw()

    # ---- interaction
    def _zoom(self, k):
        self.zoom = max(0.5, min(3.0, self.zoom * k))
        self.redraw()

    def _press(self, e):
        self._drag = (e.x, e.y, self.yaw, self.pitch)
        if self.paint_mode:
            self._paint_at(e, True)

    def _move(self, e):
        if not self._drag:
            return
        if self.paint_mode:
            self._paint_at(e, False)
            return
        x0, y0, yaw0, pitch0 = self._drag
        self.yaw = yaw0 + (e.x - x0) * 0.012
        self.pitch = max(-1.45, min(1.45, pitch0 + (e.y - y0) * 0.012))
        self.redraw()

    def _release(self, _e):
        self._drag = None
        if self.paint_mode and self.on_paint:
            self.on_paint(None, None, "end")

    def _tick(self):
        if self.auto and not self._drag and self.winfo_ismapped():
            self.yaw += 0.018
            self.redraw()
        self.after(40, self._tick)

    # ---- texture runs (horizontal spans of equal colour) per face
    def _face_runs(self, face):
        key = id(face)
        r = self._runs.get(key)
        if r is not None:
            return r
        tx, ty, tw, th = face[3]
        px, runs = (self.cape_px if face[5] == 2 else self.px), []
        for j in range(th):
            i = 0
            while i < tw:
                o = ((ty + j) * 64 + tx + i) * 4
                if px[o + 3] < 128:
                    i += 1
                    continue
                rgb = (px[o], px[o + 1], px[o + 2])
                k = i + 1
                while k < tw:
                    o2 = ((ty + j) * 64 + tx + k) * 4
                    if px[o2 + 3] < 128 or (px[o2], px[o2 + 1], px[o2 + 2]) != rgb:
                        break
                    k += 1
                runs.append((i, k, j, rgb))
                i = k
        self._runs[key] = runs
        return runs

    # ---- rendering
    def redraw(self):
        if self._job is None:
            self._job = self.after_idle(self.render)

    def render(self):
        self._job = None
        cv = self
        cv.delete("all")
        w, h = max(cv.winfo_width(), 100), max(cv.winfo_height(), 100)
        cy_, sy_ = math.cos(self.yaw), math.sin(self.yaw)
        cp, sp = math.cos(self.pitch), math.sin(self.pitch)
        scale = min(h / 40.0, w / 22.0) * self.zoom
        cam = 95.0
        cx, cyc = w / 2.0, h / 2.0 + 1.5 * scale

        def rot(x, y, z):
            y -= 16.0
            x1, z1 = x * cy_ + z * sy_, -x * sy_ + z * cy_
            y2, z2 = y * cp - z1 * sp, y * sp + z1 * cp
            return x1, y2, z2

        def proj(x, y, z):
            x1, y2, z2 = rot(x, y, z)
            k = cam / (cam - z2)
            return cx + x1 * k * scale, cyc - y2 * k * scale

        # ground shadow
        sx0, sy0 = proj(-9, 0, 0)
        sx1, _ = proj(9, 0, 0)
        cv.create_oval(sx0 - 6, sy0 - 4 - 8 * self.zoom, sx1 + 6, sy0 + 10 * self.zoom, fill=mix(C["card"], "#000000", 0.35),
                       outline="")
        lx, ly, lz = self.LIGHT
        ln = math.sqrt(lx * lx + ly * ly + lz * lz)
        order = sorted(self.parts, key=lambda p: rot(*p["center"])[2])
        self._drawn = []
        for part in order:
            if part.get("cape") and self.cape_px is None:
                continue
            groups = [part["base"]] + ([part["over"]] if self.show_overlay else [])
            for faces in groups:
                for face in faces:
                    O, U, V, (tx, ty, tw, th), n, ov = face
                    nx, ny, nz = rot(n[0], n[1] + 16.0, n[2])
                    if nz <= 0.0:
                        continue
                    f = 0.60 + 0.40 * max(0.0, (nx * lx + ny * ly + nz * lz) / ln)
                    p00 = proj(*O)
                    p10 = proj(O[0] + U[0], O[1] + U[1], O[2] + U[2])
                    p01 = proj(O[0] + V[0], O[1] + V[1], O[2] + V[2])
                    p11 = proj(O[0] + U[0] + V[0], O[1] + U[1] + V[1], O[2] + U[2] + V[2])
                    self._drawn.append((p00, p10, p01, p11, face))
                    dxu, dyu = p10[0] - p00[0], p10[1] - p00[1]
                    dxv, dyv = p01[0] - p00[0], p01[1] - p00[1]
                    cxx, cyy = p11[0] - p10[0] - p01[0] + p00[0], p11[1] - p10[1] - p01[1] + p00[1]

                    def pt(s, t):
                        return (p00[0] + s * dxu + t * dxv + s * t * cxx, p00[1] + s * dyu + t * dyv + s * t * cyy)
                    for (i0, i1, j, rgb) in self._face_runs(face):
                        s0, s1, t0, t1 = i0 / tw, i1 / tw, j / th, (j + 1) / th
                        a, b, c, d = pt(s0, t0), pt(s1, t0), pt(s1, t1), pt(s0, t1)
                        col = shade_hex(rgb, f)
                        cv.create_polygon(a[0], a[1], b[0], b[1], c[0], c[1], d[0], d[1], fill=col, outline=col)

    # ---- painting on the model
    def texel_at(self, x, y):
        """Find (tx, ty) under a screen point on the visible face of the chosen layer."""
        for p00, p10, p01, p11, face in reversed(self._drawn):
            if face[5] == 2:
                continue
            if (face[5] and self.paint_layer != "overlay") or (not face[5] and self.paint_layer != "base"):
                continue
            ux, uy = p10[0] - p00[0], p10[1] - p00[1]
            vx, vy = p01[0] - p00[0], p01[1] - p00[1]
            det = ux * vy - uy * vx
            if abs(det) < 1e-6:
                continue
            qx, qy = x - p00[0], y - p00[1]
            s = (qx * vy - qy * vx) / det
            t = (ux * qy - uy * qx) / det
            if 0 <= s < 1 and 0 <= t < 1:
                tx, ty, tw, th = face[3]
                return tx + int(s * tw), ty + int(t * th)
        return None

    def _paint_at(self, e, first):
        if not self.on_paint:
            return
        t = self.texel_at(e.x, e.y)
        if t:
            self.on_paint(t[0], t[1], "start" if first else "move")


# --------------------------------------------------------------------------
# Skin library + Mojang skin API
# --------------------------------------------------------------------------
SKINS_DIR = ROOT / "skins"
OVERLAY_NAMES = {"Head": "Hat", "Body": "Jacket", "Right arm": "Right sleeve", "Left arm": "Left sleeve",
                 "Right leg": "Right pants", "Left leg": "Left pants"}


def lib_load():
    return load_json(SKINS_DIR / "library.json", {"skins": []}).get("skins", [])


def lib_save(items):
    SKINS_DIR.mkdir(parents=True, exist_ok=True)
    save_json(SKINS_DIR / "library.json", {"skins": items})


def lib_add(name, slim, px, entry=None):
    items = lib_load()
    if entry and any(i["id"] == entry["id"] for i in items):
        e = next(i for i in items if i["id"] == entry["id"])
        e.update(name=name, slim=bool(slim))
    else:
        base = re.sub(r"[^\w]+", "-", name).strip("-").lower() or "skin"
        sid, n = base, 2
        while (SKINS_DIR / f"{sid}.png").exists():
            sid, n = f"{base}-{n}", n + 1
        e = {"id": sid, "name": name, "slim": bool(slim)}
        items.append(e)
    SKINS_DIR.mkdir(parents=True, exist_ok=True)
    (SKINS_DIR / f"{e['id']}.png").write_bytes(png_encode(64, 64, px))
    lib_save(items)
    return e


def lib_px(entry):
    return skin_from_png((SKINS_DIR / f"{entry['id']}.png").read_bytes())


def lib_remove(entry):
    (SKINS_DIR / f"{entry['id']}.png").unlink(missing_ok=True)
    lib_save([i for i in lib_load() if i["id"] != entry["id"]])


def skin_upload(token, png, variant):
    """Change the skin of the signed-in Minecraft profile (multipart upload)."""
    b = "----SpectraBoundary" + os.urandom(8).hex()
    body = (f'--{b}\r\nContent-Disposition: form-data; name="variant"\r\n\r\n{variant}\r\n'
            f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="skin.png"\r\n'
            f'Content-Type: image/png\r\n\r\n').encode() + png + f"\r\n--{b}--\r\n".encode()
    req = urllib.request.Request(SKIN_API + "/skins", data=body, method="POST", headers={
        "Authorization": f"Bearer {token}", "Content-Type": f"multipart/form-data; boundary={b}",
        "User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        msg = {400: "Mojang rejected the image (it must be a valid 64x64 skin PNG).",
               401: "Your sign-in expired. Remove and re-add your account.",
               403: "Mojang refused the change for this account.",
               429: "Too many skin changes. Wait a minute and try again."}.get(e.code, f"Mojang returned {e.code}.")
        raise IOError(f"{msg} {raw[:120] if e.code not in (400, 401, 403, 429) else ''}".strip())


def account_skin(token):
    """Download the skin currently on the account: (png bytes, slim?)."""
    status, prof = http_json(SKIN_API, headers={"Authorization": f"Bearer {token}"})
    if status != 200:
        raise IOError("Could not read your profile from Mojang.")
    sk = next((s for s in prof.get("skins", []) if s.get("state") == "ACTIVE"), None)
    if not sk:
        raise IOError("This account has no skin set.")
    return http_get(sk["url"].replace("http://", "https://")), sk.get("variant", "CLASSIC").upper() == "SLIM"


def account_capes(token):
    """The capes this account owns: [{id, alias, active, px}] (textures downloaded)."""
    status, prof = http_json(SKIN_API, headers={"Authorization": f"Bearer {token}"})
    if status != 200:
        raise IOError("Could not read your profile from Mojang.")
    out = []
    for c in prof.get("capes", []):
        try:
            px = cape_from_png(http_get(c["url"].replace("http://", "https://")))
        except Exception:  # noqa: BLE001
            continue
        out.append({"id": c["id"], "alias": c.get("alias") or "Cape", "active": c.get("state") == "ACTIVE", "px": px})
    return out


def cape_set(token, cape_id):
    """Equip a cape, or hide the cape when cape_id is None."""
    hdr = {"Authorization": f"Bearer {token}", "User-Agent": UA, "Accept": "application/json"}
    body = None
    if cape_id:
        body = json.dumps({"capeId": cape_id}).encode()
        hdr["Content-Type"] = "application/json"
    req = urllib.request.Request(SKIN_API + "/capes/active", data=body, method="PUT" if cape_id else "DELETE", headers=hdr)
    try:
        urllib.request.urlopen(req, timeout=30).read()
    except urllib.error.HTTPError as e:
        raise IOError({401: "Your sign-in expired. Remove and re-add your account.",
                       429: "Too many changes. Wait a minute and try again."}.get(e.code, f"Mojang returned {e.code}."))


# --------------------------------------------------------------------------
# Dialogs: skin info + skin maker
# --------------------------------------------------------------------------
class SkinInfoDialog(Dialog):
    def __init__(self, app, name, slim, done):
        super().__init__(app, "Add skin", 460, 360)
        self.done = done
        b = tk.Frame(self, bg=C["panel"])
        b.pack(fill="both", expand=True, padx=30, pady=26)
        lbl(b, "Add skin", 20, "bold").pack(anchor="w")
        hint(b, "Give it a name and choose the arm style it was made for.", 400).pack(anchor="w", pady=(4, 18))
        field_label(b, "Name").pack(anchor="w", pady=(0, 6))
        self.name = tk.StringVar(value=name)
        e = entry(b, self.name)
        e.pack(fill="x")
        e.entry.focus_set()
        field_label(b, "Arm style").pack(anchor="w", pady=(16, 6))
        self.slim = tk.BooleanVar(value=slim)
        row = tk.Frame(b, bg=C["panel"])
        row.pack(anchor="w")
        self.b1 = Btn(row, "Classic (4px arms)", lambda: self.pick(False), h=36)
        self.b2 = Btn(row, "Slim (3px arms)", lambda: self.pick(True), h=36)
        self.b1.pack(side="left")
        self.b2.pack(side="left", padx=8)
        self.pick(slim)
        btns = tk.Frame(b, bg=C["panel"])
        btns.pack(side="bottom", fill="x")
        Btn(btns, "Add & use", lambda: self.ok(True), "primary", h=42).pack(side="right")
        Btn(btns, "Just add", lambda: self.ok(False), "secondary", h=42).pack(side="right", padx=(0, 8))
        Btn(btns, "Cancel", self.destroy, "ghost", h=42).pack(side="left")

    def pick(self, slim):
        self.slim.set(slim)
        self.b1.style, self.b2.style = ("secondary", "primary") if slim else ("primary", "secondary")
        self.b1.draw()
        self.b2.draw()

    def ok(self, apply):
        self.done(self.name.get().strip() or "My skin", self.slim.get(), apply)
        self.destroy()


class SkinMaker(Dialog):
    Z = 8   # 2D zoom (pixels per texel)
    PALETTE = ["#000000", "#3a3a3a", "#7a7a7a", "#bdbdbd", "#ffffff", "#7b4a2a", "#c98b62", "#f1c7a4",
               "#ff5d73", "#ff8a3d", "#ffd23d", "#46e08a", "#2cc7b5", "#38a8ff", "#5b6cff", "#a66bff",
               "#e05cc0", "#8a1f2d", "#1f6b3a", "#1f3a8a"]

    def __init__(self, app, px=None, slim=False, name="My skin", entry=None):
        super().__init__(app, "Skin maker", 1300, 840)
        self.px = bytearray(px) if px else template_skin()
        self.slim, self.name, self.entry = bool(slim), tk.StringVar(value=name), entry
        self.tool, self.size, self.color = "pencil", 1, "#46e08a"
        self.undo, self.redo, self._last, self._stroke = [], [], None, False
        self.show_grid, self.show_guides = tk.BooleanVar(value=True), tk.BooleanVar(value=True)
        self.v_over, self.v_auto, self.v_paint3d = tk.BooleanVar(value=True), tk.BooleanVar(value=False), tk.BooleanVar(value=False)
        self.layer = "base"
        self.build()
        self.refresh_all()
        self.bind("<Escape>", lambda _e: self.close())
        self.protocol("WM_DELETE_WINDOW", self.close)
        for seq, fn in (("<Control-z>", self.do_undo), ("<Command-z>", self.do_undo), ("<Control-y>", self.do_redo),
                        ("<Control-Shift-Z>", self.do_redo), ("<Command-Shift-Z>", self.do_redo)):
            self.bind(seq, lambda _e, f=fn: f())
        for key, tool in (("b", "pencil"), ("e", "eraser"), ("g", "fill"), ("i", "picker")):
            self.bind(key, lambda _e, t=tool: self.set_tool(t))

    def close(self):
        self.view.auto = False
        self.destroy()

    # ---- layout
    def build(self):
        root = tk.Frame(self, bg=C["panel"])
        root.pack(fill="both", expand=True, padx=24, pady=20)
        root.grid_columnconfigure(1, weight=1)
        root.grid_rowconfigure(0, weight=1)

        # left: tools
        left = tk.Frame(root, bg=C["panel"], width=250)
        left.grid(row=0, column=0, sticky="ns", padx=(0, 22))
        left.pack_propagate(False)
        lbl(left, "Skin maker", 20, "bold").pack(anchor="w")
        hint(left, "Paint on the flat skin or directly on the 3D model.", 240).pack(anchor="w", pady=(2, 14))
        field_label(left, "Name").pack(anchor="w", pady=(0, 5))
        entry(left, self.name, width=18).pack(fill="x")
        field_label(left, "Tool").pack(anchor="w", pady=(16, 6))
        tools = tk.Frame(left, bg=C["panel"])
        tools.pack(anchor="w")
        self.tool_btns = {}
        for i, (t, label) in enumerate((("pencil", "Pencil"), ("eraser", "Eraser"), ("fill", "Fill"), ("picker", "Picker"))):
            b = Btn(tools, label, lambda t=t: self.set_tool(t), "secondary", w=56, h=34, size=8)
            b.grid(row=0, column=i, padx=(0, 4))
            self.tool_btns[t] = b
        field_label(left, "Brush size").pack(anchor="w", pady=(14, 6))
        sizes = tk.Frame(left, bg=C["panel"])
        sizes.pack(anchor="w")
        self.size_btns = {}
        for i, s in enumerate((1, 2, 3, 4)):
            b = Btn(sizes, f"{s}", lambda s=s: self.set_size(s), "secondary", w=42, h=32)
            b.grid(row=0, column=i, padx=(0, 4))
            self.size_btns[s] = b
        field_label(left, "Colour").pack(anchor="w", pady=(14, 6))
        cr = tk.Frame(left, bg=C["panel"])
        cr.pack(fill="x")
        self.swatch = tk.Canvas(cr, width=44, height=44, bg=C["panel"], highlightthickness=0, bd=0, cursor="hand2")
        self.swatch.pack(side="left")
        self.swatch.bind("<Button-1>", lambda _e: self.choose_color())
        self.hex = tk.StringVar(value=self.color)
        he = entry(cr, self.hex, width=9)
        he.pack(side="left", padx=8)
        he.entry.bind("<Return>", lambda _e: self.set_color(self.hex.get()))
        Btn(cr, "Pick…", self.choose_color, "secondary", h=36, w=58).pack(side="left")
        pal = tk.Canvas(left, width=240, height=70, bg=C["panel"], highlightthickness=0, bd=0)
        pal.pack(anchor="w", pady=(10, 0))
        for i, c in enumerate(self.PALETTE):
            x, y = (i % 10) * 24, (i // 10) * 28
            pal.create_rectangle(x + 1, y + 1, x + 22, y + 24, fill=c, outline=C["line2"], tags=("sw",))
        pal.bind("<Button-1>", lambda e: self._pal(e))
        field_label(left, "Edit").pack(anchor="w", pady=(14, 6))
        er = tk.Frame(left, bg=C["panel"])
        er.pack(anchor="w")
        Btn(er, "Undo", self.do_undo, h=34, w=70, size=9).pack(side="left")
        Btn(er, "Redo", self.do_redo, h=34, w=70, size=9).pack(side="left", padx=6)
        Btn(er, "Clear", self.do_clear, "danger", h=34, w=62, size=9).pack(side="left")
        field_label(left, "File").pack(anchor="w", pady=(14, 6))
        fr = tk.Frame(left, bg=C["panel"])
        fr.pack(anchor="w")
        Btn(fr, "Template", self.do_template, h=34, w=76, size=9).pack(side="left")
        Btn(fr, "Open…", self.do_open, h=34, w=68, size=9).pack(side="left", padx=6)
        Btn(fr, "Save…", self.do_save, h=34, w=68, size=9).pack(side="left")
        bottom = tk.Frame(left, bg=C["panel"])
        bottom.pack(side="bottom", fill="x")
        Btn(bottom, "Apply to my account", self.do_apply, "secondary", h=40, w=240).pack(pady=(0, 8))
        Btn(bottom, "Save to my skins", self.do_library, "primary", h=44, w=240).pack()
        self.set_tool("pencil")
        self.set_size(1)
        self.set_color(self.color)

        # middle: 2D editor
        mid = tk.Frame(root, bg=C["panel"])
        mid.grid(row=0, column=1, sticky="n")
        top = tk.Frame(mid, bg=C["panel"])
        top.pack(fill="x", pady=(0, 8))
        lbl(top, "SKIN TEXTURE  64 × 64", 8, "bold", C["dim"]).pack(side="left")
        for var, text in ((self.show_guides, "Guides"), (self.show_grid, "Grid")):
            r = tk.Frame(top, bg=C["panel"])
            r.pack(side="right", padx=(14, 0))
            lbl(r, text, 9, color=C["muted"]).pack(side="left", padx=(0, 6))
            Switch(r, var, command=self.draw_overlays).pack(side="left")
        n = 64 * self.Z
        frame = tk.Frame(mid, bg=C["line"], padx=1, pady=1)
        frame.pack()
        self.cv = tk.Canvas(frame, width=n, height=n, bg="#1a2420", highlightthickness=0, bd=0, cursor="crosshair")
        self.cv.pack()
        self.disp = tk.PhotoImage(master=self, width=64, height=64)
        self.zoomed = self.disp.zoom(self.Z)
        self.img_item = self.cv.create_image(0, 0, anchor="nw", image=self.zoomed)
        self.cv.bind("<ButtonPress-1>", self._down)
        self.cv.bind("<B1-Motion>", self._drag)
        self.cv.bind("<ButtonRelease-1>", self._up)
        self.cv.bind("<Motion>", self._hover)
        self.coord = lbl(mid, "Click or drag to paint. Pencil B · Eraser E · Fill G · Picker I · Undo Ctrl/Cmd+Z", 9,
                         color=C["dim"], wraplength=n)
        self.coord.pack(anchor="w", pady=(8, 0))

        # right: 3D
        right = tk.Frame(root, bg=C["panel"], width=440)
        right.grid(row=0, column=2, sticky="ns", padx=(22, 0))
        right.pack_propagate(False)
        head = tk.Frame(right, bg=C["panel"])
        head.pack(fill="x", pady=(0, 8))
        lbl(head, "3D PREVIEW  ·  drag to rotate", 8, "bold", C["dim"]).pack(side="left")
        Btn(head, "Reset view", lambda: self.view.reset(), "ghost", h=28, size=8, w=80).pack(side="right")
        self.view = SkinView(right, width=440, height=520, bg="#12181a", on_paint=self.model_paint)
        self.view.pack()
        self.view.set_pixels(self.px, self.slim)
        ctl = tk.Frame(right, bg=C["panel"])
        ctl.pack(fill="x", pady=(10, 0))
        row = tk.Frame(ctl, bg=C["panel"])
        row.pack(fill="x")
        self.b_classic = Btn(row, "Classic arms", lambda: self.set_slim(False), h=32, size=9)
        self.b_slim = Btn(row, "Slim arms", lambda: self.set_slim(True), h=32, size=9)
        self.b_classic.pack(side="left")
        self.b_slim.pack(side="left", padx=6)
        self.set_slim(self.slim)
        for var, text, cmd in ((self.v_over, "Show outer layer", self.sync_view), (self.v_auto, "Auto-rotate", self.sync_view),
                               (self.v_paint3d, "Paint on the model", self.sync_view)):
            r = tk.Frame(ctl, bg=C["panel"])
            r.pack(fill="x", pady=(8, 0))
            lbl(r, text, 10, color=C["text"]).pack(side="left")
            Switch(r, var, command=cmd).pack(side="right")
        lr = tk.Frame(ctl, bg=C["panel"])
        lr.pack(fill="x", pady=(8, 0))
        lbl(lr, "Model paints on layer", 9, color=C["muted"]).pack(side="left")
        self.l_over = Btn(lr, "Outer", lambda: self.set_layer("overlay"), h=28, w=60, size=8)
        self.l_base = Btn(lr, "Base", lambda: self.set_layer("base"), h=28, w=60, size=8)
        self.l_over.pack(side="right")
        self.l_base.pack(side="right", padx=6)
        self.set_layer("base")

    # ---- state helpers
    def set_tool(self, t):
        self.tool = t
        for k, b in self.tool_btns.items():
            b.style = "primary" if k == t else "secondary"
            b.draw()

    def set_size(self, s):
        self.size = s
        for k, b in self.size_btns.items():
            b.style = "primary" if k == s else "secondary"
            b.draw()

    def set_color(self, c):
        try:
            hex_rgb(c)
            if len(c) != 7:
                raise ValueError
        except Exception:  # noqa: BLE001
            self.hex.set(self.color)
            return
        self.color = c.lower()
        self.hex.set(self.color)
        sw = self.swatch
        sw.delete("all")
        rrect(sw, 2, 2, 42, 42, 10, fill=self.color, outline=C["line2"], width=2)

    def choose_color(self):
        from tkinter import colorchooser
        rgb, hx = colorchooser.askcolor(color=self.color, parent=self, title="Choose a colour")
        if hx:
            self.set_color(hx)

    def _pal(self, e):
        i = (e.y // 28) * 10 + e.x // 24
        if 0 <= i < len(self.PALETTE) and e.x % 24 < 23:
            self.set_color(self.PALETTE[i])

    def set_slim(self, slim):
        self.slim = bool(slim)
        self.b_classic.style, self.b_slim.style = ("secondary", "primary") if self.slim else ("primary", "secondary")
        self.b_classic.draw()
        self.b_slim.draw()
        if hasattr(self, "view"):
            self.view.set_slim(self.slim)
            self.draw_overlays()

    def set_layer(self, layer):
        self.layer = layer
        self.l_base.style, self.l_over.style = ("primary", "secondary") if layer == "base" else ("secondary", "primary")
        self.l_base.draw()
        self.l_over.draw()
        if hasattr(self, "view"):
            self.view.paint_layer = layer

    def sync_view(self):
        v = self.view
        v.show_overlay, v.auto, v.paint_mode = self.v_over.get(), self.v_auto.get(), self.v_paint3d.get()
        v.config(cursor="crosshair" if v.paint_mode else "fleur")
        v.redraw()

    # ---- drawing the 2D editor
    def texel_color(self, x, y):
        o = (y * 64 + x) * 4
        p = self.px
        if p[o + 3] >= 128:
            return "#%02x%02x%02x" % (p[o], p[o + 1], p[o + 2])
        return "#2f3a35" if (x + y) % 2 else "#27312d"

    def refresh_all(self):
        rows = ["{" + " ".join(self.texel_color(x, y) for x in range(64)) + "}" for y in range(64)]
        self.disp.put(" ".join(rows), to=(0, 0))
        self.zoomed = self.disp.zoom(self.Z)
        self.cv.itemconfigure(self.img_item, image=self.zoomed)
        self.draw_overlays()
        self.view.set_pixels(self.px, self.slim)

    def draw_overlays(self):
        cv, Z = self.cv, self.Z
        cv.delete("ov")
        if self.show_guides.get():
            for part, layer, lab, x, y, w, h in net_rects(self.slim):
                col = "#46e08a" if layer == "base" else "#ffa94d"
                cv.create_rectangle(x * Z, y * Z, (x + w) * Z, (y + h) * Z, outline=col, tags="ov")
            for part, layer, lab, x, y, w, h in net_rects(self.slim):
                if lab == "front":
                    nm = part if layer == "base" else OVERLAY_NAMES[part]
                    cv.create_text(x * Z + 3, y * Z + 2, text=nm, anchor="nw", tags="ov", font=font(7, "bold"),
                                   fill="#46e08a" if layer == "base" else "#ffa94d")
        if self.show_grid.get():
            for i in range(0, 65):
                col = "#3b4a43" if i % 8 == 0 else "#27342e"
                cv.create_line(i * Z, 0, i * Z, 64 * Z, fill=col, tags="ov")
                cv.create_line(0, i * Z, 64 * Z, i * Z, fill=col, tags="ov")

    # ---- painting
    def _tex(self, e):
        return max(0, min(63, e.x // self.Z)), max(0, min(63, e.y // self.Z))

    def _hover(self, e):
        x, y = self._tex(e)
        o = (y * 64 + x) * 4
        a = self.px[o + 3]
        self.coord.config(text=f"x {x}  y {y}   " + ("transparent" if a < 128 else "#%02x%02x%02x" % tuple(self.px[o:o + 3])))

    def snapshot(self):
        self.undo.append(bytes(self.px))
        if len(self.undo) > 80:
            self.undo.pop(0)
        self.redo.clear()

    def _down(self, e):
        self._stroke = True
        self.snapshot()
        x, y = self._tex(e)
        self.apply(x, y, first=True)

    def _drag(self, e):
        if self._stroke:
            x, y = self._tex(e)
            self.apply(x, y, first=False)

    def _up(self, _e):
        self._stroke, self._last = False, None
        self.view.set_pixels(self.px, self.slim)

    def model_paint(self, x, y, phase):
        if phase == "end":
            self._stroke, self._last = False, None
            return
        if phase == "start":
            self.snapshot()
            self._stroke = True
        self.apply(x, y, first=(phase == "start"))

    def apply(self, x, y, first):
        tool = self.tool
        if tool == "picker":
            o = (y * 64 + x) * 4
            if self.px[o + 3] >= 128:
                self.set_color("#%02x%02x%02x" % tuple(self.px[o:o + 3]))
                self.set_tool("pencil")
            return
        if tool == "fill":
            if first:
                self.flood(x, y)
            return
        pts = [(x, y)]
        if self._last and self._last != (x, y):
            pts = self._line(self._last, (x, y))
        self._last = (x, y)
        rgba = (0, 0, 0, 0) if tool == "eraser" else hex_rgb(self.color) + (255,)
        s = self.size
        for (px_, py_) in pts:
            for dy in range(s):
                for dx in range(s):
                    tx, ty = px_ + dx - (s - 1) // 2, py_ + dy - (s - 1) // 2
                    if 0 <= tx < 64 and 0 <= ty < 64:
                        o = (ty * 64 + tx) * 4
                        self.px[o:o + 4] = bytes(rgba)
                        self.disp.put(self.texel_color(tx, ty), to=(tx, ty))
        self.zoomed = self.disp.zoom(self.Z)
        self.cv.itemconfigure(self.img_item, image=self.zoomed)
        self.view.invalidate()

    @staticmethod
    def _line(a, b):
        (x0, y0), (x1, y1) = a, b
        dx, dy = abs(x1 - x0), -abs(y1 - y0)
        sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
        err, out = dx + dy, []
        while True:
            out.append((x0, y0))
            if (x0, y0) == (x1, y1):
                return out
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy

    def flood(self, x, y):
        rect = next(((rx, ry, rw, rh) for _p, _l, _lab, rx, ry, rw, rh in net_rects(self.slim)
                     if rx <= x < rx + rw and ry <= y < ry + rh), None)
        if not rect:
            return
        rx, ry, rw, rh = rect
        o = (y * 64 + x) * 4
        target = bytes(self.px[o:o + 4])
        new = hex_rgb(self.color) + (255,)
        if target == bytes(new):
            return
        stack = [(x, y)]
        while stack:
            cx, cy = stack.pop()
            if not (rx <= cx < rx + rw and ry <= cy < ry + rh):
                continue
            o = (cy * 64 + cx) * 4
            if bytes(self.px[o:o + 4]) != target:
                continue
            self.px[o:o + 4] = bytes(new)
            stack += [(cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)]
        self.refresh_all()

    # ---- edit / file actions
    def do_undo(self):
        if self.undo:
            self.redo.append(bytes(self.px))
            self.px[:] = self.undo.pop()
            self.refresh_all()

    def do_redo(self):
        if self.redo:
            self.undo.append(bytes(self.px))
            self.px[:] = self.redo.pop()
            self.refresh_all()

    def do_clear(self):
        if messagebox.askyesno("Clear skin", "Erase the whole skin?", parent=self):
            self.snapshot()
            self.px[:] = bytes(64 * 64 * 4)
            self.refresh_all()

    def do_template(self):
        self.snapshot()
        self.px[:] = template_skin()
        self.refresh_all()

    def do_open(self):
        p = filedialog.askopenfilename(parent=self, title="Open a skin PNG", filetypes=[("PNG image", "*.png")])
        if not p:
            return
        try:
            px = skin_from_png(Path(p).read_bytes())
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Open skin", str(e), parent=self)
            return
        self.snapshot()
        self.px[:] = px
        self.name.set(Path(p).stem)
        self.refresh_all()

    def do_save(self):
        p = filedialog.asksaveasfilename(parent=self, title="Save skin as PNG", defaultextension=".png",
                                         initialfile=f"{self.name.get() or 'skin'}.png", filetypes=[("PNG image", "*.png")])
        if p:
            Path(p).write_bytes(png_encode(64, 64, self.px))
            self.app.toast("Skin saved")

    def do_library(self):
        self.entry = lib_add(self.name.get().strip() or "My skin", self.slim, self.px, self.entry)
        self.app.pages["skins"].reload(select=self.entry["id"])
        self.app.toast("Saved to your skins")

    def do_apply(self):
        self.app.apply_skin(bytearray(self.px), self.slim)


# --------------------------------------------------------------------------
# Skins page
# --------------------------------------------------------------------------
class SkinsPage(tk.Frame):
    PAD, TW, TH, GAP = 32, 132, 150, 14

    def __init__(self, master, app):
        super().__init__(master, bg=C["bg"])
        self.app = app
        self.items, self.sel, self.hover, self.hit = [], None, None, []
        self.capes, self.cape_sel, self.cape_hover, self.cape_hit, self.cape_user = [], None, None, [], None
        _, right, _ = app.header(self, "Skins", "Change your look. Upload a PNG or design one in the skin maker.")
        Btn(right, "Skin maker", self.new_maker, "primary", h=42).pack(side="right")
        Btn(right, "Upload PNG", self.upload, "secondary", h=42).pack(side="right", padx=(0, 10))
        body = tk.Frame(self, bg=C["bg"])
        body.pack(fill="both", expand=True, padx=32, pady=(6, 20))
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)
        card = Card(body, height=400)
        card.grid(row=0, column=0, sticky="ns", padx=(0, 20))
        card.config(width=330)
        card.grid_propagate(False)
        b = card.body
        self.view = SkinView(b, width=290, height=330, bg=C["card"])
        self.view.pack()
        self.view.auto = True
        self.name_lbl = lbl(b, "No skin selected", 13, "bold", bg=C["card"])
        self.name_lbl.pack(anchor="w", pady=(8, 0))
        self.meta_lbl = lbl(b, "Drag the model to rotate it.", 9, color=C["muted"], bg=C["card"])
        self.meta_lbl.pack(anchor="w")
        row = tk.Frame(b, bg=C["card"])
        row.pack(side="bottom", fill="x")
        self.b_apply = Btn(row, "Use this skin", self.apply, "primary", h=40, bg=C["card"], w=262)
        self.b_apply.pack(pady=(0, 6))
        r2 = tk.Frame(row, bg=C["card"])
        r2.pack(fill="x")
        self.b_edit = Btn(r2, "Edit", self.edit, "secondary", h=34, w=84, bg=C["card"])
        self.b_edit.pack(side="left")
        self.b_del = Btn(r2, "Delete", self.delete, "danger", h=34, w=84, bg=C["card"])
        self.b_del.pack(side="left", padx=6)
        self.b_imp = Btn(r2, "Import", self.import_account, "secondary", h=34, w=84, bg=C["card"])
        self.b_imp.pack(side="left")
        wrap = tk.Frame(body, bg=C["bg"])
        wrap.grid(row=0, column=1, sticky="nsew")
        lbl(wrap, "MY SKINS", 8, "bold", C["dim"], bg=C["bg"]).pack(anchor="w", pady=(0, 8))
        self.cv = tk.Canvas(wrap, bg=C["bg"], highlightthickness=0, bd=0)
        self.cv.pack(fill="both", expand=True)
        self.cv.bind("<Configure>", lambda _e: self.draw())
        self.cv.bind("<Motion>", self._motion)
        self.cv.bind("<Leave>", lambda _e: self._set_hover(None))
        self.cv.bind("<Button-1>", self._click)
        self.cv.bind("<Double-Button-1>", lambda _e: self.apply())
        ch = tk.Frame(wrap, bg=C["bg"])
        ch.pack(fill="x", pady=(10, 8))
        lbl(ch, "MY CAPES", 8, "bold", C["dim"], bg=C["bg"]).pack(side="left")
        Btn(ch, "Refresh", lambda: self.load_capes(True), "ghost", h=26, w=70, size=8, bg=C["bg"]).pack(side="right")
        self.b_cape = Btn(ch, "Equip cape", self.equip_cape, "secondary", h=26, w=96, size=8, bg=C["bg"])
        self.b_cape.pack(side="right", padx=(0, 6))
        self.cv2 = tk.Canvas(wrap, bg=C["bg"], highlightthickness=0, bd=0, height=176)
        self.cv2.pack(fill="x")
        self.cv2.bind("<Configure>", lambda _e: self.draw_capes())
        self.cv2.bind("<Motion>", self._cape_motion)
        self.cv2.bind("<Leave>", lambda _e: self._cape_hover(None))
        self.cv2.bind("<Button-1>", self._cape_click)
        self.cv2.bind("<Double-Button-1>", lambda _e: self.equip_cape())
        self.cape_note = "Sign in with a Microsoft account to see your capes."
        self.reload()

    # ---- data
    def reload(self, select=None):
        self.items = lib_load()
        if select:
            self.sel = select
        if self.sel not in [i["id"] for i in self.items]:
            self.sel = self.items[0]["id"] if self.items else None
        self.show_selected()
        self.draw()

    def current(self):
        return next((i for i in self.items if i["id"] == self.sel), None)

    def show_selected(self):
        e = self.current()
        for b in (self.b_apply, self.b_edit, self.b_del):
            b.set_enabled(bool(e))
        if not e:
            self.name_lbl.config(text="No skin yet")
            self.meta_lbl.config(text="Upload a PNG or open the skin maker.")
            self.view.set_pixels(template_skin(), False)
            return
        try:
            self.view.set_pixels(lib_px(e), e["slim"])
        except Exception:  # noqa: BLE001
            self.view.set_pixels(template_skin(), False)
        self.name_lbl.config(text=e["name"])
        self.meta_lbl.config(text=("Slim" if e["slim"] else "Classic") + " arms  ·  drag to rotate")

    # ---- drawing the library grid
    def draw(self):
        cv = self.cv
        cv.delete("all")
        self.hit = []
        w = max(cv.winfo_width(), 300)
        TW, TH, G = self.TW, self.TH, self.GAP
        cols = max(1, (w + G) // (TW + G))
        if not self.items:
            cv.create_text(4, 10, anchor="nw", fill=C["muted"], font=font(10),
                           text="Your skins will appear here.\nClick “Upload PNG” or “Skin maker” to add one.")
            return
        for n, e in enumerate(self.items):
            x, y = (n % cols) * (TW + G), (n // cols) * (TH + G)
            sel, hov = e["id"] == self.sel, e["id"] == self.hover
            rrect(cv, x, y, x + TW, y + TH, 14, fill=C["card2"] if (sel or hov) else C["card"],
                  outline=C["accent"] if sel else (C["line2"] if hov else C["line"]), width=2 if sel else 1)
            try:
                px = lib_px(e)
                self.draw_head(cv, px, x + (TW - 64) // 2, y + 14, 8)
            except Exception:  # noqa: BLE001
                pass
            cv.create_text(x + TW // 2, y + TH - 30, text=fit_text(e["name"], font(10, "bold"), TW - 20),
                           fill=C["text"], font=font(10, "bold"))
            cv.create_text(x + TW // 2, y + TH - 14, text="Slim" if e["slim"] else "Classic", fill=C["dim"], font=font(8))
            self.hit.append((x, y, x + TW, y + TH, e["id"]))

    @staticmethod
    def draw_head(cv, px, x0, y0, z):
        for (u, v, k) in ((8, 8, 0), (40, 8, 1)):
            for j in range(8):
                for i in range(8):
                    o = ((v + j) * 64 + u + i) * 4
                    if px[o + 3] >= 128:
                        c = "#%02x%02x%02x" % (px[o], px[o + 1], px[o + 2])
                        cv.create_rectangle(x0 + i * z - k * 0, y0 + j * z, x0 + i * z + z, y0 + j * z + z,
                                            fill=c, outline=c)

    def _at(self, e):
        return next((h[4] for h in self.hit if h[0] <= e.x <= h[2] and h[1] <= e.y <= h[3]), None)

    def _motion(self, e):
        self._set_hover(self._at(e))

    def _set_hover(self, sid):
        if sid != self.hover:
            self.hover = sid
            self.cv.config(cursor="hand2" if sid else "")
            self.draw()

    def _click(self, e):
        sid = self._at(e)
        if sid:
            self.sel = sid
            self.show_selected()
            self.draw()

    # ---- actions
    def new_maker(self):
        SkinMaker(self.app)

    def edit(self):
        e = self.current()
        if e:
            SkinMaker(self.app, lib_px(e), e["slim"], e["name"], e)

    def delete(self):
        e = self.current()
        if e and messagebox.askyesno("Delete skin", f"Delete “{e['name']}” from your skins?", parent=self.app.root):
            lib_remove(e)
            self.reload()

    def apply(self):
        e = self.current()
        if e:
            self.app.apply_skin(bytearray(lib_px(e)), e["slim"])

    def upload(self):
        p = filedialog.askopenfilename(parent=self.app.root, title="Choose a skin PNG", filetypes=[("PNG image", "*.png")])
        if not p:
            return
        try:
            px = skin_from_png(Path(p).read_bytes())
        except Exception as ex:  # noqa: BLE001
            messagebox.showerror("Upload skin", str(ex), parent=self.app.root)
            return
        self.add_dialog(Path(p).stem, False, px)

    def add_dialog(self, name, slim, px):
        def done(n, s, apply):
            e = lib_add(n, s, px)
            self.reload(select=e["id"])
            if apply:
                self.app.apply_skin(bytearray(px), s)
        SkinInfoDialog(self.app, name, slim, done)

    def import_account(self):
        acct = self.app.current_account()
        if not acct or acct.get("type") != "msa":
            self.app.toast("Sign in with a Microsoft account first", "err")
            return

        def work():
            a = self.app.fresh_account(acct)
            png, slim = account_skin(a["access_token"])
            return skin_from_png(png), slim
        self.app.bg(work, ok=lambda r: self.add_dialog(acct["username"], r[1], r[0]),
                    fail=lambda e: self.app.toast(str(e), "err"))

    # ---- capes
    def load_capes(self, force=False):
        acct = self.app.current_account()
        if not acct or acct.get("type") != "msa":
            self.capes, self.cape_user = [], None
            self.cape_note = "Sign in with a Microsoft account to see your capes."
            self.draw_capes()
            return
        if not force and self.cape_user == acct.get("uuid"):
            return
        self.cape_user = acct.get("uuid")
        self.cape_note = "Loading your capes…"
        self.draw_capes()

        def work():
            return account_capes(self.app.fresh_account(acct)["access_token"])

        def ok(capes):
            self.capes = capes
            act = next((c for c in capes if c["active"]), None)
            self.cape_sel = act["id"] if act else None
            self.cape_note = "" if capes else "This account doesn't own any capes."
            self.show_cape()
            self.draw_capes()

        def fail(e):
            self.cape_user = None
            self.cape_note = str(e)
            self.draw_capes()
        self.app.bg(work, ok=ok, fail=fail)

    def show_cape(self):
        c = next((c for c in self.capes if c["id"] == self.cape_sel), None)
        self.view.set_cape(c["px"] if c else None)

    def draw_capes(self):
        cv = self.cv2
        cv.delete("all")
        self.cape_hit = []
        if not self.capes:
            cv.create_text(4, 6, anchor="nw", fill=C["muted"], font=font(10), text=self.cape_note)
            self.b_cape.set_enabled(False)
            return
        self.b_cape.set_enabled(True)
        TW, TH, G, Z = 104, 164, 12, 6
        for n, c in enumerate([None] + self.capes):
            cid = c["id"] if c else None
            x = n * (TW + G)
            sel, hov = cid == self.cape_sel, (cid if c else "none") == self.cape_hover
            rrect(cv, x, 0, x + TW, TH, 14, fill=C["card2"] if (sel or hov) else C["card"],
                  outline=C["accent"] if sel else (C["line2"] if hov else C["line"]), width=2 if sel else 1)
            if c:
                px = c["px"]
                for j in range(16):
                    for i in range(10):
                        o = ((1 + j) * 64 + 1 + i) * 4
                        if px[o + 3] >= 128:
                            col = "#%02x%02x%02x" % (px[o], px[o + 1], px[o + 2])
                            cv.create_rectangle(x + 22 + i * Z, 12 + j * Z * 0.82, x + 22 + i * Z + Z, 12 + (j + 1) * Z * 0.82,
                                                fill=col, outline=col)
            else:
                cv.create_text(x + TW // 2, 62, text="No cape", fill=C["muted"], font=font(10))
            name = "None" if not c else c["alias"]
            cv.create_text(x + TW // 2, TH - 26, text=fit_text(name, font(9, "bold"), TW - 14), fill=C["text"], font=font(9, "bold"))
            if c and c["active"]:
                cv.create_text(x + TW // 2, TH - 11, text="Equipped", fill=C["accent"], font=font(8, "bold"))
            self.cape_hit.append((x, 0, x + TW, TH, cid if c else "none"))

    def _cape_at(self, e):
        return next((h[4] for h in self.cape_hit if h[0] <= e.x <= h[2] and h[1] <= e.y <= h[3]), False)

    def _cape_motion(self, e):
        self._cape_hover(self._cape_at(e) or None)

    def _cape_hover(self, cid):
        if cid != self.cape_hover:
            self.cape_hover = cid
            self.cv2.config(cursor="hand2" if cid else "")
            self.draw_capes()

    def _cape_click(self, e):
        cid = self._cape_at(e)
        if cid is False:
            return
        self.cape_sel = None if cid == "none" else cid
        self.show_cape()
        self.draw_capes()

    def equip_cape(self):
        acct = self.app.current_account()
        if not acct or acct.get("type") != "msa":
            self.app.toast("Sign in with a Microsoft account first", "err")
            return
        cid = self.cape_sel

        def work():
            cape_set(self.app.fresh_account(acct)["access_token"], cid)

        def ok(_r):
            for c in self.capes:
                c["active"] = c["id"] == cid
            self.draw_capes()
            self.app.toast("Cape changed" if cid else "Cape removed")
        self.app.bg(work, ok=ok, fail=lambda e: self.app.toast(str(e), "err"))


# --------------------------------------------------------------------------
# Main window
# --------------------------------------------------------------------------
WINDOW_TITLE = APP_NAME


class App:
    def __init__(self, root):
        self.root = root
        root.title(WINDOW_TITLE)
        root.configure(bg=C["bg"])
        w, h = 1180, 740
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        w, h = min(w, sw - 80), min(h, sh - 120)
        root.geometry(f"{w}x{h}+{max(0, (sw - w) // 2)}+{max(0, (sh - h) // 3)}")
        root.minsize(960, 620)
        setup_style(root)
        self.q = queue.Queue()
        self.cfg = load_json(CONFIG, {})
        # Only Microsoft accounts are supported; ignore anything else left in an old file.
        self.accounts = [a for a in load_json(ACCOUNTS, {}).get("accounts", []) if a.get("type") == "msa"]
        self.game_versions, self.instances = [], []
        self.busy, self.phase = False, None
        self.sel_id = self.cfg.get("last_instance")
        self.page = "instances"
        self.cursor_tk = ""
        self.build()
        self.log(f"{APP_NAME} {APP_VERSION}")
        self.log("Not an official Minecraft product; not affiliated with Mojang or Microsoft.")
        self.log(f"Data folder: {ROOT}")
        self.refresh_accounts()
        self.refresh_instances()
        self.apply_cursor()
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.bg(lambda: [(v["version"], v["stable"]) for v in get_json(f"{FABRIC_META}/versions/game")],
                self.set_versions, lambda e: self.log(f"Could not load version list: {e}"))
        root.after(100, self.poll)

    # ---- layout
    def header(self, parent, title, sub):
        f = tk.Frame(parent, bg=C["bg"])
        f.pack(fill="x", padx=32, pady=(30, 10))
        left = tk.Frame(f, bg=C["bg"])
        left.pack(side="left")
        lbl(left, title, 24, "bold", bg=C["bg"]).pack(anchor="w")
        s = lbl(left, sub, 10, color=C["muted"], bg=C["bg"])
        s.pack(anchor="w", pady=(2, 0))
        right = tk.Frame(f, bg=C["bg"])
        right.pack(side="right")
        return f, right, s

    def build(self):
        root = self.root
        root.grid_columnconfigure(1, weight=1)
        root.grid_rowconfigure(0, weight=1)
        side = tk.Frame(root, bg=C["side"], width=244)
        side.grid(row=0, column=0, sticky="ns")
        side.pack_propagate(False)
        tk.Frame(root, bg=C["line"], width=1).grid(row=0, column=0, sticky="nse")
        main = tk.Frame(root, bg=C["bg"])
        main.grid(row=0, column=1, sticky="nsew")
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(0, weight=1)

        # brand
        brand = tk.Canvas(side, width=244, height=92, bg=C["side"], highlightthickness=0, bd=0)
        brand.pack(fill="x")
        draw_logo(brand, 24, 26, 40)
        brand.create_text(78, 40, text="Spectra", anchor="w", fill=C["text"], font=font(16, "bold"))
        brand.create_text(79, 60, text="L A U N C H E R", anchor="w", fill=C["dim"], font=font(7, "bold"))

        # navigation
        nav = tk.Frame(side, bg=C["side"])
        nav.pack(fill="x", padx=12, pady=(6, 0))
        self.nav = {}
        for key, text, icon in (("instances", "Instances", "grid"), ("accounts", "Accounts", "user"),
                                ("skins", "Skins", "skin"), ("cursor", "Cursor", "cursor"), ("console", "Console", "term"), ("about", "About", "info")):
            n = NavItem(nav, text, icon, lambda k=key: self.show_page(k))
            n.pack(fill="x", pady=2)
            self.nav[key] = n

        # account chip + disclaimer
        foot = tk.Frame(side, bg=C["side"])
        foot.pack(side="bottom", fill="x", padx=12, pady=(0, 14))
        lbl(foot, "Not an official Minecraft product.\nNot affiliated with Mojang or Microsoft.", 7,
            color=C["dim"], bg=C["side"], justify="left").pack(anchor="w", padx=4, pady=(10, 0), side="bottom")
        self.chip = tk.Canvas(foot, width=220, height=62, bg=C["side"], highlightthickness=0, bd=0, cursor="hand2")
        self.chip.pack(side="bottom")
        self.chip.bind("<Button-1>", lambda _e: self.show_page("accounts"))
        self.chip.bind("<Enter>", lambda _e: self.draw_chip(True))
        self.chip.bind("<Leave>", lambda _e: self.draw_chip(False))

        # pages
        holder = tk.Frame(main, bg=C["bg"])
        holder.grid(row=0, column=0, sticky="nsew")
        holder.grid_columnconfigure(0, weight=1)
        holder.grid_rowconfigure(0, weight=1)
        self.pages = {}
        self.pages["instances"] = self.build_instances(holder)
        self.pages["accounts"] = AccountsPage(holder, self)
        self.pages["skins"] = SkinsPage(holder, self)
        self.pages["cursor"] = CursorPage(holder, self)
        self.pages["console"] = self.build_console(holder)
        self.pages["about"] = self.build_about(holder)
        for p in self.pages.values():
            p.grid(row=0, column=0, sticky="nsew")

        # launch bar
        bar = tk.Frame(main, bg=C["side"], height=98)
        bar.grid(row=1, column=0, sticky="ew")
        bar.pack_propagate(False)
        tk.Frame(bar, bg=C["line"], height=1).pack(fill="x", side="top")
        inner = tk.Frame(bar, bg=C["side"])
        inner.pack(fill="both", expand=True, padx=32)
        inner.grid_columnconfigure(1, weight=1)
        inner.grid_rowconfigure(0, weight=1)
        left = tk.Frame(inner, bg=C["side"], width=300)
        left.grid(row=0, column=0, sticky="w")
        self.bar_icon = tk.Canvas(left, width=54, height=54, bg=C["side"], highlightthickness=0, bd=0)
        self.bar_icon.pack(side="left")
        lt = tk.Frame(left, bg=C["side"])
        lt.pack(side="left", padx=(14, 0))
        self.bar_name = lbl(lt, "", 12, "bold", bg=C["side"])
        self.bar_name.pack(anchor="w")
        self.bar_meta = lbl(lt, "", 9, color=C["muted"], bg=C["side"])
        self.bar_meta.pack(anchor="w")
        mid = tk.Frame(inner, bg=C["side"])
        mid.grid(row=0, column=1, sticky="ew", padx=28)
        self.status = lbl(mid, "Ready", 9, color=C["muted"], bg=C["side"], anchor="w")
        self.status.pack(fill="x", pady=(0, 7))
        self.meter = Meter(mid, height=10, bg=C["side"])
        self.meter.pack(fill="x")
        self.btn_launch = Btn(inner, "PLAY", self.launch, "primary", w=190, h=58, size=12, r=16, bg=C["side"], icon="play")
        self.btn_launch.grid(row=0, column=2, sticky="e")
        self.show_page("instances")

    def build_instances(self, parent):
        f = tk.Frame(parent, bg=C["bg"])
        _, right, self.inst_sub = self.header(f, "Instances", "")
        Btn(right, "New instance", self.add_instance, "primary", h=42, icon="plus").pack()
        self.grid_view = InstanceGrid(f, self)
        self.grid_view.pack(fill="both", expand=True)
        return f

    def build_console(self, parent):
        f = tk.Frame(parent, bg=C["bg"])
        _, right, _ = self.header(f, "Console", "Launcher activity and game output.")
        Btn(right, "Clear", self.clear_log, "secondary", h=38).pack(side="right")
        Btn(right, "Copy all", self.copy_log, "secondary", h=38).pack(side="right", padx=(0, 8))
        box = tk.Frame(f, bg=C["line"], padx=1, pady=1)
        box.pack(fill="both", expand=True, padx=32, pady=(4, 28))
        inner = tk.Frame(box, bg="#090d0a")
        inner.pack(fill="both", expand=True)
        self.logbox = tk.Text(inner, bg="#090d0a", fg="#b4c4ba", insertbackground=C["accent"], relief="flat", bd=0,
                              highlightthickness=0, wrap="word", font=font(9, mono=True), padx=16, pady=14,
                              state="disabled", selectbackground="#1d3a2a", spacing1=2)
        sb = ttk.Scrollbar(inner, command=self.logbox.yview)
        self.logbox.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.logbox.pack(side="left", fill="both", expand=True)
        self.logbox.tag_configure("err", foreground=C["danger"])
        self.logbox.tag_configure("warn", foreground=C["warn"])
        self.logbox.tag_configure("sys", foreground=C["accent"])
        return f

    def build_about(self, parent):
        f = tk.Frame(parent, bg=C["bg"])
        self.header(f, "About", "Free and open source.")
        card = Card(f, height=330, pad=28)
        card.pack(fill="x", padx=32, pady=(6, 0))
        b = card.body
        top = tk.Frame(b, bg=C["card"])
        top.grid(row=0, column=0, sticky="w")
        logo = tk.Canvas(top, width=78, height=78, bg=C["card"], highlightthickness=0, bd=0)
        logo.pack(side="left", padx=(0, 20))
        draw_logo(logo, 0, 0, 74)
        tt = tk.Frame(top, bg=C["card"])
        tt.pack(side="left")
        lbl(tt, APP_NAME, 20, "bold", bg=C["card"]).pack(anchor="w")
        lbl(tt, f"Version {APP_VERSION}", 10, color=C["muted"], bg=C["card"]).pack(anchor="w")
        lbl(b, "A launcher for Minecraft: Java Edition with the Fabric mod loader. Create instances, install mods "
               "and their dependencies, and play with your own Microsoft account. Spectra runs entirely on your "
               "computer and collects no data.", 10, color=C["text"], bg=C["card"], wraplength=640,
            justify="left").grid(row=2, column=0, sticky="w", pady=(20, 10))
        lbl(b, "Spectra Launcher is not an official Minecraft product. It is not approved by or associated with "
               "Mojang or Microsoft, and it is not affiliated with the Fabric project.", 9, color=C["muted"],
            bg=C["card"], wraplength=640, justify="left").grid(row=3, column=0, sticky="w")
        row = tk.Frame(b, bg=C["card"])
        row.grid(row=4, column=0, sticky="w", pady=(20, 0))
        Btn(row, "Source on GitHub", lambda: webbrowser.open("https://github.com/mcpacks-site/Spectra-launcher"),
            "secondary", h=38, bg=C["card"]).pack(side="left")
        Btn(row, "Open data folder", lambda: open_path(ROOT), "secondary", h=38, bg=C["card"]).pack(side="left", padx=8)
        return f

    # ---- navigation
    def show_page(self, name):
        self.page = name
        self.pages[name].tkraise()
        for k, n in self.nav.items():
            n._set(active=(k == name))
        if name == "console":
            self.logbox.see("end")
        if name == "cursor":
            self.pages["cursor"].draw()
        if name == "skins":
            self.pages["skins"].load_capes()

    # ---- skins
    def apply_skin(self, px, slim):
        acct = self.current_account()
        if not acct or acct.get("type") != "msa":
            self.toast("Sign in with a Microsoft account to change your skin", "err")
            return
        png = png_encode(64, 64, px)
        self.toast("Uploading skin…")

        def work():
            a = self.fresh_account(acct)
            skin_upload(a["access_token"], png, "slim" if slim else "classic")
        self.bg(work, ok=lambda _r: self.toast("Skin changed. It shows up next time you join a game."),
                fail=lambda e: self.toast(str(e), "err"))

    # ---- cursor
    def cursor_scope(self):
        s = self.cfg.get("cursor_scope", "launcher")
        return s if s in ("launcher", "minecraft") or (s == "system" and OS == "windows") else "launcher"

    def set_cursor(self, scope=None, style=None):
        if scope:
            self.cfg["cursor_scope"] = scope
        if style:
            self.cfg["cursor_style"] = style
        self.save_cfg()
        self.apply_cursor()
        if scope in ("minecraft", "system"):
            self.toast("The cursor mod is added to your instances next time you play")

    def apply_cursor(self):
        style = self.cfg.get("cursor_style", "default")
        if style not in {s[0] for s in CURSOR_STYLES}:
            style = "default"
        try:
            self.cursor_tk = tk_cursor_for(style, self.root)
        except Exception as e:  # noqa: BLE001
            self.cursor_tk = ""
            self.log(f"Could not load cursor: {e}")
        self.root.config(cursor=self.cursor_tk)
        for w in self.root.winfo_children():
            if isinstance(w, tk.Toplevel):
                w.config(cursor=self.cursor_tk)
        if OS == "windows":
            if self.cursor_scope() == "system" and style != "default":
                self.cfg["cursor_system"] = win_set_system_cursor(cursor_file(style))
                atexit.register(win_restore_cursors)
            elif self.cfg.get("cursor_system"):
                win_restore_cursors()
                self.cfg["cursor_system"] = False
            self.save_cfg()

    def on_close(self):
        if OS == "windows" and self.cfg.get("cursor_system"):
            win_restore_cursors()
            self.cfg["cursor_system"] = False
            self.save_cfg()
        self.root.destroy()

    # ---- small UI helpers
    def toast(self, text, kind="ok"):
        col = C["accent"] if kind == "ok" else C["danger"]
        t = tk.Frame(self.root, bg=col, padx=1, pady=1)
        inner = tk.Frame(t, bg=C["card2"])
        inner.pack()
        tk.Frame(inner, bg=col, width=4).pack(side="left", fill="y")
        lbl(inner, text, 10, "bold", bg=C["card2"]).pack(side="left", padx=16, pady=12)
        t.place(relx=1.0, rely=1.0, x=-28, y=-122, anchor="se")
        t.lift()
        self.root.after(2600, t.destroy)

    def draw_chip(self, hover=False):
        cv, a = self.chip, self.current_account()
        cv.delete("all")
        rrect(cv, 1, 1, 219, 61, 14, fill="#121b15" if hover else "#0e1510", outline="#2a3a31" if hover else C["line"])
        if a:
            draw_avatar(cv, 12, 12, 38, acct_key(a))
            cv.create_text(62, 24, text=fit_text(a["username"], font(10, "bold"), 140), anchor="w",
                           fill=C["text"], font=font(10, "bold"))
            cv.create_text(62, 42, text="Microsoft account",
                           anchor="w", fill=C["muted"], font=font(8))
        else:
            cv.create_oval(12, 12, 50, 50, fill=C["card2"], outline=C["line2"])
            draw_icon(cv, "user", 31, 31, 18, C["muted"])
            cv.create_text(62, 24, text="Not signed in", anchor="w", fill=C["text"], font=font(10, "bold"))
            cv.create_text(62, 42, text="Click to add an account", anchor="w", fill=C["accent"], font=font(8))

    def update_bar(self):
        inst = self.instance_by_id(self.sel_id)
        ic = self.bar_icon
        ic.delete("all")
        if inst:
            c1, c2 = inst_colors(inst["id"])
            ic.create_image(1, 1, anchor="nw", image=grad_image(ic, 52, 52, c1, c2, 12))
            ic.create_text(27, 27, text=inst["version"].split("-")[0][:7], fill="#ffffff", font=font(9, "bold"))
            self.bar_name.config(text=fit_text(inst["name"], font(12, "bold"), 210))
            self.bar_meta.config(text=f"Minecraft {inst['version']}  ·  Fabric  ·  {inst.get('ram_gb', 4):g} GB")
        else:
            rrect(ic, 1, 1, 53, 53, 12, fill="#0e1510", outline=C["line2"], dash=(3, 3))
            self.bar_name.config(text="No instance selected")
            self.bar_meta.config(text="Create or pick one to play")
        self.btn_launch.set_enabled(bool(inst) and not self.busy)

    # ---- persistence
    def save_cfg(self):
        save_json(CONFIG, self.cfg)

    def save_accounts(self):
        save_json(ACCOUNTS, {"accounts": self.accounts}, private=True)

    # ---- thread-safe messaging
    def log(self, text):
        self.q.put(("log", text))

    def progress(self, done, total, label):
        self.q.put(("progress", done, total, label))

    def bg(self, fn, ok=None, fail=None):
        def run():
            try:
                res = fn()
            except Exception as e:  # noqa: BLE001
                self.q.put(("cb", fail, e))
            else:
                self.q.put(("cb", ok, res))
        threading.Thread(target=run, daemon=True).start()

    def append_log(self, text):
        lb = self.logbox
        low = text.lower()
        tag = "err" if ("error" in low or "exception" in low or "failed" in low) else (
            "warn" if "warn" in low else ("sys" if text.startswith(("Preparing", "Launching", "Using ", "Java:")) else ""))
        lb.configure(state="normal")
        lb.insert("end", text + "\n", tag)
        if int(lb.index("end-1c").split(".")[0]) > 4000:
            lb.delete("1.0", "500.0")
        lb.configure(state="disabled")
        lb.see("end")

    def clear_log(self):
        self.logbox.configure(state="normal")
        self.logbox.delete("1.0", "end")
        self.logbox.configure(state="disabled")

    def copy_log(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.logbox.get("1.0", "end"))
        self.toast("Console copied")

    def poll(self):
        try:
            while True:
                msg = self.q.get_nowait()
                kind = msg[0]
                if kind == "log":
                    self.append_log(msg[1])
                    if self.phase == "prep":
                        self.status.config(text=fit_text(msg[1], font(9), 560))
                elif kind == "progress":
                    _, d, t, label = msg
                    self.meter.set(d / max(1, t))
                    self.status.config(text=f"{label}   {d} / {t}")
                elif kind == "busy":
                    self.busy = msg[1]
                    if msg[1]:
                        self.phase = "prep"
                        self.meter.indeterminate(True)
                        self.status.config(text="Preparing…")
                        self.btn_launch.configure_text("LAUNCHING")
                    else:
                        self.phase = None
                        self.meter.set(0)
                        self.status.config(text="Ready")
                        self.btn_launch.configure_text("PLAY")
                    self.update_bar()
                    self.grid_view.draw()
                elif kind == "running":
                    self.phase = "run"
                    self.meter.set(1.0)
                    self.status.config(text=f"Playing {msg[1]}")
                    self.btn_launch.configure_text("PLAYING")
                elif kind == "error":
                    self.toast("Launch failed", "err")
                    messagebox.showerror("Error", msg[1])
                elif kind == "cb":
                    if msg[1]:
                        msg[1](msg[2])
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    # ---- versions
    def set_versions(self, versions):
        self.game_versions = versions

    # ---- accounts
    def current_account(self):
        key = self.cfg.get("account")
        for a in self.accounts:
            if acct_key(a) == key:
                return a
        return self.accounts[0] if self.accounts else None

    def refresh_accounts(self):
        self.draw_chip()
        if "accounts" in getattr(self, "pages", {}):
            self.pages["accounts"].reload()

    def add_account(self, acct):
        self.accounts = [a for a in self.accounts if acct_key(a) != acct_key(acct)] + [acct]
        self.cfg["account"] = acct_key(acct)
        self.save_cfg()
        self.save_accounts()
        self.refresh_accounts()

    def fresh_account(self, acct):
        """Refresh an expiring Microsoft token (runs on a worker thread)."""
        if acct.get("type") != "msa" or time.time() < acct.get("expires_at", 0) - 300:
            return acct
        auth = MSAuth()
        new = auth.minecraft_account(auth.refresh(acct["refresh_token"]))
        self.accounts = [new if acct_key(a) == acct_key(acct) else a for a in self.accounts]
        self.save_accounts()
        return new

    # ---- instances
    def instance_by_id(self, iid):
        return next((i for i in self.instances if i["id"] == iid), None)

    def refresh_instances(self, select=None):
        self.instances = list_instances()
        if select:
            self.sel_id = select
        if not self.instance_by_id(self.sel_id):
            self.sel_id = self.instances[0]["id"] if self.instances else None
        n = len(self.instances)
        self.inst_sub.config(text=f"{n} instance{'s' if n != 1 else ''}  ·  Minecraft: Java Edition with Fabric")
        self.update_bar()
        self.grid_view.draw()

    def select(self, iid):
        if iid != self.sel_id:
            self.sel_id = iid
            self.cfg["last_instance"] = iid
            self.save_cfg()
            self.update_bar()
            self.grid_view.draw()

    def selected_instance(self, iid=None):
        iid = iid or self.sel_id
        inst = load_json(INSTANCES / iid / "instance.json", None) if iid else None
        if not inst:
            self.toast("Select an instance first", "err")
        return inst

    def card_menu(self, event, iid):
        m = tk.Menu(self.root, tearoff=0, bg=C["card2"], fg=C["text"], activebackground=C["accent2"],
                    activeforeground=C["ink"], bd=0, relief="flat", font=font(10))
        m.add_command(label="Play", command=lambda: self.launch(iid))
        m.add_command(label="Settings…", command=lambda: self.edit_instance(iid))
        m.add_command(label="Mods…", command=lambda: self.edit_instance(iid, tab=1))
        m.add_command(label="Open folder", command=lambda: self.open_instance(iid))
        m.add_separator()
        m.add_command(label="Delete…", command=lambda: self.delete_instance(iid))
        m.tk_popup(event.x_root, event.y_root)

    def add_instance(self):
        if not self.game_versions:
            self.toast("Still loading the version list…", "err")
            return
        AddInstanceDialog(self)

    def edit_instance(self, iid=None, tab=0):
        inst = self.selected_instance(iid)
        if inst:
            EditInstanceDialog(self, inst, tab)

    def open_instance(self, iid=None):
        inst = self.selected_instance(iid)
        if inst:
            open_path(game_dir_of(inst))

    def delete_instance(self, iid=None):
        inst = self.selected_instance(iid)
        if inst and messagebox.askyesno("Delete", f"Delete '{inst['name']}' and all its worlds and mods?"):
            shutil.rmtree(INSTANCES / inst["id"], ignore_errors=True)
            self.refresh_instances()
            self.toast(f"Deleted {inst['name']}")

    # ---- launching
    def launch(self, iid=None):
        if self.busy:
            return
        inst = self.selected_instance(iid)
        if not inst:
            return
        acct = self.current_account()
        if not acct:
            self.show_page("accounts")
            self.toast("Sign in with your Microsoft account first", "err")
            return
        self.q.put(("busy", True))
        threading.Thread(target=self.worker, args=(inst, acct), daemon=True).start()

    def worker(self, inst, acct):
        try:
            acct = self.fresh_account(acct)
            cmd, game_dir = Core(self.log, self.progress).prepare(inst, acct)
            try:
                sync_cursor_mod(inst, self.cursor_scope() in ("minecraft", "system"), self.log)
            except Exception as e:  # noqa: BLE001
                self.log(f"WARNING: could not update the cursor mod: {e}")
            save_instance(inst)
            self.log(f"Launching as {acct['username']}...")
            proc = subprocess.Popen(cmd, cwd=str(game_dir), stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, errors="replace",
                                    creationflags=NOWIN)
            self.q.put(("running", f"{inst['name']}"))
            for line in proc.stdout:
                self.log(line.rstrip())
            self.log(f"Minecraft exited with code {proc.wait()}.")
        except Exception as e:  # noqa: BLE001
            self.log(f"ERROR: {e}")
            self.q.put(("error", str(e)))
        finally:
            self.q.put(("busy", False))


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    INSTANCES.mkdir(parents=True, exist_ok=True)
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()