"""Tests for tools/file_tools.py"""
import os
import tempfile
import unittest
from unittest.mock import patch

from tools.file_tools import FileTreeTool, ReadFileTool


class TestFileTreeTool(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = self.tmpdir.name
        # Build a small tree
        os.makedirs(os.path.join(self.root, "src", "core"))
        os.makedirs(os.path.join(self.root, "tests"))
        os.makedirs(os.path.join(self.root, ".git"))
        open(os.path.join(self.root, "README.md"), "w").close()
        open(os.path.join(self.root, "src", "main.py"), "w").close()
        open(os.path.join(self.root, "src", "core", "agent.py"), "w").close()
        open(os.path.join(self.root, "tests", "test_agent.py"), "w").close()
        open(os.path.join(self.root, ".git", "config"), "w").close()

        # Patch allowed roots to include the temp directory for tests
        self.patcher = patch("tools.file_tools._get_allowed_roots", return_value=[self.root])
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        self.tmpdir.cleanup()

    def test_file_tree_basic(self):
        tool = FileTreeTool()
        result = tool.execute({"path": self.root, "depth": 2})
        self.assertTrue(result.success, result.output)
        self.assertIn("src/", result.output)
        self.assertIn("tests/", result.output)
        self.assertIn("README.md", result.output)
        self.assertIn("main.py", result.output)
        # Hidden / skipped dirs should not appear
        self.assertNotIn(".git", result.output)

    def test_file_tree_depth_limit(self):
        tool = FileTreeTool()
        result = tool.execute({"path": self.root, "depth": 1})
        self.assertTrue(result.success, result.output)
        self.assertIn("src/", result.output)
        # depth=1 should not list files inside src/core
        self.assertNotIn("core/", result.output)

    def test_file_tree_path_not_allowed(self):
        tool = FileTreeTool()
        with patch("tools.file_tools._get_allowed_roots", return_value=["C:\\fake"]):
            result = tool.execute({"path": "C:\\Windows"})
        self.assertFalse(result.success)

    def test_file_tree_not_directory(self):
        fpath = os.path.join(self.root, "README.md")
        tool = FileTreeTool()
        result = tool.execute({"path": fpath})
        self.assertFalse(result.success)


class TestReadFileToolDirectory(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = self.tmpdir.name
        open(os.path.join(self.root, "a.txt"), "w").close()
        os.makedirs(os.path.join(self.root, "sub"))
        self.patcher = patch("tools.file_tools._get_allowed_roots", return_value=[self.root])
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        self.tmpdir.cleanup()

    def test_read_directory_lists_contents(self):
        tool = ReadFileTool()
        result = tool.execute({"path": self.root})
        self.assertTrue(result.success, result.output)
        self.assertIn("a.txt", result.output)
        self.assertIn("sub/", result.output)


if __name__ == "__main__":
    unittest.main()
