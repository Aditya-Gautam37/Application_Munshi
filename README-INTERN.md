# Welcome — Munshi intern setup (Windows)

Hi! This is **Munshi**, an offline desktop app for small transport businesses (see `CLAUDE.md` for the full picture — and open `CLAUDE.md` in your Claude/VS Code so your AI assistant understands the project instantly).

## 1. One-time setup (about 10 minutes)

You need **Python 3.11+** and **VS Code** (you have Claude Pro — use it inside VS Code as you work).

1. **Install Python** from https://python.org — during install, **tick "Add Python to PATH."**
2. **Unzip** this project somewhere simple, e.g. `C:\munshi`.
3. Open the folder in **VS Code** (File → Open Folder).
4. Open a terminal in VS Code (Terminal → New Terminal) and run:
   ```
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   pip install pytest
   ```
5. **(Optional) AI photo-reader key.** The app runs fine without it, but to use the photo→bilty feature, get a **free** Google Gemini key at https://aistudio.google.com/apikey, then:
   ```
   copy .env.example .env
   ```
   Open `.env` and paste your key after `GOOGLE_API_KEY=`. **Never share or commit this file** (it's already git-ignored).

## 2. Run the app

```
python app.py
```
Your browser opens at **http://127.0.0.1:5056**. The **first launch shows a setup wizard** — enter any firm name and create a login (e.g. `admin` / `admin123`). Or click **"Load sample demo data"** to start with fake sample bills to play with.

To stop the app: press **Ctrl + C** in the terminal.

## 3. Run the tests (do this before AND after any change)

```
python -m pytest tests/ -q
```
You should see **9 passed**. If your change makes a test fail, fix it before moving on. These tests protect the money math — treat a red test as a real problem.

## 4. How to work (suggested flow)

1. Pick a task from **`TASKS.md`** (start with the warm-ups).
2. Ask your **Claude** (in VS Code) to help — it can read `CLAUDE.md` for context. Tell it exactly which file/feature you're changing.
3. Make the change, **run the app and click the screen you touched**, then **run the tests**.
4. Keep changes small and focused. Commit often with clear messages (see below).

## 5. Saving your work (git)

This zip has no git history (fresh start). Set it up once:
```
git init
git add -A
git commit -m "Start: my working copy of Munshi"
```
Then commit after each finished task: `git add -A && git commit -m "what you did"`. Yash may later invite you to the shared GitHub repo — then you'll push there.

## 6. Where things are (quick reference)
- App code: **`app.py`** (one big file — use Ctrl+F / your Claude to navigate)
- Screens: **`templates/`** (`base.html` is the shared layout)
- Styles: **`static/jl-app.css`**
- Hindi words: **`translations/hi.json`**
- Tests: **`tests/test_smoke.py`**
- Full project guide for your AI: **`CLAUDE.md`**
- Your task list: **`TASKS.md`**

## 7. Golden rules
- The app must always **run** and the **tests must stay green** before you call something done.
- Be careful around **money/payments**, **GST invoice math**, and the **setup/login flow** (marked in `CLAUDE.md`). Test extra after touching them.
- Ask questions early. A 2-minute question beats a day down the wrong path.

Have fun — this is a real product going to real transporters in Kanpur. 🚚
