# Vault sync: server writes, GitHub carries, Mac reads

The bot runs on a server and writes notes there. Your Obsidian is on a Mac.
`vault/` is therefore its own **private** git repo, separate from this public
code repo (which gitignores it).

    server: bot saves a note → vault_sync.sh push → github.com/<you>/vault (private)
    mac:    every 5 min vault_sync.sh pull → the clone inside your Obsidian vault

Every version of every note is kept. A reprocess or a bad edit is one
`git log` away from undo.

## Server (once)

    gh repo create saved-to-notes-vault --private
    ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519_vault      # on the server
    gh repo deploy-key add ~/.ssh/id_ed25519_vault.pub --allow-write -R <you>/saved-to-notes-vault
    cd ~/saved-to-notes/vault && git init -b main && git remote add origin git@github.com:<you>/saved-to-notes-vault.git
    git add -A && git commit -m "Initial vault" && git push -u origin main
    echo VAULT_SYNC=1 >> ~/saved-to-notes/.env && ./deploy/install-linux.sh

A deploy key is scoped to that one repo, which is why it is used instead of
your personal key.

## Mac (once)

    git clone https://github.com/<you>/saved-to-notes-vault.git "<your Obsidian vault>/Saved to Notes"
    cd <this checkout> && mv vault vault.backup && ln -s "<your Obsidian vault>/Saved to Notes" vault
    ./install-mac-reader.sh

Obsidian sees the folder like any other and picks up new files as they land.
Edits you make on the Mac are committed and pushed by the same job; the
server rebases on them before its next push. Conflicts are rare by
construction — the server only adds files or rewrites ones it wrote — and a
conflicted pull is logged in `logs/vault_sync.log` and retried, never forced.

Don't put the clone inside iCloud Drive: iCloud and git fight over the same
files, and iCloud can't reach a Linux server anyway.
