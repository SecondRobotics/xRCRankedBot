"""Compatibility wrappers for the orchestrator migration.

Server process lifecycle is owned by the xRC Server Orchestrator. New bot code
should use ``OrchestratorClient`` or the ``ServerActions`` cog directly.
"""


def start_server_process(*args, **kwargs):
    raise RuntimeError("Local xRC process launch has been removed. Use the orchestrator API.")


def stop_server_process(*args, **kwargs):
    raise RuntimeError("Local xRC process stop has been removed. Use the orchestrator API.")
