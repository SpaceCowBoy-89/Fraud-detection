# macOS LaunchAgent: standalone pipeline scheduler

Use this when you want **`python scheduler.py`** to run **outside** the Flask process so scheduled jobs survive web restarts. The web app should set **`SKIP_EMBEDDED_SCHEDULER=1`** (see `.env.example`) so only one scheduler runs.

## Install

1. Copy `com.fraud-detection.pipeline.plist` to `~/Library/LaunchAgents/`.
2. Replace every **`ABSOLUTE/PATH/TO/fraud-detection`** with your project directory (three places: `ProgramArguments`, `WorkingDirectory`, `EnvironmentVariables`).
3. If you use a virtualenv, change `ProgramArguments` to the venv’s `python` and keep `WorkingDirectory` pointing at the project root.
4. Load the agent:

```bash
launchctl unload ~/Library/LaunchAgents/com.fraud-detection.pipeline.plist 2>/dev/null
launchctl load ~/Library/LaunchAgents/com.fraud-detection.pipeline.plist
```

5. Start the web app with **`SKIP_EMBEDDED_SCHEDULER=1`** in the environment (or in `.env` if you add dotenv loading later).

## Behavior

- **`KeepAlive`**: restarts the process if it exits (e.g. crash).
- **`RunAtLoad`**: starts the scheduler when you log in.
- Logs go to `/tmp/fraud-pipeline-scheduler.log` and `.err` (edit paths in the plist if you prefer).

## Limitations

- A sleeping or powered-off Mac **cannot** run jobs. For laptops, keep the machine awake at the scheduled hour, use **AC power**, or run the stack on a small always-on host.
- **SQLAlchemy** must be installed (`pip install sqlalchemy`) so APScheduler can persist jobs to `apscheduler_jobs.sqlite`.

## Uninstall

```bash
launchctl unload ~/Library/LaunchAgents/com.fraud-detection.pipeline.plist
rm ~/Library/LaunchAgents/com.fraud-detection.pipeline.plist
```
