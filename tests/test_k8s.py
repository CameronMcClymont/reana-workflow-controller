# This file is part of REANA.
# Copyright (C) 2024 CERN.
#
# REANA is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

from unittest.mock import Mock, patch
from uuid import uuid4

from reana_workflow_controller.k8s import (
    InteractiveDeploymentK8sBuilder,
    build_interactive_jupyter_deployment_k8s_objects,
)
from reana_commons.k8s.secrets import UserSecretsStore, UserSecrets, Secret


def test_interactive_deployment_k8s_builder_user_secrets(monkeypatch):
    """Expose user secrets in interactive sessions"""
    user_id = uuid4()
    user_secrets = UserSecrets(
        user_id=str(user_id),
        k8s_secret_name="k8s-secret",
        secrets=[Secret(name="third_env", type_="env", value="3")],
    )
    monkeypatch.setattr(
        UserSecretsStore,
        "fetch",
        lambda _: user_secrets,
    )

    builder = InteractiveDeploymentK8sBuilder(
        "name", "workflow_id", "owner_id", "workspace", "docker_image", "port", "path"
    )

    builder.add_command_arguments(["args"])
    builder.add_reana_shared_storage()
    builder.add_user_secrets()
    builder.add_environment_variable("first_env", "1")
    builder.add_environment_variable("second_env", "2")
    builder.add_run_with_root_permissions()
    objs = builder.get_deployment_objects()

    deployment = objs["deployment"]
    pod = deployment.spec.template.spec
    assert len(pod.containers) == 1
    assert any(v["name"] == "k8s-secret" for v in pod.volumes)
    assert any(vm["name"] == "k8s-secret" for vm in pod.containers[0].volume_mounts)
    assert any(e["name"] == "third_env" for e in pod.containers[0].env)


def _build_jupyter_session(read_only):
    """Build a Jupyter interactive session deployment with the given flag."""
    user_id = uuid4()
    user_secrets = UserSecrets(
        user_id=str(user_id),
        k8s_secret_name="k8s-secret",
        secrets=[],
    )
    with patch.object(UserSecretsStore, "fetch", lambda _: user_secrets), patch(
        "reana_workflow_controller.k8s."
        "REANA_KUBERNETES_JOBS_READ_ONLY_ROOT_FILESYSTEM",
        read_only,
    ):
        objs = build_interactive_jupyter_deployment_k8s_objects(
            "session-name",
            "/workspace",
            "/access-path",
            "docker.io/jupyter/scipy-notebook",
            owner_id=str(user_id),
            workflow_id=str(uuid4()),
            expose_secrets=False,
        )
    return objs["deployment"].spec.template.spec.containers[0]


def test_interactive_session_read_only_root_filesystem_enabled():
    """Jupyter session redirects its writable paths into the workspace."""
    container = _build_jupyter_session(read_only=True)
    env = {e.name: e.value for e in container.env}

    assert container.security_context.read_only_root_filesystem is True
    assert env["HOME"] == "/workspace/.reana/home"
    assert env["JUPYTER_RUNTIME_DIR"] == "/workspace/.reana/jupyter/runtime"
    assert env["JUPYTER_DATA_DIR"] == "/workspace/.reana/jupyter/data"
    assert env["XDG_CACHE_HOME"] == "/workspace/.reana/cache"
    assert env["TMPDIR"] == "/workspace/.reana/tmp"
    # the startup command creates the directories before launching the server
    assert container.command == ["/bin/bash", "-c"]
    assert container.args[0].startswith("mkdir -p ")
    assert "start-notebook.sh" in container.args[0]


def test_interactive_session_read_only_root_filesystem_disabled():
    """Without the flag the session keeps its default command and no redirects."""
    container = _build_jupyter_session(read_only=False)
    env = {e.name: e.value for e in container.env}

    assert container.security_context.read_only_root_filesystem is None
    assert "HOME" not in env
    assert "TMPDIR" not in env
    assert container.args[0] == "start-notebook.sh"
