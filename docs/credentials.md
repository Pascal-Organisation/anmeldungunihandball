# Zugangsdaten verwalten

Seit dem Umzug auf **my.sport.uni-bonn.de** braucht jede Buchung einen Login
(E-Mail + Passwort). `mysport/credentials.py` kümmert sich ausschließlich darum,
diese Daten und die Login-Sitzung sicher abzulegen – getrennt vom Buchungscode.

## Was wo liegt

| Datei | Inhalt | Schutz |
|---|---|---|
| `key` | Hauptschlüssel (Fernet) | `0600`, idealerweise außerhalb von `data/` |
| `data/vault.enc` | E-Mail + Passwort je Profil | verschlüsselt mit `key` |
| `data/sessions/<profil>.enc` | Cookies der Sitzung (inkl. „Angemeldet bleiben“) | verschlüsselt mit `key` |

Der Bot nutzt im Alltag nur die **Sitzung**. Das Passwort wird nur gebraucht,
wenn die Sitzung abgelaufen ist und neu eingeloggt werden muss.

**Wichtig:** Die Sitzungsdatei ist so viel wert wie das Passwort – wer sie hat,
ist eingeloggt. Deshalb ist sie genauso verschlüsselt.

Wer `key` **und** `data/` besitzt, kann alles lesen. Die Verschlüsselung schützt
vor Backups/Snapshots, Nextcloud-Sync oder versehentlichem Commit von `data/` –
nicht vor jemandem mit root im Container. Daher den Schlüssel getrennt ablegen
(siehe unten).

## Bedienung

```bash
pip install -r requirements.txt

python -m mysport.credentials init         # Schlüssel erzeugen (einmalig)
python -m mysport.credentials set          # E-Mail + Passwort (verdeckte Eingabe)
python -m mysport.credentials show         # Profile, Quelle, Sitzung ja/nein – nie das Passwort
python -m mysport.credentials logout       # nur Sitzung löschen → nächster Lauf loggt neu ein
python -m mysport.credentials delete       # Profil + Sitzung löschen
python -m mysport.credentials rotate-key   # neuer Schlüssel, alles wird neu verschlüsselt
```

Mehrere Konten (z. B. für Freunde): `--profile anna` an jeden Befehl hängen.

Das Passwort wird nie als Kommandozeilen-Argument übergeben (sonst steht es in
`ps` und der Shell-History). Für Skripte: `--password-stdin`.

### Im Code

```python
from mysport.credentials import get_credentials, load_session, save_session

creds = get_credentials()          # Credentials(email=..., password='***')
state = load_session()             # dict oder None
save_session(new_state)
```

## Konfiguration über Umgebungsvariablen

| Variable | Standard | Zweck |
|---|---|---|
| `MYSPORT_DATA_DIR` | `./data` | Ort für Tresor und Sitzungen |
| `MYSPORT_KEY_FILE` | – | fester Pfad zum Schlüssel |
| `CREDENTIALS_DIRECTORY` | von systemd gesetzt | Secret-Dateien (siehe LXC) |

Reihenfolge der Schlüsselsuche: `MYSPORT_KEY_FILE` →
`$CREDENTIALS_DIRECTORY/mysport_key` → `/run/secrets/mysport_key` → `data/key`.

Login-Daten als Dateien (`mysport_email`, `mysport_password`) in
`$CREDENTIALS_DIRECTORY` oder `/run/secrets` haben Vorrang vor dem Tresor.

## Betrieb auf Proxmox

### Empfohlen: natives Python im unprivilegierten LXC (Debian 13)

Ohne Docker-in-LXC (braucht `nesting=1` und macht bei unprivilegierten CTs
gerne Ärger). systemd liefert den Schlüssel als Credential, er liegt
verschlüsselt auf der Platte des CT und taucht nie im Bot-Verzeichnis auf.

```bash
# im CT als root
adduser --system --group --home /opt/mysport mysport
# Code nach /opt/mysport, venv anlegen, pip install -r requirements.txt

# Schlüssel erzeugen und mit systemd-creds verschlüsseln
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" \
  | systemd-creds encrypt --name=mysport_key - /etc/credstore.encrypted/mysport_key
```

`/etc/systemd/system/mysport.service`:

```ini
[Service]
User=mysport
WorkingDirectory=/opt/mysport
Environment=MYSPORT_DATA_DIR=/var/lib/mysport
StateDirectory=mysport
StateDirectoryMode=0700
LoadCredentialEncrypted=mysport_key
# Einstiegspunkt des Bots – folgt in der nächsten Phase
ExecStart=/opt/mysport/venv/bin/python -m mysport
# Härtung
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
```

Zugangsdaten einmalig im Kontext des Dienstes speichern:

```bash
systemd-run --pty --wait --collect -p User=mysport \
  -p LoadCredentialEncrypted=mysport_key -p Environment=MYSPORT_DATA_DIR=/var/lib/mysport \
  -p WorkingDirectory=/opt/mysport /opt/mysport/venv/bin/python -m mysport.credentials set
```

Hinweis: Ohne TPM im CT verschlüsselt `systemd-creds` mit
`/var/lib/systemd/credential.secret` des CT. Proxmox-Backups (vzdump) des CT
enthalten also beides – Backup-Speicher entsprechend schützen oder den
Schlüssel zusätzlich offline sichern.

### Alternative: Docker im LXC

Im CT `nesting=1` (und ggf. `keyctl=1`) aktivieren, dann:

```yaml
services:
  mysport:
    build: .
    environment:
      TZ: Europe/Berlin
      MYSPORT_DATA_DIR: /data
    volumes:
      - ./data:/data
    secrets: [mysport_key]
secrets:
  mysport_key:
    file: ./secrets/mysport_key   # chmod 600, NICHT im Repo
```

Danach `docker compose run --rm mysport python -m mysport.credentials set`.
