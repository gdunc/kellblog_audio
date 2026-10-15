# Cloudflare R2 setup for `kellblog.thisisgrant.com`

Podcast feed URL: `https://kellblog.thisisgrant.com/feed.xml`

Account detected via Wrangler (gdunc718@gmail.com):

- **Account name:** This Is Grant Website
- **Account ID:** `<your-cloudflare-account-id>`

## Current blockers (as of setup)

1. **R2 is not enabled** on this account yet (API error `10042`).
2. **`thisisgrant.com` is not on Cloudflare** — DNS is at DreamHost (`ns1–3.dreamhost.com`). Only `praxisawards.com` is in the account today.
3. R2 custom domains require the **parent zone** (`thisisgrant.com`) on the **same** Cloudflare account as the bucket.

---

## Step 1: Log into Cloudflare Dashboard

1. Open [Cloudflare Dashboard](https://dash.cloudflare.com/).
2. Sign in (Wrangler CLI login is separate from the browser session).

---

## Step 2: Enable R2 (one-time)

1. Select account **This Is Grant Website**.
2. Left sidebar → **R2 Object Storage**.
3. If prompted, click **Purchase R2** / **Enable R2** (free tier: 10 GB storage, no egress fees).
4. Wait until the R2 overview loads.

CLI check after enabling:

```bash
npx wrangler r2 bucket list
```

---

## Step 3: Add `thisisgrant.com` to Cloudflare

1. Dashboard → **Add a site** → enter `thisisgrant.com` → continue.
2. Pick **Free** plan (sufficient for R2 + DNS).
3. Cloudflare scans existing DNS records — review and import.
4. Cloudflare gives you two nameservers, e.g. `ada.ns.cloudflare.com` and `bob.ns.cloudflare.com`.

### Update nameservers at DreamHost

1. Log into [DreamHost panel](https://panel.dreamhost.com/).
2. **Domains** → **Registrations** → **thisisgrant.com** → **DNS** / nameservers.
3. Replace DreamHost nameservers with Cloudflare’s two nameservers.
4. Save. Propagation can take up to 24–48 hours (often faster).

### Get zone ID (after zone is active)

Dashboard → **thisisgrant.com** → right sidebar **Zone ID**, or:

```bash
# After zone exists in account
curl -s "https://api.cloudflare.com/client/v4/zones?name=thisisgrant.com" \
  -H "Authorization: Bearer <API_TOKEN>" | jq '.result[0].id'
```

---

## Step 4: Create R2 bucket

Dashboard: **R2** → **Create bucket** → name `kellblog-audio`.

Or CLI:

```bash
npx wrangler r2 bucket create kellblog-audio
```

---

## Step 5: Connect custom domain `kellblog.thisisgrant.com`

Dashboard:

1. Open bucket **kellblog-audio** → **Settings**.
2. **Custom Domains** → **Add**.
3. Domain: `kellblog.thisisgrant.com` → **Connect domain**.
4. Cloudflare adds the DNS record automatically (when the zone is on Cloudflare).

Or CLI (needs zone ID from Step 3):

```bash
npx wrangler r2 bucket domain add kellblog-audio \
  --domain kellblog.thisisgrant.com \
  --zone-id <ZONE_ID_FOR_THISISGRANT_COM>
```

Verify:

```bash
npx wrangler r2 bucket domain list kellblog-audio
dig kellblog.thisisgrant.com
```

---

## Step 6: Create R2 API token (S3-compatible)

1. **R2** → **Manage R2 API Tokens** → **Create API token**.
2. Permission: **Object Read & Write**.
3. Scope: bucket `kellblog-audio` (or entire account).
4. Copy **Access Key ID** and **Secret Access Key** (secret shown once).

---

## Step 7: Configure `.env`

```bash
R2_ACCOUNT_ID=<your-cloudflare-account-id>
R2_ACCESS_KEY_ID=...
R2_SECRET_ACCESS_KEY=...
R2_BUCKET=kellblog-audio
KELLBLOG_AUDIO_PUBLIC_URL=https://kellblog.thisisgrant.com
```

Verify:

```bash
uv run python -c "from kellblog_audio.config import get_settings; print(get_settings().r2_configured)"
```

---

## Step 8: Publish

```bash
uv run kellblog-audio publish
```

Then open:

- `https://kellblog.thisisgrant.com/feed.xml`
- A sample MP3 from an `<enclosure>` tag

---

## Step 9: GitHub Action secrets

| Secret | Value |
|--------|--------|
| `R2_ACCOUNT_ID` | `<your-cloudflare-account-id>` |
| `R2_ACCESS_KEY_ID` | from Step 6 |
| `R2_SECRET_ACCESS_KEY` | from Step 6 |
| `R2_BUCKET` | `kellblog-audio` |

Variable: `KELLBLOG_AUDIO_PUBLIC_URL` = `https://kellblog.thisisgrant.com`

---

## WordPress / main site note

`thisisgrant.com` stays on DreamHost hosting; only **DNS nameservers** move to Cloudflare. WordPress keeps working if you import the same A/CNAME records Cloudflare scanned in Step 3. Double-check the root `@` and `www` records after import.
