# 1000Jobs ATS Lab on a Manus Cloud Computer

This is the short runbook: spin up the machine, copy one file, run one command.
Everything else is already prepared.

---

## What you need first

| Item | Where | Notes |
|---|---|---|
| A Manus Cloud Computer | https://manus.im/app#settings/my-computer/create | **Standard ($30/month, 4 GB RAM)** is the right size. Basic (1 GB) is too small: torch plus the meaning-match model needs about 1.5 GB at load. |
| The upload file | `deploy\cloud\atslab-deploy.tar.gz` | Built by `package.ps1` (see step 1). |
| Two settings | your OpenRouter key and the admin name + password | They go into `.env` on the server. |

The app does not need a GPU. Any tier works on CPU, but it needs memory.

---

## Step 1 - build the upload file (on this PC, once)

```powershell
cd C:\ATSLab
powershell -ExecutionPolicy Bypass -File deploy\cloud\package.ps1
```

It writes `deploy\cloud\atslab-deploy.tar.gz` (about 1-2 MB) with the code only: no secrets, no history, no resumes, no test data. Run it again whenever the code changes.

---

## Step 2 - spin up the machine

1. Open https://manus.im/app#settings/my-computer/create and choose **Standard**.
2. Wait for the machine to show as running, then attach it to this task (the computer icon under the chat input).
3. Note the **public IP** on the management page. You will need it in step 4.

---

## Step 3 - put the code on the machine and start it

Once the machine is attached, tell me and I run these for you. If you prefer to do it yourself over SSH:

```bash
# 1. copy the file up (from this PC; the IP and password are on the management page)
scp deploy/cloud/atslab-deploy.tar.gz ubuntu@<PUBLIC-IP>:/tmp/

# 2. on the machine
sudo mkdir -p /opt/atslab
sudo tar -xzf /tmp/atslab-deploy.tar.gz -C /opt/atslab
cd /opt/atslab/deploy/cloud

# 3. fill in the settings (two required lines)
cp .env.example .env
nano .env                 # OPENROUTER_API_KEY and ATSLAB_ADMINS

# 4. install and start
sudo bash install.sh              # direct port mode  -> http://IP:8501
```

The first build takes 5 to 15 minutes: it downloads torch and the meaning-match model into the image. After that, restarts take seconds.

---

## Step 4 - open it

| Mode | User page | Admin page |
|---|---|---|
| Direct port | `http://<PUBLIC-IP>:8501/user` | `http://<PUBLIC-IP>:8501/admin` |
| HTTPS | `https://<DOMAIN>/user` | `https://<DOMAIN>/admin` |

The admin page asks for the name and password from `ATSLAB_ADMINS`.

### HTTPS without buying a domain

`sslip.io` is a free public DNS service: `34-12-56-78.sslip.io` always resolves to `34.12.56.78`. So:

```bash
# in .env, set DOMAIN to your IP with dashes instead of dots
DOMAIN=34-12-56-78.sslip.io

sudo bash install.sh https
```

Caddy asks Let's Encrypt for the certificate on its own. The first load takes about 30 seconds while it does. This needs ports 80 and 443 open, which `install.sh` does.

If you own a domain, point an A record at the public IP and put the real name in `DOMAIN` instead. Same command.

---

## What stays running after a reboot

`install.sh` creates the systemd unit `atslab.service`, enabled at boot. So a tier upgrade, a backup restore or a manual restart brings the app back by itself. The container also has `restart: unless-stopped`.

Check it any time:

```bash
sudo systemctl status atslab
cd /opt/atslab/deploy/cloud && sudo docker compose ps
cd /opt/atslab/deploy/cloud && sudo docker compose logs -f --tail 50
```

---

## Your data lives in a Docker volume

The history database and the kept resume files are in the volume `atslab-data`, mounted at `/data` in the container. They survive restarts and image rebuilds. Back them up:

```bash
sudo docker run --rm -v atslab-data:/data -v /root:/backup alpine \
  tar -czf /backup/atslab-data-$(date +%F).tar.gz -C /data .
```

The Cloud Computer also takes a daily full-disk snapshot (10 kept). Restoring one needs a reboot.

---

## Things to know

- **Firewall.** UFW is on and only port 22 is open by default. `install.sh` opens 8501, or 80 and 443. Never expose the app without the admin password set.
- **Outbound traffic.** The plans include 200 GB (Basic), 500 GB (Standard) or 1000 GB (Advanced) a month. When the allowance runs out the machine is shut down unless auto top-up is on. Turn it on at the management page if the app will be used a lot.
- **Memory.** If checks start failing while two or three people use it at once, the machine is short of memory. Standard's 4 GB is comfortable; Basic's 1 GB is not.
- **Uploads.** The AI review and the job-keyword step call OpenRouter. Without `OPENROUTER_API_KEY` the app still scores resumes, but those two features are skipped.
- **No domain needed** for the first test. Port mode is the fastest way to see it work. Use HTTPS before sharing the link with real users: in port mode the admin password travels unencrypted.
- **The free-check limit** counts per visitor IP. Behind Caddy the real address is forwarded; in port mode it is the real address. If you later put Cloudflare in front, keep the record on "DNS only", otherwise every visitor looks like one person.

---

## Costs

| Plan | Price | Fits? |
|---|---|---|
| Basic | $10/month, 2 vCPU, 1 GB RAM | Tight. The model plus torch needs about 1.5 GB. |
| Standard | $30/month, 2 vCPU, 4 GB RAM | Recommended. |
| Advanced | $50/month, 2 vCPU, 8 GB RAM | Only if many people use it at once. |

Storage beyond the plan is $1 per 10 GB a month; outbound traffic beyond the allowance is $0.15 per GB.

---

## If something goes wrong

| Symptom | Check |
|---|---|
| The page does not load | Is the port open? `sudo ufw status`. Is the container up? `docker compose ps`. |
| "Connection refused" right after start | The image is still building. `docker compose logs -f` shows the progress. |
| The admin page rejects the password | `ATSLAB_ADMINS` in `.env` must be valid JSON: `{"Bader": "password"}`. Restart after editing. |
| The certificate does not arrive | Ports 80 and 443 must be open and the DOMAIN must match the IP. `docker compose logs caddy`. |
| The app restarts alone | Out of memory. Check `docker stats` and consider the next tier. |
