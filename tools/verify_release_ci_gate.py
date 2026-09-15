"""发布门禁校验：release commit 自身有成功 CI，或与最近绿灯祖先仅差版本文件。

纯版本号 bump 的 push 不触发 CI（ci.yml 对 version.py 配置了 paths-ignore），
此时允许 release 借用第一父链上最近一次绿灯 run 的结论，但两次 commit 之间的
全部改动必须落在白名单内，避免夹带未经 CI 检验的发布内容。
"""

from __future__ import annotations

import json
import os
import subprocess
import urllib.parse
import urllib.request

CI_WORKFLOW_PATH = ".github/workflows/ci.yml"
RELEASE_SAFE_FILES = frozenset({"src/docvortex/version.py"})
ANCESTOR_LIMIT = 16


def successful_push_shas(api_url: str, repository: str, token: str, branch: str = "main", per_page: int = 30) -> set[str]:
    """查询分支上 push 事件触发的 CI run，返回结论为成功的 head SHA 集合。"""
    query = urllib.parse.urlencode({"branch": branch, "event": "push", "per_page": str(per_page)})
    request = urllib.request.Request(
        f"{api_url}/repos/{repository}/actions/runs?{query}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(request) as response:
        payload = json.load(response)
    return {
        run["head_sha"]
        for run in payload.get("workflow_runs", [])
        if run.get("path") == CI_WORKFLOW_PATH and run.get("status") == "completed" and run.get("conclusion") == "success"
    }


def first_parent_chain(repo: str, sha: str, limit: int = ANCESTOR_LIMIT) -> list[str]:
    """返回从 sha 起沿第一父链的 commit 列表（含自身），受 limit 约束。"""
    output = subprocess.run(
        ["git", "-C", repo, "rev-list", "--first-parent", "-n", str(limit), sha],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout
    return output.split()


def changed_files(repo: str, base: str, target: str) -> list[str]:
    """列出两次 commit 之间的改动文件路径。"""
    output = subprocess.run(
        ["git", "-C", repo, "diff", "--name-only", base, target],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout
    return [line for line in output.splitlines() if line]


def verify(repo: str, release_sha: str, green_shas: set[str]) -> tuple[bool, str]:
    """校验发布门禁，返回（是否通过, 说明）。"""
    chain = first_parent_chain(repo, release_sha)
    if release_sha in green_shas:
        return True, "release commit has a successful CI run on main"
    green_ancestor = next((sha for sha in chain[1:] if sha in green_shas), None)
    if green_ancestor is None:
        return (
            False,
            f"no successful CI run on main for the release commit or its {len(chain) - 1} nearest first-parent ancestors",
        )
    changed = changed_files(repo, green_ancestor, release_sha)
    unsafe = sorted(set(changed) - RELEASE_SAFE_FILES)
    if unsafe:
        return (
            False,
            f"release commit changes files beyond {sorted(RELEASE_SAFE_FILES)} since green ancestor {green_ancestor[:12]}: {unsafe}",
        )
    return True, f"release commit only changes {sorted(RELEASE_SAFE_FILES)} since green ancestor {green_ancestor[:12]}"


def main() -> None:
    passed, message = verify(
        os.getcwd(),
        os.environ["GITHUB_SHA"],
        successful_push_shas(os.environ["GITHUB_API_URL"], os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_TOKEN"]),
    )
    print(message)
    if not passed:
        raise SystemExit(message)


if __name__ == "__main__":
    main()
