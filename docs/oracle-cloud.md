# Hosting the room on Oracle Cloud (free)

The panel is light (Python, no database), so an Always Free machine on Oracle Cloud is enough, and
the room stays up without your PC on. Tailscale Funnel keeps working the same way: the server
connects out to Tailscale, so no port has to be opened.

If the room already runs on your PC, you can keep **the same address**: friends keep their link,
nobody signs in again, and Spotify's Redirect URI doesn't change.

## 1. A key to reach the server (on your PC)

```powershell
ssh-keygen -t ed25519 -f $env:USERPROFILE\.ssh\sala-oracle -C sala-de-escuta
Get-Content $env:USERPROFILE\.ssh\sala-oracle.pub   # paste this in step 2
```

## 2. The machine (Oracle Cloud console)

1. Pick your home region when creating the account (it can't be changed later).
2. ☰ → Compute → Instances → **Create instance**. Name: `sala`.
3. **Image**: Canonical Ubuntu 24.04.
4. **Shape**: Ampere `VM.Standard.A1.Flex` with 1 OCPU and 6 GB. If creating fails with
   "Out of capacity", use `VM.Standard.E2.1.Micro` (AMD) instead. Both are marked *Always Free-eligible*.
5. **Networking**: the defaults (a new network with a public IPv4 address).
6. **SSH keys**: *Paste public keys* and paste the line from step 1.
7. Create, wait for *Running*, and copy the **Public IP address**.

Oracle may reclaim Always Free machines that sit idle for a week, and this panel is mostly idle.
Upgrading the account to *Pay As You Go* (Billing) avoids that; Always Free resources stay free.
If you upgrade, set a budget alert (Billing → Budgets) so nothing paid goes unnoticed.

## 3. Install

```powershell
ssh -i $env:USERPROFILE\.ssh\sala-oracle ubuntu@<public-ip>
```

On the server:

```bash
curl -fsSL https://raw.githubusercontent.com/NejDev/sala-de-escuta/main/scripts/install-linux.sh | bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up          # open the link it prints and approve the machine
```

## 4. Move the room (about 10 minutes offline)

On the PC, stop the panel for good (two panels with the same accounts would fight over the tokens),
turn its Funnel off and copy the room to the server:

```powershell
Stop-ScheduledTask -TaskName 'Sala de escuta - painel'
Disable-ScheduledTask -TaskName 'Sala de escuta - painel'
tailscale funnel reset
cd <folder of the room>
scp -i $env:USERPROFILE\.ssh\sala-oracle -r data .env playlists.json ubuntu@<public-ip>:~/sala-de-escuta/
```

To keep the address, swap the names in the Tailscale admin (Machines → ⋯ → *Edit machine name*):
first rename the PC (for example `pc-home`), then give the server the PC's old name. On the server:

```bash
sudo systemctl start sala-de-escuta
sudo tailscale funnel --bg 8888
tailscale funnel status    # the address, which must match SALA_PUBLIC_URL in .env
```

If you chose a new address instead, set `SALA_PUBLIC_URL` in `~/sala-de-escuta/.env`, add
`<address>/callback` to the Redirect URIs of the Spotify app, and run `sudo systemctl restart sala-de-escuta`.

## Day to day

```bash
bash ~/sala-de-escuta/scripts/install-linux.sh     # update to the latest version and restart
sudo systemctl status sala-de-escuta               # is it running?
tail -f ~/sala-de-escuta/data/assistant.log        # what it is doing
```

To go back to the PC: stop the service on the server (`sudo systemctl disable --now sala-de-escuta`
and `sudo tailscale funnel reset`), copy `data/` back, swap the machine names again, and on the PC
run `Enable-ScheduledTask` / `Start-ScheduledTask` and `tailscale funnel --bg 8888`.
