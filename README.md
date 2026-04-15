# xRC Ranked Bot

A Discord bot written in Discord.py that runs ranked competitive matches for xRC Simulator and submits scores to the Second Robotics API.

## Getting Started

-   Create and activate a virtual environment.
-   Install all the necessary dependencies by running `make deps`.
-   Set up your environment variables by creating a `.env` file and filling in the required values. An example `.env` file can be found [here](./.env.example).
-   Run the bot by running `make run`.

## Dependency Management

-   Direct dependencies live in `requirements.in`.
-   The fully pinned lock file lives in `requirements.txt` and is generated with `pip-tools`.
-   Install locked dependencies with `make deps`.
-   Refresh the lock file with `make lock`.
-   Verify the lock file is up to date with `make check-lock`.
-   The default Makefile Python is `python3.10`. Override it if needed, for example `make lock PYTHON=python3.11`.
