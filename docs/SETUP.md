# Setup: Telegram alerts and GitHub Actions

You do this once. It takes about 10 minutes.

## 1. Create your Telegram bot

1. In Telegram, open a chat with **@BotFather** (check it has the blue verified tick).
2. Send `/newbot`, then choose a name and a username ending in `bot`.
3. BotFather replies with the **bot token** (looks like `123456789:AA...`). Keep it private.
4. Open your new bot's chat and press **Start** (send it any message). A bot cannot message you
   until you have done this.

## 2. Find your chat id

After sending your bot a message, open this in a browser (replace `<TOKEN>`; do not share the page):

`https://api.telegram.org/bot<TOKEN>/getUpdates`

Look for `"chat":{"id":123456789,...}`. That number is your **chat id**.

## 3. Test it from your laptop (optional)

```bash
export TELEGRAM_BOT_TOKEN="your-token"
export TELEGRAM_CHAT_ID="your-chat-id"
uv run python -m tracker run
```

If this is the first run for a company you get one "Now tracking ..." message. Otherwise you get
one message per new internship. Never paste the token into a file in this repo.

## 4. Add the GitHub secrets

Repository → Settings → Secrets and variables → Actions → New repository secret:

| Name | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | the token BotFather sent you |
| `TELEGRAM_CHAT_ID` | your chat id |

Without these the workflow still updates `data/`; it just skips Telegram (with a warning in the log).

## 5. Run the workflow once by hand

Actions tab → **scrape** → Run workflow. When it finishes:

- the log ends with `Telegram: N sent, M waiting`,
- you receive the messages on Telegram,
- a `chore(data): update listings` commit appears if anything changed,
- running it again right away sends nothing and commits nothing.

After that it runs on its own. With the outside timer from section 7, expect alerts within about
10 to 15 minutes of a posting appearing; on GitHub's own cron alone it can be hours.

GitHub pauses scheduled workflows in a repository with no activity for 60 days. If alerts stop,
check the Actions tab and re-enable the workflow.

## 6. Checking a new company from GitHub's servers

Some career sites block cloud IPs. Before enabling a company, run Actions → **cloud-check** with
its slug (for example `nvidia,intel`). It prints posting counts and saves nothing. If it fails
there but works on your laptop, keep the company disabled and note it in `docs/CUSTOM_PORTALS.md`.

## 7. Make it run every 10 minutes (outside timer)

GitHub's own cron is unreliable on a quiet repo: in practice it ran every 3 to 9 hours instead of
every 15 minutes. A run started through the API (`workflow_dispatch`) begins within seconds, so a free
outside timer calls that every 10 minutes. The GitHub cron stays as a backup.

### 7a. Create a GitHub token that can only start this workflow
1. GitHub, top-right avatar, **Settings**, **Developer settings**, **Personal access tokens**,
   **Fine-grained tokens**, **Generate new token**.
2. Name: `internship-tracker-timer`. Expiration: 1 year (put a reminder in your calendar).
3. **Repository access**: *Only select repositories*, then pick `internship-tracker`.
4. **Permissions**, *Repository permissions*: **Actions: Read and write**. Leave everything else at
   *No access* (Metadata: Read-only is added automatically).
5. **Generate token** and copy it (starts with `github_pat_`). You see it only once. Do not paste it
   into this repo or into a chat.

### 7b. Create the timer on cron-job.org (free)
1. Sign up at https://cron-job.org and confirm your email.
2. **Create cronjob**. Title: `internship-tracker`.
3. **URL**: `https://api.github.com/repos/Sarthzk/internship-tracker/actions/workflows/scrape.yml/dispatches`
4. **Execution schedule**: every 10 minutes.
5. **Advanced**:
   - Request method: **POST**
   - Request body: `{"ref":"main"}`
   - Headers (add each):
     - `Authorization`: `Bearer <your github_pat_ token>`
     - `Accept`: `application/vnd.github+json`
     - `X-GitHub-Api-Version`: `2022-11-28`
     - `Content-Type`: `application/json`
6. Turn on **notify me on failures** and save.
7. Click **Test run**. A success shows **HTTP 204** (no body). Then open the repo's **Actions** tab:
   a new `scrape` run should appear within seconds.

If it shows 401 or 403 the token is wrong or lacks *Actions: Read and write*; 404 means the URL has a
typo or the token cannot see the repo.

### 7c. How to tell it is working
Open the Actions tab. You should see a `scrape` run roughly every 10 minutes, each about a minute
long, with the trigger shown as `workflow_dispatch`. Runs where nothing changed commit nothing.
If the timer service is down, the GitHub cron backup still fires now and then.

## What the messages mean

- `🆕 Company: Role` + location + link: a new internship.
- `🆕 N new internships`: five or more arrived at once, combined into one message.
- `📋 Now tracking ...`: a company was fetched for the first time; its already-open internships
  are summarised once instead of one message each.
- `⚠️ Company has failed 3 runs in a row`: its fetcher is broken; sent once.
- `✅ Company is working again`: sent once, after a `⚠️`.
- `🚨 internship-tracker run crashed`: the whole run failed (the Action also shows red).
