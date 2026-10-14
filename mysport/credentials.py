"""
Zugangsdatenverwaltung für MY.SPORT (my.sport.uni-bonn.de).

Getrennt vom Buchungscode: Der Bot fragt hier nur nach `get_credentials()`,
`load_session()` und `save_session()` und weiß nicht, wo oder wie die Daten
liegen.

Quellen für Login-Daten (erste Fundstelle gewinnt):
  1. Secret-Dateien  – systemd `LoadCredential=` ($CREDENTIALS_DIRECTORY)
                       oder Docker/Podman-Secrets (/run/secrets)
                       Dateinamen: mysport_email, mysport_password
                       (Profil ≠ "default": mysport_<profil>_email, ...)
  2. Verschlüsselter Tresor  <DATA_DIR>/vault.enc  (Fernet = AES-128-CBC + HMAC)

Sitzungen (Cookies inkl. "Angemeldet bleiben") liegen getrennt verschlüsselt in
<DATA_DIR>/sessions/<profil>.enc, damit häufiges Speichern den Tresor nie
anfasst.

Der Schlüssel wird gesucht in:
  $MYSPORT_KEY_FILE, $CREDENTIALS_DIRECTORY/mysport_key, /run/secrets/mysport_key,
  zuletzt <DATA_DIR>/key (wird bei `init` erzeugt).
"""

import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

DEFAULT_PROFILE = "default"
KEY_NAME = "mysport_key"
SECRET_DIRS_ENV = "CREDENTIALS_DIRECTORY"  # gesetzt von systemd LoadCredential=
DOCKER_SECRETS_DIR = Path("/run/secrets")
PROFILE_RE = re.compile(r"^[a-z0-9_-]{1,32}$")


class CredentialError(Exception):
    """Zugangsdaten fehlen, Schlüssel falsch oder Datei beschädigt."""


@dataclass(frozen=True)
class Credentials:
    email: str
    password: str

    def __repr__(self):
        # Passwort darf nie in Logs oder Tracebacks landen
        return f"Credentials(email={self.email!r}, password='***')"

    __str__ = __repr__


# --- Pfade ---


def data_dir() -> Path:
    return Path(os.environ.get("MYSPORT_DATA_DIR", "data"))


def _secret_dirs():
    dirs = []
    if os.environ.get(SECRET_DIRS_ENV):
        dirs.append(Path(os.environ[SECRET_DIRS_ENV]))
    dirs.append(DOCKER_SECRETS_DIR)
    return dirs


def _in_secret_dir(path: Path) -> bool:
    """Secret-Verzeichnisse verwaltet systemd/Docker, dort nichts schreiben oder bemängeln."""
    return any(path.parent == d for d in _secret_dirs())


def key_path(for_create: bool = False) -> Path:
    """Pfad des Schlüssels. Bei for_create=True das Ziel für einen neuen Schlüssel."""
    if os.environ.get("MYSPORT_KEY_FILE"):
        return Path(os.environ["MYSPORT_KEY_FILE"])
    if not for_create:
        for d in _secret_dirs():
            if (d / KEY_NAME).is_file():
                return d / KEY_NAME
    return data_dir() / "key"


def _check_profile(profile: str) -> str:
    if not PROFILE_RE.match(profile):
        raise CredentialError(
            f"Ungültiger Profilname {profile!r} (erlaubt: a-z, 0-9, _ und -, max. 32 Zeichen)"
        )
    return profile


# --- Dateizugriff ---


def _write_private(path: Path, data: bytes):
    """Atomar schreiben mit Rechten 0600, damit nie eine halbe Datei entsteht."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _warn_if_world_readable(path: Path):
    try:
        mode = path.stat().st_mode
    except OSError:
        return
    if mode & 0o077 and not _in_secret_dir(path):
        print(f"Warnung: {path} ist für andere lesbar – bitte `chmod 600 {path}`.")


# --- Schlüssel ---


def init_key() -> Path:
    """Erzeugt einen neuen Schlüssel, falls noch keiner existiert."""
    existing = key_path()
    if existing.is_file():
        return existing
    path = key_path(for_create=True)
    _write_private(path, Fernet.generate_key() + b"\n")
    return path


def _fernet(path: Path = None) -> Fernet:
    path = path or key_path()
    if not path.is_file():
        raise CredentialError(
            f"Kein Schlüssel gefunden ({path}). Zuerst `python -m mysport.credentials init` ausführen."
        )
    _warn_if_world_readable(path)
    try:
        return Fernet(path.read_bytes().strip())
    except ValueError as e:
        raise CredentialError(f"Schlüsseldatei {path} ist ungültig") from e


def _decrypt_json(path: Path, fernet: Fernet):
    try:
        return json.loads(fernet.decrypt(path.read_bytes()))
    except InvalidToken as e:
        raise CredentialError(
            f"{path} lässt sich nicht entschlüsseln – falscher Schlüssel oder Datei beschädigt"
        ) from e


def _encrypt_json(path: Path, obj, fernet: Fernet):
    _write_private(path, fernet.encrypt(json.dumps(obj).encode()))


# --- Tresor (Login-Daten) ---


def _vault_path() -> Path:
    return data_dir() / "vault.enc"


def _read_vault(fernet: Fernet) -> dict:
    path = _vault_path()
    if not path.is_file():
        return {"version": 1, "profiles": {}}
    return _decrypt_json(path, fernet)


def set_credentials(email: str, password: str, profile: str = DEFAULT_PROFILE):
    _check_profile(profile)
    if not email or "@" not in email:
        raise CredentialError("E-Mail-Adresse fehlt oder ist ungültig")
    if not password:
        raise CredentialError("Passwort darf nicht leer sein")
    fernet = _fernet()
    vault = _read_vault(fernet)
    vault["profiles"][profile] = {"email": email.strip(), "password": password}
    _encrypt_json(_vault_path(), vault, fernet)


def delete_credentials(profile: str = DEFAULT_PROFILE) -> bool:
    """Löscht Login-Daten und gespeicherte Sitzung eines Profils."""
    _check_profile(profile)
    fernet = _fernet()
    vault = _read_vault(fernet)
    found = vault["profiles"].pop(profile, None) is not None
    if found:
        _encrypt_json(_vault_path(), vault, fernet)
    clear_session(profile)
    return found


def list_profiles() -> list:
    if not _vault_path().is_file():
        return []
    return sorted(_read_vault(_fernet())["profiles"])


def _from_secret_files(profile: str):
    prefix = "mysport" if profile == DEFAULT_PROFILE else f"mysport_{profile}"
    for d in _secret_dirs():
        email_f, pw_f = d / f"{prefix}_email", d / f"{prefix}_password"
        if email_f.is_file() and pw_f.is_file():
            return Credentials(
                email=email_f.read_text().strip(),
                password=pw_f.read_text().rstrip("\r\n"),
            ), d
    return None, None


def get_credentials(profile: str = DEFAULT_PROFILE) -> Credentials:
    _check_profile(profile)
    creds, _ = _from_secret_files(profile)
    if creds:
        return creds
    if _vault_path().is_file():
        entry = _read_vault(_fernet())["profiles"].get(profile)
        if entry:
            return Credentials(entry["email"], entry["password"])
    raise CredentialError(
        f"Keine Zugangsdaten für Profil {profile!r}. "
        f"`python -m mysport.credentials set --profile {profile}` ausführen."
    )


def credentials_source(profile: str = DEFAULT_PROFILE) -> str:
    """Woher die Login-Daten kommen würden (für `show`), ohne sie auszugeben."""
    _, d = _from_secret_files(profile)
    if d:
        return f"Secret-Dateien in {d}"
    return f"Tresor {_vault_path()}"


def rotate_key() -> Path:
    """Neuer Schlüssel, Tresor und alle Sitzungen werden neu verschlüsselt."""
    path = key_path()
    old = _fernet(path)
    if _in_secret_dir(path):
        raise CredentialError(
            f"Schlüssel kommt aus {path.parent} (schreibgeschützt). Dort extern austauschen."
        )
    new_key = Fernet.generate_key()
    new = Fernet(new_key)
    files = [_vault_path()] + sorted((data_dir() / "sessions").glob("*.enc"))
    plain = {f: _decrypt_json(f, old) for f in files if f.is_file()}
    # Erst alles neu verschlüsseln, dann den Schlüssel tauschen.
    # Bricht es dazwischen ab, liegt der alte Schlüssel als key.old daneben.
    _write_private(path.with_name(path.name + ".old"), path.read_bytes())
    for f, obj in plain.items():
        _encrypt_json(f, obj, new)
    _write_private(path, new_key + b"\n")
    path.with_name(path.name + ".old").unlink()
    return path


# --- Sitzungen (Cookies / Playwright storage_state) ---


def _session_path(profile: str) -> Path:
    return data_dir() / "sessions" / f"{_check_profile(profile)}.enc"


def save_session(state: dict, profile: str = DEFAULT_PROFILE):
    _encrypt_json(_session_path(profile), state, _fernet())


def load_session(profile: str = DEFAULT_PROFILE):
    """Gespeicherte Sitzung oder None. Eine unlesbare Sitzung gilt als abgelaufen."""
    path = _session_path(profile)
    if not path.is_file():
        return None
    fernet = _fernet()
    try:
        return _decrypt_json(path, fernet)
    except CredentialError:
        return None


def clear_session(profile: str = DEFAULT_PROFILE):
    _session_path(profile).unlink(missing_ok=True)


# --- CLI: python -m mysport.credentials <befehl> ---


def _mask(email: str) -> str:
    name, _, domain = email.partition("@")
    return f"{name[:2]}***@{domain}"


def main(argv=None):
    import argparse
    import getpass
    import sys

    parser = argparse.ArgumentParser(
        prog="python -m mysport.credentials",
        description="Zugangsdaten für MY.SPORT sicher verwalten.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init", help="Schlüssel erzeugen (einmalig)")
    p_set = sub.add_parser("set", help="E-Mail und Passwort speichern/ändern")
    p_set.add_argument("--email", help="sonst interaktive Abfrage")
    p_set.add_argument(
        "--password-stdin", action="store_true",
        help="Passwort von stdin lesen (für Skripte), nie als Argument übergeben",
    )
    sub.add_parser("show", help="Gespeicherte Profile anzeigen (ohne Passwort)")
    sub.add_parser("delete", help="Profil samt Sitzung löschen")
    sub.add_parser("logout", help="Nur gespeicherte Sitzung löschen")
    sub.add_parser("rotate-key", help="Neuen Schlüssel erzeugen und alles neu verschlüsseln")
    for p in sub.choices.values():
        p.add_argument("--profile", default=DEFAULT_PROFILE)
    args = parser.parse_args(argv)

    try:
        if args.cmd == "init":
            print(f"Schlüssel: {init_key()}")
            print("Diese Datei sichern! Ohne sie sind Tresor und Sitzungen nicht lesbar.")
        elif args.cmd == "set":
            email = args.email or input("E-Mail: ")
            if args.password_stdin:
                password = sys.stdin.readline().rstrip("\r\n")
            else:
                password = getpass.getpass("Passwort: ")
                if password != getpass.getpass("Passwort wiederholen: "):
                    raise CredentialError("Passwörter stimmen nicht überein")
            set_credentials(email, password, args.profile)
            clear_session(args.profile)  # alte Sitzung gehört evtl. zu anderem Konto
            print(f"Gespeichert für Profil {args.profile!r}.")
        elif args.cmd == "show":
            for name in sorted(set(list_profiles()) | {args.profile}):
                try:
                    c = get_credentials(name)
                except CredentialError:
                    continue
                session = "ja" if _session_path(name).is_file() else "nein"
                print(f"{name}: {_mask(c.email)}  Quelle: {credentials_source(name)}  Sitzung: {session}")
        elif args.cmd == "delete":
            found = delete_credentials(args.profile)
            print("Gelöscht." if found else f"Profil {args.profile!r} nicht im Tresor.")
        elif args.cmd == "logout":
            clear_session(args.profile)
            print("Sitzung gelöscht.")
        elif args.cmd == "rotate-key":
            print(f"Neuer Schlüssel: {rotate_key()}")
    except CredentialError as e:
        sys.exit(f"Fehler: {e}")


if __name__ == "__main__":
    main()
