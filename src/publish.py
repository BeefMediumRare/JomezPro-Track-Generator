"""Push generated tracks to the public repo the extension syncs from.

The server works inside its own checkout (cloned on first run, fast-forwarded on
each round so it never diverges from what's published). Tracks are written into
that checkout's tracks/JomezPro and committed one per video.

Auth is a fine-grained PAT read from the GITHUB_TOKEN env var. It's handed to git
through a credential helper that echoes the token from the environment, so the
token never lands in argv (visible in `ps`) or in .git/config on disk. Commits are
made under a plain bot identity and are deliberately unsigned — the maintainer's
interactive 1Password signing can't run headless.
"""

import os
import subprocess

# Credential helper: git calls it for github.com and it reads the token from the
# process environment. The empty helper first clears any inherited system helper.
_CRED_HELPER = '!f() { echo username=x-access-token; echo "password=$GITHUB_TOKEN"; }; f'


class PublishError(RuntimeError):
    pass


def _base(cfg):
    # safe.directory keeps git happy when the checkout lives on a Docker volume
    # owned by a different uid than the process.
    return ["git", "-C", cfg.repo_dir, "-c", f"safe.directory={os.path.abspath(cfg.repo_dir)}"]


def _auth():
    return ["-c", "credential.helper=", "-c", f"credential.helper={_CRED_HELPER}"]


def _run(args, check=True):
    proc = subprocess.run(args, capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise PublishError((proc.stderr or proc.stdout).strip())
    return proc


def _require_token():
    if not os.environ.get("GITHUB_TOKEN"):
        raise PublishError("GITHUB_TOKEN is not set; cannot push to GitHub.")


def ensure_repo(cfg):
    """Make cfg.repo_dir a checkout sitting at origin/<branch>. Clones it on the
    first run, otherwise fetches and hard-resets so dedup sees what's published and
    local state never drifts. Untracked leftovers under tracks/ (e.g. a track from
    a crashed round) are cleaned, so each round starts pristine. Also pins the bot
    identity and turns signing off.

    No token needed here — the repo is public, so clone/fetch work anonymously.
    Only push() requires GITHUB_TOKEN."""
    git_dir = os.path.join(cfg.repo_dir, ".git")
    if not os.path.isdir(git_dir):
        _run(["git"] + _auth() + ["clone", "--branch", cfg.repo_branch,
                                  "--single-branch", cfg.repo_url, cfg.repo_dir])
    else:
        _run(_base(cfg) + _auth() + ["fetch", "origin", cfg.repo_branch])
        _run(_base(cfg) + ["checkout", cfg.repo_branch])
        _run(_base(cfg) + ["reset", "--hard", f"origin/{cfg.repo_branch}"])
        _run(_base(cfg) + ["clean", "-fd", "--", "tracks"])
    _run(_base(cfg) + ["config", "user.name", cfg.git_user_name])
    _run(_base(cfg) + ["config", "user.email", cfg.git_user_email])
    _run(_base(cfg) + ["config", "commit.gpgsign", "false"])


def commit_track(cfg, path, title):
    """Stage and commit one track. Returns True if a commit was made, False if
    there was nothing to commit (the track already matched what's checked in)."""
    _run(_base(cfg) + ["add", "--", path])
    status = _run(_base(cfg) + ["status", "--porcelain", "--", path])
    if not status.stdout.strip():
        return False
    message = (f'Add speed track for "{title}"\n\n'
               "So the extension can skip this video's filler and play the throws "
               "at normal speed.")
    _run(_base(cfg) + ["commit", "-m", message])
    return True


def push(cfg):
    """Push committed tracks to origin."""
    _require_token()
    _run(_base(cfg) + _auth() + ["push", "origin", cfg.repo_branch])
