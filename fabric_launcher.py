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
APP_VERSION = "2.0"
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
# Dialogs
# --------------------------------------------------------------------------
def make_modal(win, parent):
    win.transient(parent)
    win.grab_set()
    win.focus_set()


class AddInstanceDialog(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.title("Add instance")
        self.geometry("380x230")
        self.resizable(False, False)
        make_modal(self, app.root)
        f = ttk.Frame(self, padding=14)
        f.pack(fill="both", expand=True)
        f.columnconfigure(1, weight=1)
        ttk.Label(f, text="Name").grid(row=0, column=0, sticky="w", pady=6)
        self.name = tk.StringVar(value="New instance")
        ttk.Entry(f, textvariable=self.name).grid(row=0, column=1, columnspan=2, sticky="ew", pady=6)
        ttk.Label(f, text="Minecraft").grid(row=1, column=0, sticky="w", pady=6)
        self.ver = tk.StringVar()
        self.box = ttk.Combobox(f, textvariable=self.ver, state="readonly")
        self.box.grid(row=1, column=1, sticky="ew", pady=6)
        self.snap = tk.BooleanVar(value=False)
        ttk.Checkbutton(f, text="Snapshots", variable=self.snap, command=self.refresh).grid(row=1, column=2, padx=6)
        self.api = tk.BooleanVar(value=True)
        ttk.Checkbutton(f, text="Install Fabric API automatically", variable=self.api).grid(
            row=2, column=0, columnspan=3, sticky="w", pady=6)
        ttk.Button(f, text="Create", command=self.create).grid(row=3, column=0, columnspan=3, sticky="ew", ipady=4, pady=10)
        self.refresh()

    def refresh(self):
        vs = [v for v, stable in self.app.game_versions if stable or self.snap.get()]
        self.box.configure(values=vs)
        if vs and self.ver.get() not in vs:
            self.ver.set(vs[0])

    def create(self):
        name = self.name.get().strip()
        if not name or not self.ver.get():
            messagebox.showwarning("Add instance", "Enter a name and pick a version.", parent=self)
            return
        inst = {"id": new_instance_id(name), "name": name, "version": self.ver.get(),
                "ram_gb": 4, "java": "", "jvm_args": "", "auto_fabric_api": self.api.get(), "mods": {}}
        save_instance(inst)
        game_dir_of(inst).mkdir(parents=True, exist_ok=True)
        self.app.refresh_instances(select=inst["id"])
        self.destroy()


class AccountsDialog(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.cancel = threading.Event()
        self.title("Accounts")
        self.geometry("520x380")
        make_modal(self, app.root)
        self.protocol("WM_DELETE_WINDOW", self.close)
        f = ttk.Frame(self, padding=12)
        f.pack(fill="both", expand=True)
        f.columnconfigure(0, weight=1)

        self.lb = tk.Listbox(f, height=8, exportselection=False)
        self.lb.grid(row=0, column=0, sticky="nsew", pady=(0, 8))
        f.rowconfigure(0, weight=1)

        row = ttk.Frame(f)
        row.grid(row=1, column=0, sticky="ew")
        ttk.Button(row, text="Add Microsoft account", command=self.add_ms).pack(side="left")
        ttk.Button(row, text="Set default", command=self.set_default).pack(side="left", padx=6)
        ttk.Button(row, text="Remove", command=self.remove).pack(side="left")

        self.info = ttk.Label(f, text="Sign in with the Microsoft account that owns Minecraft: Java Edition.",
                              wraplength=480, justify="left")
        self.info.grid(row=2, column=0, sticky="w", pady=(10, 0))
        self.reload()

    def close(self):
        self.cancel.set()
        self.destroy()

    def reload(self):
        self.lb.delete(0, "end")
        for a in self.app.accounts:
            mark = "  ★" if acct_key(a) == self.app.cfg.get("account") else ""
            self.lb.insert("end", acct_label(a) + mark)

    def selected(self):
        s = self.lb.curselection()
        return self.app.accounts[s[0]] if s else None

    def set_default(self):
        a = self.selected()
        if a:
            self.app.cfg["account"] = acct_key(a)
            self.app.save_cfg()
            self.app.refresh_accounts()
            self.reload()

    def remove(self):
        a = self.selected()
        if a and messagebox.askyesno("Remove account", f"Remove {a['username']}?", parent=self):
            self.app.accounts.remove(a)
            self.app.save_accounts()
            self.app.refresh_accounts()
            self.reload()

    def add_ms(self):
        self.cancel.clear()
        auth = MSAuth()
        self.info.configure(text="Contacting Microsoft...")

        def got_code(dc):
            if not self.winfo_exists():
                return
            url, code = dc["verification_uri"], dc["user_code"]
            self.info.configure(text=f"Go to {url} and enter the code:  {code}\n"
                                     "(The code was copied to your clipboard and the page was opened.)\n"
                                     "Waiting for you to finish signing in...")
            self.clipboard_clear()
            self.clipboard_append(code)
            webbrowser.open(url)
            self.app.bg(lambda: auth.minecraft_account(auth.poll_device(dc, self.cancel)),
                        self.signed_in, self.failed)

        self.app.bg(auth.start_device, got_code, self.failed)

    def signed_in(self, acct):
        self.app.add_account(acct)
        if self.winfo_exists():
            self.info.configure(text=f"Signed in as {acct['username']}.")
            self.reload()

    def failed(self, err):
        if self.winfo_exists():
            self.info.configure(text=f"Sign-in failed: {err}")


class EditInstanceDialog(tk.Toplevel):
    def __init__(self, app, inst):
        super().__init__(app.root)
        self.app, self.inst = app, inst
        self.title(f"Edit instance - {inst['name']}")
        self.geometry("760x560")
        make_modal(self, app.root)
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=8, pady=8)
        self.build_settings(nb)
        self.build_mods(nb)

    # ---- settings tab
    def build_settings(self, nb):
        f = ttk.Frame(nb, padding=14)
        nb.add(f, text="Settings")
        f.columnconfigure(1, weight=1)
        i = self.inst
        self.v_name = tk.StringVar(value=i["name"])
        self.v_ram = tk.DoubleVar(value=i.get("ram_gb", 4))
        self.v_java = tk.StringVar(value=i.get("java", ""))
        self.v_args = tk.StringVar(value=i.get("jvm_args", ""))
        self.v_api = tk.BooleanVar(value=i.get("auto_fabric_api", True))
        rows = [("Name", ttk.Entry(f, textvariable=self.v_name)),
                ("Memory (GB)", ttk.Spinbox(f, from_=1, to=64, increment=0.5, textvariable=self.v_ram, width=8)),
                ("Java path (optional)", ttk.Entry(f, textvariable=self.v_java)),
                ("Extra JVM args", ttk.Entry(f, textvariable=self.v_args))]
        for r, (label, w) in enumerate(rows):
            ttk.Label(f, text=label).grid(row=r, column=0, sticky="w", pady=6)
            w.grid(row=r, column=1, sticky="ew" if not isinstance(w, ttk.Spinbox) else "w", pady=6)
        ttk.Label(f, text=f"Minecraft {i['version']}  |  Fabric").grid(row=4, column=0, columnspan=2, sticky="w", pady=6)
        ttk.Checkbutton(f, text="Keep Fabric API installed and up to date",
                        variable=self.v_api).grid(row=5, column=0, columnspan=2, sticky="w", pady=6)
        ttk.Button(f, text="Save", command=self.save).grid(row=6, column=0, columnspan=2, sticky="ew", ipady=4, pady=12)

    def save(self):
        try:
            ram = float(self.v_ram.get())
        except (tk.TclError, ValueError):
            messagebox.showwarning("Settings", "Memory must be a number.", parent=self)
            return
        self.inst.update(name=self.v_name.get().strip() or self.inst["name"], ram_gb=ram,
                         java=self.v_java.get().strip(), jvm_args=self.v_args.get().strip(),
                         auto_fabric_api=self.v_api.get())
        save_instance(self.inst)
        self.app.refresh_instances(select=self.inst["id"])
        self.title(f"Edit instance - {self.inst['name']}")

    # ---- mods tab
    @property
    def mods_dir(self):
        return game_dir_of(self.inst) / "mods"

    def build_mods(self, nb):
        f = ttk.Frame(nb, padding=10)
        nb.add(f, text="Mods")
        f.columnconfigure(0, weight=1)
        f.rowconfigure(1, weight=1)
        f.rowconfigure(5, weight=1)

        ttk.Label(f, text="Installed").grid(row=0, column=0, sticky="w")
        self.inst_tree = ttk.Treeview(f, columns=("file", "state"), show="headings", height=7)
        self.inst_tree.heading("file", text="File")
        self.inst_tree.heading("state", text="State")
        self.inst_tree.column("state", width=90, stretch=False)
        self.inst_tree.grid(row=1, column=0, sticky="nsew")
        bar = ttk.Frame(f)
        bar.grid(row=2, column=0, sticky="w", pady=6)
        ttk.Button(bar, text="Enable / disable", command=self.toggle).pack(side="left")
        ttk.Button(bar, text="Remove", command=self.remove).pack(side="left", padx=6)
        ttk.Button(bar, text="Open mods folder", command=lambda: open_path(self.mods_dir)).pack(side="left")

        sr = ttk.Frame(f)
        sr.grid(row=3, column=0, sticky="ew", pady=(8, 4))
        sr.columnconfigure(1, weight=1)
        ttk.Label(sr, text="Search Modrinth").grid(row=0, column=0)
        self.q = tk.StringVar()
        e = ttk.Entry(sr, textvariable=self.q)
        e.grid(row=0, column=1, sticky="ew", padx=6)
        e.bind("<Return>", lambda _e: self.search())
        ttk.Button(sr, text="Search", command=self.search).grid(row=0, column=2)

        self.res = ttk.Treeview(f, columns=("title", "dl", "desc"), show="headings", height=7)
        for c, t, w in (("title", "Mod", 160), ("dl", "Downloads", 90), ("desc", "Description", 380)):
            self.res.heading(c, text=t)
            self.res.column(c, width=w, stretch=(c == "desc"))
        self.res.grid(row=5, column=0, sticky="nsew")
        ttk.Button(f, text="Install selected (with required dependencies)",
                   command=self.install).grid(row=6, column=0, sticky="ew", ipady=3, pady=6)
        self.msg = ttk.Label(f, text="")
        self.msg.grid(row=7, column=0, sticky="w")
        self.reload_mods()

    def reload_mods(self):
        self.inst_tree.delete(*self.inst_tree.get_children())
        if self.mods_dir.exists():
            for p in sorted(self.mods_dir.iterdir()):
                if p.name.endswith(".jar"):
                    self.inst_tree.insert("", "end", iid=p.name, values=(p.name, "enabled"))
                elif p.name.endswith(".jar.disabled"):
                    self.inst_tree.insert("", "end", iid=p.name, values=(p.name[:-9], "disabled"))

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
        self.msg.configure(text="Searching...")

        def done(data):
            if not self.winfo_exists():
                return
            self.res.delete(*self.res.get_children())
            for h in data.get("hits", []):
                self.res.insert("", "end", iid=h["project_id"],
                                values=(h["title"], f"{h['downloads']:,}", h["description"]))
            self.msg.configure(text=f"{len(data.get('hits', []))} result(s) for Minecraft {self.inst['version']}.")

        self.app.bg(lambda: get_json(url), done, lambda e: self.msg.configure(text=f"Search failed: {e}"))

    def install(self):
        sel = self.res.selection()
        if not sel:
            return
        mc, installed = self.inst["version"], self.inst.setdefault("mods", {})
        self.msg.configure(text="Installing...")

        def work():
            seen, logs = set(), []
            for pid in sel:
                install_project(mc, pid, self.mods_dir, installed, logs.append, seen)
            return logs

        def done(logs):
            save_instance(self.inst)
            if self.winfo_exists():
                self.reload_mods()
                self.msg.configure(text=logs[-1] if logs else "Done.")
            for l in logs:
                self.app.log(l)

        self.app.bg(work, done, lambda e: self.msg.configure(text=f"Install failed: {e}"))


# --------------------------------------------------------------------------
# Main window
# --------------------------------------------------------------------------
class App:
    def __init__(self, root):
        self.root = root
        root.title(APP_NAME)
        root.geometry("900x640")
        root.minsize(720, 480)
        self.q = queue.Queue()
        self.cfg = load_json(CONFIG, {})
        # Only Microsoft accounts are supported; ignore anything else left in an old file.
        self.accounts = [a for a in load_json(ACCOUNTS, {}).get("accounts", []) if a.get("type") == "msa"]
        self.game_versions = []
        self.busy = False

        # toolbar
        tb = ttk.Frame(root, padding=(10, 8))
        tb.pack(fill="x")
        self.btn_launch = ttk.Button(tb, text="▶ Launch", command=self.launch)
        self.btn_launch.pack(side="left")
        for text, cmd in (("Add instance", self.add_instance), ("Edit / Mods", self.edit_instance),
                          ("Folder", self.open_instance), ("Delete", self.delete_instance)):
            ttk.Button(tb, text=text, command=cmd).pack(side="left", padx=(6, 0))
        ttk.Button(tb, text="Accounts", command=lambda: AccountsDialog(self)).pack(side="right")
        self.acct_var = tk.StringVar()
        self.acct_box = ttk.Combobox(tb, textvariable=self.acct_var, state="readonly", width=28)
        self.acct_box.pack(side="right", padx=8)
        self.acct_box.bind("<<ComboboxSelected>>", self.acct_changed)

        # instance list
        mid = ttk.Frame(root, padding=(10, 0))
        mid.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(mid, columns=("name", "mc", "loader", "mods"), show="headings", height=8)
        for c, t, w in (("name", "Instance", 300), ("mc", "Minecraft", 110), ("loader", "Loader", 90), ("mods", "Mods", 70)):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, stretch=(c == "name"))
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", lambda _e: self.launch())

        # progress + console
        self.bar = ttk.Progressbar(root, mode="determinate")
        self.bar.pack(fill="x", padx=10, pady=(8, 0))
        self.status = ttk.Label(root, text="Ready")
        self.status.pack(anchor="w", padx=10)
        lf = ttk.Frame(root, padding=(10, 4, 10, 10))
        lf.pack(fill="both", expand=True)
        self.logbox = tk.Text(lf, height=9, state="disabled", wrap="word")
        sb = ttk.Scrollbar(lf, command=self.logbox.yview)
        self.logbox.configure(yscrollcommand=sb.set)
        self.logbox.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        self.log(f"{APP_NAME} {APP_VERSION} - not an official Minecraft product; not affiliated with Mojang or Microsoft.")
        self.log(f"Data folder: {ROOT}")
        self.refresh_accounts()
        self.refresh_instances()
        if not self.accounts:
            self.log("No account yet. Click Accounts and sign in with the Microsoft account that owns Minecraft.")
        self.bg(lambda: [(v["version"], v["stable"]) for v in get_json(f"{FABRIC_META}/versions/game")],
                self.set_versions, lambda e: self.log(f"Could not load version list: {e}"))
        root.after(100, self.poll)

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

    def poll(self):
        try:
            while True:
                msg = self.q.get_nowait()
                kind = msg[0]
                if kind == "log":
                    self.logbox.configure(state="normal")
                    self.logbox.insert("end", msg[1] + "\n")
                    self.logbox.see("end")
                    self.logbox.configure(state="disabled")
                elif kind == "progress":
                    _, d, t, label = msg
                    self.bar.configure(maximum=t, value=d)
                    self.status.configure(text=f"{label}: {d}/{t}")
                elif kind == "busy":
                    self.busy = msg[1]
                    self.btn_launch.configure(state="disabled" if msg[1] else "normal")
                    if not msg[1]:
                        self.status.configure(text="Ready")
                        self.bar.configure(value=0)
                elif kind == "error":
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
        self.acct_box.configure(values=[acct_label(a) for a in self.accounts])
        cur = self.current_account()
        self.acct_var.set(acct_label(cur) if cur else "Not signed in")

    def acct_changed(self, _e=None):
        i = self.acct_box.current()
        if 0 <= i < len(self.accounts):
            self.cfg["account"] = acct_key(self.accounts[i])
            self.save_cfg()

    def add_account(self, acct):
        self.accounts = [a for a in self.accounts if acct_key(a) != acct_key(acct)] + [acct]
        self.cfg["account"] = acct_key(acct)
        self.save_cfg()
        self.save_accounts()
        self.refresh_accounts()

    def fresh_account(self, acct):
        """Refresh an expiring Microsoft token (runs on a worker thread)."""
        if time.time() < acct.get("expires_at", 0) - 300:
            return acct
        auth = MSAuth()
        new = auth.minecraft_account(auth.refresh(acct["refresh_token"]))
        self.accounts = [new if acct_key(a) == acct_key(acct) else a for a in self.accounts]
        self.save_accounts()
        return new

    # ---- instances
    def refresh_instances(self, select=None):
        keep = select or (self.tree.selection()[0] if self.tree.selection() else None)
        self.tree.delete(*self.tree.get_children())
        for i in list_instances():
            self.tree.insert("", "end", iid=i["id"],
                             values=(i["name"], i["version"], "Fabric", len(i.get("mods", {}))))
        if keep and self.tree.exists(keep):
            self.tree.selection_set(keep)

    def selected_instance(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Instance", "Select an instance first (or add one).")
            return None
        return load_json(INSTANCES / sel[0] / "instance.json", None)

    def add_instance(self):
        if not self.game_versions:
            messagebox.showinfo("Please wait", "Still loading the version list...")
            return
        AddInstanceDialog(self)

    def edit_instance(self):
        inst = self.selected_instance()
        if inst:
            EditInstanceDialog(self, inst)

    def open_instance(self):
        inst = self.selected_instance()
        if inst:
            open_path(game_dir_of(inst))

    def delete_instance(self):
        inst = self.selected_instance()
        if inst and messagebox.askyesno("Delete", f"Delete '{inst['name']}' and all its worlds/mods?"):
            shutil.rmtree(INSTANCES / inst["id"], ignore_errors=True)
            self.refresh_instances()

    # ---- launching
    def launch(self):
        if self.busy:
            return
        inst = self.selected_instance()
        if not inst:
            return
        acct = self.current_account()
        if not acct:
            messagebox.showinfo("Sign in", "Sign in with the Microsoft account that owns Minecraft first.")
            AccountsDialog(self)
            return
        self.q.put(("busy", True))
        threading.Thread(target=self.worker, args=(inst, acct), daemon=True).start()

    def worker(self, inst, acct):
        try:
            acct = self.fresh_account(acct)
            cmd, game_dir = Core(self.log, self.progress).prepare(inst, acct)
            save_instance(inst)
            self.log(f"Launching as {acct['username']}...")
            proc = subprocess.Popen(cmd, cwd=str(game_dir), stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, errors="replace",
                                    creationflags=NOWIN)
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
