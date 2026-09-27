"""Local Git integration tests; never contact GitHub or run a model."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import daily_sync as sync


class DailySyncTests(unittest.TestCase):
    def git(self, *args, cwd=None):
        return subprocess.check_output(["git", *args], cwd=cwd or self.root,
                                       stderr=subprocess.PIPE).decode().strip()

    def initialize(self, path):
        path.mkdir()
        self.git("init", "-b", "main", cwd=path)
        self.configure(path)

    def configure(self, path):
        for key, value in (("user.name", "Sync Fixture"), ("user.email", "fixture@example.invalid"),
                           ("commit.gpgsign", "false"), ("core.hooksPath", str(self.tmp / "no-hooks"))):
            self.git("config", key, value, cwd=path)

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.tmp = Path(temp.name).resolve()
        source = self.tmp / "source"
        self.root = self.tmp / "work"
        self.initialize(source)
        (source / "method.py").write_text("value = 1\n")
        self.git("add", "method.py", cwd=source)
        self.git("commit", "-m", "base", cwd=source)
        self.initialize(self.root)
        self.git("-c", "protocol.file.allow=always", "submodule", "add", str(source), sync.UPSTREAM)
        self.sub = self.root / sync.UPSTREAM
        self.configure(self.sub)
        (self.root / "README.md").write_text("Fixture\n")
        (self.root / ".gitignore").write_text("/runs/\n/data/\n.env\n")
        self.git("add", ".")
        self.git("commit", "-m", "initial")
        self.remote = self.tmp / "remote.git"
        self.git("init", "--bare", "-b", "main", str(self.remote))
        self.git("remote", "add", "origin", str(self.remote))
        self.git("push", "-u", "origin", "main")
        for target, value in (("ROOT", self.root), ("REMOTE_URLS", {str(self.remote)})):
            p = patch.object(sync, target, value)
            p.start()
            self.addCleanup(p.stop)

    def write(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        return target

    def test_explicit_selection_and_existing_staged_work(self):
        self.write("docs/今日 笔记.md", "新笔记\n")
        self.write("src/later.py", "later = True\n")
        self.write("runs/raw.json", "{}\n")
        self.write("README.md", "Updated fixture\n")
        self.git("add", "README.md")
        sync.stage(["docs"])
        self.assertEqual(set(sync.check_index()), {"README.md", "docs/今日 笔记.md"})
        self.assertIn("src/", self.git("status", "--short"))
        self.assertTrue((self.root / "runs/raw.json").exists())

    def test_disallowed_and_large_files_do_not_get_staged(self):
        for name in ("runs/raw.json", "docs/.env", "src/weights.safetensors"):
            self.write(name, "fixture\n")
            with self.assertRaises(ValueError):
                sync.stage([name])
            self.assertEqual(sync.check_index(), [])
        with self.assertRaises(ValueError):
            sync.stage(["."])
        self.write("docs/large.txt", "a" * (sync.MAX_BYTES + 1))
        with self.assertRaises(ValueError):
            sync.stage(["docs/large.txt"])
        (self.root / "docs/link.txt").symlink_to(self.root / "README.md")
        with self.assertRaises(ValueError):
            sync.stage(["docs/link.txt"])
        self.assertEqual(sync.check_index(), [])

    def test_publish_checks_manually_staged_files(self):
        before = self.git("rev-parse", "HEAD")
        self.write("runs/raw.json", "fixture\n")
        self.git("add", "-f", "runs/raw.json")
        with self.assertRaises(ValueError):
            sync.publish("must not commit raw output")
        self.assertEqual(before, self.git("rev-parse", "HEAD"))
        self.assertTrue((self.root / "runs/raw.json").exists())

    def test_notes_round_trip_includes_staged_and_unstaged_edits(self):
        before = self.git("rev-parse", "HEAD", cwd=self.sub)
        source = self.sub / "method.py"
        source.write_text("# first note\nvalue = 1\n")
        self.git("add", "method.py", cwd=self.sub)
        expected = "# first note  \nvalue = 1\n# 第二条注释\n"
        source.write_text(expected)
        paths = sync.export_notes()
        metadata = json.loads((self.root / paths[1]).read_text())
        self.assertEqual(metadata["base_commit"], before)
        self.assertEqual(metadata["patch_sha256"], hashlib.sha256((self.root / paths[0]).read_bytes()).hexdigest())
        self.assertEqual(source.read_text(), expected)
        self.assertEqual(before, self.git("rev-parse", "HEAD", cwd=self.sub))
        restore = self.tmp / "restore"
        self.git("clone", str(self.sub), str(restore))
        self.git("apply", "--check", str(self.root / paths[0]), cwd=restore)
        self.git("apply", str(self.root / paths[0]), cwd=restore)
        self.assertEqual((restore / "method.py").read_text(), expected)
        sync.stage([], notes=True)
        self.assertEqual(set(sync.check_index()), set(paths))
        self.assertIn("method.py", self.git("status", "--short", cwd=self.sub))
        sync.publish("preserve notes including original whitespace")
        self.assertEqual(self.git("rev-parse", "HEAD"), self.git("rev-parse", "main", cwd=self.remote))
        self.assertEqual(source.read_text(), expected)

    def test_notes_refuse_untracked_and_changed_upstream_commit(self):
        new = self.sub / "new.py"
        new.write_text("new = 1\n")
        with self.assertRaises(ValueError):
            sync.export_notes()
        self.git("add", "new.py", cwd=self.sub)
        self.git("commit", "-m", "different upstream head", cwd=self.sub)
        with self.assertRaises(ValueError):
            sync.export_notes()
        self.assertFalse((self.root / "docs/upstream-notes").exists())

    def test_publish_records_deletion_and_verifies_remote(self):
        (self.root / "README.md").unlink()
        sync.stage(["README.md"])
        sync.publish("delete fixture readme")
        self.assertEqual(self.git("rev-parse", "HEAD"), self.git("rev-parse", "main", cwd=self.remote))
        self.assertEqual(self.git("diff-tree", "--no-commit-id", "--name-status", "-r", "HEAD"), "D\tREADME.md")

    def test_push_retry_keeps_the_same_local_commit(self):
        self.write("docs/note.md", "keep this\n")
        sync.stage(["docs"])
        missing = str(self.tmp / "unavailable.git")
        self.git("remote", "set-url", "origin", missing)
        with patch.object(sync, "REMOTE_URLS", {missing}):
            with self.assertRaises(subprocess.CalledProcessError):
                sync.publish("saved before network failure")
        committed = self.git("rev-parse", "HEAD")
        self.assertEqual(self.git("log", "-1", "--format=%s"), "saved before network failure")
        self.git("remote", "set-url", "origin", str(self.remote))
        sync.push()
        self.assertEqual(committed, self.git("rev-parse", "HEAD"))
        self.assertEqual(committed, self.git("rev-parse", "main", cwd=self.remote))

    def test_remote_divergence_never_overwrites_other_commit(self):
        other = self.tmp / "other"
        self.git("clone", str(self.remote), str(other))
        self.configure(other)
        (other / "README.md").write_text("other machine\n")
        self.git("add", "README.md", cwd=other)
        self.git("commit", "-m", "other writer", cwd=other)
        self.git("push", "origin", "main", cwd=other)
        remote_head = self.git("rev-parse", "main", cwd=self.remote)
        self.write("docs/note.md", "my work\n")
        sync.stage(["docs"])
        with self.assertRaises(subprocess.CalledProcessError):
            sync.publish("my work survives rejection")
        self.assertEqual(remote_head, self.git("rev-parse", "main", cwd=self.remote))
        self.assertEqual((self.root / "docs/note.md").read_text(), "my work\n")
        self.assertEqual(self.git("log", "-1", "--format=%s"), "my work survives rejection")


if __name__ == "__main__":
    unittest.main()
