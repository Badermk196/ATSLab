# Go live: the ATS Lab on a real domain

This is the step-by-step for running the app 24/7 on a server with your own address (for example
`https://app.1000jobs.club`), instead of this Windows computer. The files it uses are in `deploy\`:
`docker-compose.yml`, `Caddyfile`, `.env.example`.

**What you need before you start**

| Thing | Where it comes from |
|---|---|
| A server with Docker, always on | a Manus Cloud Computer ($10/month Basic) or your own VPS. The app needs about 1.5 GB of disk for the image and 1 GB of memory to run comfortably |
| The domain / subdomain | your own domain. One DNS record: an **A record** to the server's IP |
| The AI key | your OpenRouter key (`OPENROUTER_API_KEY`) |
| Admin accounts | one name + long password per team member |

**The free alternatives first, honestly:** Streamlit Community Cloud is free and takes 10 minutes
(`https://share.streamlit.io`, main file `app.py`, secrets in the box) and you get
`https://your-app.streamlit.app`. Two limits there: a custom domain is not officially supported, and the disk is
not permanent — after a restart the History and the kept resume files are **lost**. Use it for a trial; use a
server for real users.

---

## Step 1 - the server

- **Manus Cloud Computer**: https://manus.im/app#settings/my-computer/create (Basic, $10/month; Ubuntu Server).
  If you already own a cloud computer, attach it with the computer icon under the chat box instead of buying one.
- **Your own VPS** (if 1000jobs.club already runs somewhere with root/Docker, use it: no extra cost).

The tiers, for reference: Basic = 2 vCPU / 1 GB RAM / 35 GB / 200 GB out ($10), Standard = 2 vCPU / 4 GB / 70 GB /
500 GB out ($30). On Basic, do Step 4 (swap) before the build.

## Step 2 - the code on the server

From this computer, the app is in `C:\ATSLab`. Two ways:

- **A zip** (simple): zip the folder without `data\`, `cv_reviews\`, `dashboard_jobs\`, `release-*\` and
  `.streamlit\secrets.toml` (the `.gitignore` list is exactly this), copy it to the server, then:
  ```
  mkdir -p ~/atslab && cd ~/atslab && unzip atslab.zip
  ```
- **A private GitHub repository**: push the code (the secrets and the data folders are already ignored), then
  `git clone <your-repo> ~/atslab` on the server.

## Step 3 - open the ports

Only 80 and 443 must be open to the world. Port 8501 is used inside Docker only.

```
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw status
```

If Docker is not installed yet: `curl -fsSL https://get.docker.com | sudo sh`, then `sudo usermod -aG docker $USER`
and log in again (or just put `sudo` in front of every `docker` command below).

## Step 4 - swap (only on the 1 GB Basic plan)

The first build installs PyTorch and a language model; 1 GB of memory is tight for that. 2 GB of swap makes it safe:

```
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
free -h
```

## Step 5 - the secrets

```
cd ~/atslab/deploy
cp .env.example .env
nano .env
```

Fill in: `DOMAIN` (your subdomain), `EMAIL`, `OPENROUTER_API_KEY`, `ATSLAB_ADMINS`, and the links
(`ATSLAB_BOOKING_URL` = your calendar link, `ATSLAB_PREMIUM_URL`, `ATSLAB_SITE_URL`). Save with Ctrl+O, Enter,
then Ctrl+X. `.env` holds real secrets: never commit it, never send it in a chat.

## Step 6 - start it

```
cd ~/atslab/deploy
sudo docker compose up -d --build          # the first build takes 5-15 minutes
sudo docker compose ps                     # both containers should be "running" / "healthy"
sudo docker compose logs -f app            # watch it start (Ctrl+C to stop watching)
```

## Step 7 - point the domain at the server

1. Copy the server's public IP (Cloud Computer: the management page, "SSH access").
2. At your DNS provider add: **A record**, name `app` (or `atslab`), value the IP, TTL 1 hour.
3. If the domain is on **Cloudflare**: keep this record on **DNS only (grey cloud)**. With the orange cloud on,
   every visitor looks like the same address to the app and the "free checks a day" limit would count everybody as
   one person.

Wait 5-30 minutes for the DNS to spread, then Caddy gets the certificate by itself.

## Step 8 - test it

```
curl -I https://app.1000jobs.club/user        # expect "HTTP/2 200"
```

Then in a browser: `https://app.1000jobs.club/user` (this is the only link to share with job seekers) and
`https://app.1000jobs.club/admin` (the team, name + password). Upload one resume and check the score, then look at
History on the Admin page.

## Step 9 - the links on the user page

Admin page -> **Settings**: paste the "Get Premium" link, the **calendar** link for "Book a resume session", the
"Go to 1000Jobs" link, the free checks a day, how many days the resume files are kept, and the "Needs review"
rules. A saved value wins over `.env` (no restart needed).

## Step 10 - the second day

| Job | Command |
|---|---|
| Look at the log | `sudo docker compose logs -f app` |
| Restart the app | `sudo docker compose restart app` |
| Stop everything | `sudo docker compose down` |
| After a code change | copy the new code, then `sudo docker compose up -d --build` |
| Backup the data (history + resume files) | `sudo docker run --rm -v deploy_atslab-data:/data -v ~:/backup alpine tar czf /backup/atslab-data-$(date +%F).tgz -C /data .` |
| A clean start (empty History and files, settings kept) | `sudo docker compose exec app python reset_data.py --yes` |

A Manus Cloud Computer also takes a daily full-disk snapshot by itself (10 kept) from its management page.

## What is already handled for you

- HTTPS and its renewal (Caddy), WebSockets (Streamlit needs them), gzip, and the `X-Forwarded-For` header the app
  uses to count the free checks per person.
- Everything the app needs to read PDFs and print the reports (Chromium and the fonts are inside the image).
- The app starts again by itself after a reboot or a crash (`restart: unless-stopped`).
- The history and the kept resumes live in the `atslab-data` volume, so a rebuild never loses them.
- The Admin page needs a name + password (checked on the server, with a one-minute lock after 5 wrong tries). If you
  want a second lock in front of `/admin` (for example a fixed list of office IP addresses), ask: it needs care
  because of Streamlit's WebSocket, and a half-working lock would be worse than none.
- Uploads are refused above 10 MB (`.streamlit/config.toml`), and the user page shows the privacy note with the
  number of days from the settings.
