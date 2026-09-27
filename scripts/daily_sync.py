#!/usr/bin/env python3
"""Daily, explicit Git staging and publication. Python standard library only."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = "upstream/CoDE-Stop"
DIRECTORIES = {"docs", "src", "configs", "scripts", "tests", "results"}
ROOT_FILES = {"README.md", "AGENTS.md", "UPSTREAM.json", ".gitignore",
              "requirements-diagnostic.txt"}
REMOTE_URLS = {"https://github.com/Ericzhy0716/CoDE.git",
               "https://github.com/Ericzhy0716/CoDE",
               "git@github.com:Ericzhy0716/CoDE.git"}
MAX_BYTES = 5 * 1024 * 1024


def git(*args, cwd=None, timeout=30):
    return subprocess.run(
        ["git", "--literal-pathspecs", *args], cwd=cwd or ROOT,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
        timeout=timeout,
    ).stdout


def names(output):
    return [name.decode("utf-8") for name in output.split(b"\0") if name]


def check_name(name, scoped=True):
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError(f"请使用仓库内的明确相对路径：{name}")
    if scoped and path.parts[0] not in DIRECTORIES and name not in ROOT_FILES:
        raise ValueError(f"不在日常同步范围：{name}。不要使用 . 或 upstream/。")
    for part in path.parts:
        low = part.lower()
        if (low in {".git", ".ssh", ".venv", "venv", "__pycache__", "node_modules"}
                or (low.startswith(".env") and low != ".env.example")
                or low.startswith(("id_rsa", "id_ed25519", "credentials", "secrets", "env_vars"))
                or Path(low).suffix in {".pem", ".key", ".safetensors", ".ckpt", ".pt", ".pth", ".bin"}):
            raise ValueError(f"不上传环境、凭据或模型文件：{name}")


def check_size(name, size):
    if size > MAX_BYTES:
        raise ValueError(f"{name} 超过脚本的 5 MiB 小文件限制，请单独整理。")


def check_parents(path):
    for entry in (path, *path.parents):
        if entry == ROOT:
            break
        if entry.is_symlink():
            raise ValueError(f"请检查符号链接，不自动写入或上传：{entry.relative_to(ROOT)}")


def check_working_files(paths):
    for name in paths:
        check_name(name)
        path = ROOT / name
        check_parents(path)
        if path.is_file():
            check_size(name, path.stat().st_size)


def check_index():
    """Check actual staged blobs, including files staged outside this script."""
    changed = names(git("diff", "--cached", "--name-only", "--no-renames", "-z"))
    for name in changed:
        check_name(name)
        entry = git("ls-files", "--stage", "--", name).decode().strip()
        if not entry:  # A staged deletion.
            continue
        mode, oid, stage = entry.split("\t", 1)[0].split()
        if mode not in {"100644", "100755"} or stage != "0":
            raise ValueError(f"不自动提交子模块、链接或合并冲突：{name}")
        check_size(name, int(git("cat-file", "-s", oid)))
    return changed


def export_notes():
    """Preserve tracked upstream edits without changing its pinned commit."""
    sub = ROOT / UPSTREAM
    if not (sub / ".git").exists():
        raise ValueError("上游子模块尚未初始化，无法导出笔记。")
    base = git("rev-parse", f"HEAD:{UPSTREAM}").decode().strip()
    if git("rev-parse", "HEAD", cwd=sub).decode().strip() != base:
        raise ValueError("上游 HEAD 已改变，请先检查版本；脚本不更新子模块指针。")
    untracked = names(git("ls-files", "--others", "--exclude-standard", "-z", cwd=sub))
    if untracked:
        raise ValueError("上游有未跟踪文件，补丁不能完整保存；请先将相关新代码整理到 src/："
                         + ", ".join(untracked))
    changed = names(git("diff", "HEAD", "--name-only", "--no-renames", "-z", cwd=sub))
    for name in changed:
        check_name(name, scoped=False)
        path = sub / name
        if path.is_symlink():
            raise ValueError(f"不导出上游符号链接：{name}")
        if path.is_file():
            check_size(name, path.stat().st_size)
    patch = git("diff", "HEAD", "--no-ext-diff", "--no-textconv", "--no-renames",
                "--full-index", "--binary", cwd=sub)
    if not patch:
        print("上游当前无已跟踪文件修改；保留以前导出的笔记。")
        return []
    if b"GIT binary patch" in patch:
        raise ValueError("上游包含二进制修改，请单独检查；不自动导出。")
    check_size("upstream notes patch", len(patch))
    stem = f"docs/upstream-notes/{datetime.date.today().isoformat()}"
    paths = [stem + ".patch", stem + ".json"]
    for name in paths:
        check_parents(ROOT / name)
    (ROOT / paths[0]).parent.mkdir(parents=True, exist_ok=True)
    (ROOT / paths[0]).write_bytes(patch)
    (ROOT / paths[1]).write_text(json.dumps({
        "upstream_path": UPSTREAM, "base_commit": base,
        "changed_files": changed, "patch_sha256": hashlib.sha256(patch).hexdigest(),
        "scope": "source_edits_snapshot_not_validation_or_experiment_evidence",
        "includes": "tracked files only; both staged and unstaged edits",
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已导出 {len(changed)} 个上游文件的修改：{paths[0]}")
    return paths


def stage(paths, notes=False):
    if not paths and not notes:
        raise ValueError("请指定要暂存的文件/目录，或使用 --notes 导出上游笔记。")
    check_index()  # Preserve, but validate, any existing staged work.
    selected = []
    for name in paths:
        check_name(name)
        selected.append(str(PurePosixPath(name)))
    candidates = set()
    if selected:
        candidates.update(names(git("diff", "HEAD", "--name-only", "--no-renames", "-z", "--", *selected)))
        candidates.update(names(git("ls-files", "--others", "--exclude-standard", "-z", "--", *selected)))
    check_working_files(candidates)
    if notes:
        selected.extend(export_notes())
    if selected:
        git("add", "-A", "--", *selected)
    check_index()
    print(git("diff", "--cached", "--stat").decode(), end="")
    print("暂存完成，尚未提交或上传。请运行 git diff --cached 检查内容（按 q 退出）。")


def check_destination():
    if git("branch", "--show-current").decode().strip() != "main":
        raise ValueError("日常脚本只处理 main 分支；其他分支请使用普通 Git 工作流。")
    urls = git("remote", "get-url", "--push", "--all", "origin").decode().splitlines()
    fetch_url = git("remote", "get-url", "origin").decode().strip()
    if len(urls) != 1 or urls[0] not in REMOTE_URLS or fetch_url not in REMOTE_URLS:
        raise ValueError("origin 推送地址不是预期的 Ericzhy0716/CoDE，请检查 git remote -v。")


def push():
    check_destination()
    print("正在推送 origin/main；遇到冲突会停止，不自动合并或强制覆盖。", flush=True)
    git("push", "--no-force", "origin", "HEAD:refs/heads/main", timeout=60)
    remote = git("ls-remote", "origin", "refs/heads/main", timeout=30).decode().split()
    head = git("rev-parse", "HEAD").decode().strip()
    if not remote or remote[0] != head:
        raise ValueError("推送已返回，但远端读取结果与本地 HEAD 不一致，请核对 GitHub。")
    print(f"上传并核对成功：{head}\nhttps://github.com/Ericzhy0716/CoDE")


def publish(message):
    check_destination()
    changed = check_index()
    if changed:
        # Archived patches preserve original whitespace, including blank context lines.
        ordinary = [name for name in changed
                    if not (name.startswith("docs/upstream-notes/") and name.endswith(".patch"))]
        if ordinary:
            git("diff", "--cached", "--check", "--", *ordinary)
        print(git("commit", "-m", message).decode(), end="", flush=True)
    else:
        print("没有暂存的新修改；尝试上传已有本地提交。", flush=True)
    push()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("status", help="查看本仓库和上游修改，不做改动")
    s = commands.add_parser("stage", help="暂存明确选择的文件；不会提交或上传")
    s.add_argument("paths", nargs="*")
    s.add_argument("--notes", action="store_true", help="同时导出上游已跟踪文件修改")
    p = commands.add_parser("publish", help="提交已检查的暂存内容并推送")
    p.add_argument("-m", "--message", required=True)
    commands.add_parser("push", help="仅重试上传，不创建新提交")
    args = parser.parse_args()
    try:
        if args.command == "stage":
            stage(args.paths, args.notes)
        elif args.command == "publish":
            publish(args.message)
        elif args.command == "push":
            push()
        else:
            print("主仓库：\n" + git("status", "--short").decode(), end="")
            if (ROOT / UPSTREAM / ".git").exists():
                print("上游子模块（需要 --notes 才能导出内部修改）：\n"
                      + git("status", "--short", cwd=ROOT / UPSTREAM).decode(), end="")
        return 0
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print(f"停止：{exc}", file=sys.stderr)
        if isinstance(exc, subprocess.CalledProcessError):
            print(exc.stderr.decode(errors="replace"), file=sys.stderr)
        print("原文件不会被脚本清理或回退。提交成功后遇到网络错误，恢复网络后用 push 重试；"
              "若上传超时，先核对 GitHub，不能据此认定上传成功或失败。", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
