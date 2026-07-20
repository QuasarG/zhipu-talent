#!/usr/bin/env bash
set -euo pipefail

REPOSITORY_URL="${REPOSITORY_URL:-https://github.com/QuasarG/zhipu-talent.git}"
BRANCH="${1:-master}"
APP_ROOT="${APP_ROOT:-/opt/zhipu-talent}"
REPOSITORY_DIR="${APP_ROOT}/repository"
RELEASES_DIR="${APP_ROOT}/releases"
CURRENT_LINK="${APP_ROOT}/current"
VENV_DIR="${APP_ROOT}/venv"

if [[ "${EUID}" -ne 0 ]]; then
    echo "deploy-from-git.sh must run as root." >&2
    exit 1
fi

exec 9>/run/lock/talent-radar-deploy.lock
flock -n 9 || {
    echo "Another talent-radar deployment is running." >&2
    exit 1
}

install -d -o root -g root "${APP_ROOT}" "${RELEASES_DIR}"

if [[ ! -d "${REPOSITORY_DIR}/.git" ]]; then
    git clone --branch "${BRANCH}" --single-branch "${REPOSITORY_URL}" "${REPOSITORY_DIR}"
else
    git -C "${REPOSITORY_DIR}" fetch origin "${BRANCH}" --prune
fi

revision="$(git -C "${REPOSITORY_DIR}" rev-parse "origin/${BRANCH}")"
release_id="$(git -C "${REPOSITORY_DIR}" rev-parse --short=12 "${revision}")"
release_dir="${RELEASES_DIR}/${release_id}"
previous_release="$(readlink -f "${CURRENT_LINK}" 2>/dev/null || true)"

if [[ ! -d "${release_dir}" ]]; then
    git -C "${REPOSITORY_DIR}" worktree add --detach "${release_dir}" "${revision}"
fi

"${VENV_DIR}/bin/pip" install -r "${release_dir}/requirements.txt"
chown -R root:root "${release_dir}"

ln -sfn "${release_dir}" "${CURRENT_LINK}"
systemctl restart talent-radar

healthy=0
for _ in $(seq 1 30); do
    if curl -fsS http://127.0.0.1:8503/ >/dev/null; then
        healthy=1
        break
    fi
    sleep 1
done

if [[ "${healthy}" -ne 1 ]]; then
    if [[ -n "${previous_release}" && -d "${previous_release}" ]]; then
        ln -sfn "${previous_release}" "${CURRENT_LINK}"
        systemctl restart talent-radar
    fi
    echo "Deployment health check failed; previous release restored." >&2
    exit 1
fi

git -C "${REPOSITORY_DIR}" worktree prune
echo "Deployed ${revision} to ${release_dir}."
