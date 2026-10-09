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

## Game Selection

`/launchserver` and `/hangout_create` search the full game catalog as you type.
The dropdown shows up to 25 suggestions at a time; type part of a game name
(for example, `bio` for Biobuzz) to find games outside the initial suggestions.
You can also submit a full game name without selecting a suggestion. Names
are case-insensitive, and valid game IDs are accepted as well.

## Testing

After installing the project dependencies, run the automated test suite:

```sh
make test
```

GitHub Actions runs the same suite with Python 3.10 on pushes to any branch and
on pull requests targeting `main`.

Override the Python interpreter if needed, for example `make test PYTHON=python3.11`.
Or run test discovery directly:

```sh
python3.10 -m unittest discover -s tests -v
```

Tests live in `tests/` and use Python's built-in `unittest` framework. Name new
test modules `test_*.py` so discovery includes them. Tests use dummy configuration
and mock external effects, so no `.env` file, credentials, or live Discord
connection is needed. Live Discord API acceptance is checked separately by
deploying and synchronizing the bot's commands.
