# DAOThink — Team Setup

Follow these steps after extracting the archive.

## 1. Extract the archive

        unzip daothink_team_share.zip
        cd daothink

On Windows, right-click the ZIP and choose "Extract All", then open the
`daothink` folder in a terminal.

## 2. Create a virtual environment

macOS / Linux:

        python3 -m venv .venv
        source .venv/bin/activate

Windows (PowerShell):

        py -m venv .venv
        .venv\Scripts\Activate.ps1

The project is developed and tested on Python 3.13.

## 3. Install dependencies

With the virtual environment active:

        pip install -r requirements.txt

`requirements.txt` contains: `uagents`, `requests`, `beautifulsoup4`,
`python-dotenv`.

## 4. Configure your own credentials

Copy the template and fill in your own values:

        cp .env.example .env

Then edit `.env` and replace every placeholder with your own private seed
strings:

- `RESEARCH_AGENT_SEED` — used by the Research Agent.
- `ANALYSIS_AGENT_SEED` — used by the Analysis Agent.
- `ORCHESTRATOR_SEED` — used as the local test client identity by
  `send_request.py` (binds port 8000).
- `DAOTHINK_LOCAL` — leave as `1` for local development.

Never commit or share the real `.env`. It is already listed in `.gitignore`.
Use one unique seed per person and per agent; agent addresses are derived from
these seeds, so changing a seed changes the agent's address.

## 5. Run the Research Agent

From the `daothink` folder, with the virtual environment active:

        python research_agent.py

It listens on port 8001 and logs its address at startup. Keep this terminal
open while testing.

## 6. Run the Analysis Agent

In a separate terminal (same folder, same virtual environment):

        python analysis_agent.py

It listens on port 8002.

## 7. Run the tests

        python -m pytest -q

Notes:

- Run the tests from inside the `daothink` folder.
- The unit tests do not make real network requests.
- One integration test (`test_e2e_research_agent_real_messaging`) only runs
  when the Research Agent is already running on port 8001 and network access is
  available; otherwise pytest reports it as skipped.

To try the Research Agent end to end, start it (step 5) and then run:

        python send_request.py --mode research

Port 8001 is not an HTTP API; the client talks to the agent over the uAgents
message transport.

## 8. Local development requirements

- Python 3.13 and a virtual environment with `requirements.txt` installed.
- A `.env` file with the three seeds listed above.
- Ports 8000, 8001 and 8002 free on your machine.
- Local agent-to-agent messaging uses a rules-based resolver
  (`DAOTHINK_LOCAL=1`), so no on-chain registration is needed for local tests.
- Outbound HTTPS access for the Research Agent to fetch source URLs.

## 9. Hosted deployment (not covered by this archive)

Running on Agentverse / with mailbox messaging needs additional configuration
that is not included here:

- Almanac contract registration requires a funded wallet; without funds the
  agent still starts but cannot register on-chain.
- Agentverse mailbox setup and any hosted endpoint configuration are separate
  steps.
- Setting `DAOTHINK_LOCAL=0` switches networking to global resolution, which
  only works once the agents are actually registered and reachable.

Do not assume deployment works just because the agents start locally.
