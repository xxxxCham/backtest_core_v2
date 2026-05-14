# Autonomous Builder Supervisor

This supervisor keeps the Streamlit Strategy Builder armed in autonomous mode.
It maps the manual recovery flow from the screenshots to stable application
state instead of brittle screen coordinates.

Manual flow covered:

1. Start `RUN_STREAMLIT.bat`.
2. Open `http://localhost:8503`.
3. Select `Strategy Builder`.
4. Enable `Mode autonome 24/24`.
5. Test or start Ollama at `http://127.0.0.1:11434`.
6. Select `qwen3.6:35b`.
7. Launch the Builder.

Capital, target Sharpe, max iterations, and the other pipeline parameters are
left to the application's existing defaults.

Files:

- `config/autonomous_builder_supervisor.json`: presets and paths.
- `tools/autonomous_builder_supervisor.py`: one-shot watchdog.
- `tools/supervisor_control_panel.py`: Tkinter Play/Stop interface.
- `tools/run_autonomous_builder_supervisor.ps1`: scheduled-task runner.
- `tools/install_autonomous_builder_supervisor.ps1`: installs/removes Windows tasks.
- `RUN_SUPERVISOR_PANEL.bat`: opens the control panel.

Install:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File D:\backtest_core_v2\tools\install_autonomous_builder_supervisor.ps1 -RunNow
```

The installer creates a logon trigger and a 30-minute recurring trigger. It
also tries to add a Windows startup trigger; if Windows refuses Task Scheduler
without administrator rights, it installs an `HKCU\...\Run` fallback that starts
a hidden supervisor loop at session login.

Open the control panel:

```powershell
D:\backtest_core_v2\RUN_SUPERVISOR_PANEL.bat
```

In the panel, `Stop` only suspends future supervision checks. It does not stop
Streamlit, Ollama, or a Strategy Builder session already running. `Play`
reactivates supervision and schedules the next automatic check; it does not
force a new run from the button itself.

Pause automatic relaunches:

```powershell
New-Item -ItemType File C:\Users\o3-Pro\Documents\backtest_results\_builder_sessions\supervisor.disabled -Force
```

Resume automatic relaunches:

```powershell
Remove-Item C:\Users\o3-Pro\Documents\backtest_results\_builder_sessions\supervisor.disabled
```

Check status:

```powershell
D:\backtest_core_v2\.venv\Scripts\python.exe D:\backtest_core_v2\tools\autonomous_builder_supervisor.py status
```
