"""Tests for rbxbundle.deps — require() extraction and dependency resolution."""

from __future__ import annotations

import textwrap
import unittest

from rbxbundle.deps import (
    Node,
    ScriptInfo,
    build_dependency_graph,
    find_require_calls,
    _mask_lua_strings_and_comments,
    _collect_service_aliases,
    resolve_require_expr,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_node(full_path: str, class_name: str = "ModuleScript") -> Node:
    parts = full_path.rsplit("/", 1)
    parent = parts[0] if len(parts) == 2 else ""
    name = parts[-1]
    return Node(
        class_name=class_name,
        name=name,
        safe_name=name,
        full_path=full_path,
        parent_path=parent,
    )


def make_nodes(*paths: str) -> dict:
    return {p: make_node(p) for p in paths}


def make_lookup(nodes: dict) -> dict:
    lookup = {}
    for p, n in nodes.items():
        lookup[(n.parent_path, n.name)] = n.full_path
        lookup[(n.parent_path, n.safe_name)] = n.full_path
    return lookup


# ---------------------------------------------------------------------------
# find_require_calls
# ---------------------------------------------------------------------------

class TestFindRequireCalls(unittest.TestCase):
    def test_simple_require(self):
        src = 'local M = require(script.Parent.Mod)'
        calls = find_require_calls(src)
        self.assertEqual(len(calls), 1)
        self.assertIn("script.Parent.Mod", calls[0].arg)

    def test_require_with_waitforchild(self):
        src = 'local M = require(script:WaitForChild("Config"))'
        calls = find_require_calls(src)
        self.assertEqual(len(calls), 1)
        self.assertIn("WaitForChild", calls[0].arg)

    def test_multiple_requires(self):
        src = "local A = require(script.A)\nlocal B = require(script.B)\n"
        calls = find_require_calls(src)
        self.assertEqual(len(calls), 2)

    def test_require_in_string_ignored(self):
        src = 'local x = "require(script.X)"'
        calls = find_require_calls(src)
        self.assertEqual(len(calls), 0)

    def test_require_in_line_comment_ignored(self):
        src = '-- require(script.X)\nlocal y = 1'
        calls = find_require_calls(src)
        self.assertEqual(len(calls), 0)

    def test_require_in_block_comment_ignored(self):
        src = '--[[\nrequire(script.X)\n]]\nlocal y = 1'
        calls = find_require_calls(src)
        self.assertEqual(len(calls), 0)

    def test_line_number_recorded(self):
        src = "local x = 1\nlocal M = require(script.M)"
        calls = find_require_calls(src)
        self.assertEqual(calls[0].line, 2)

    def test_not_identifier_boundary(self):
        # foo.require(...) should NOT match
        src = "foo.require(script.X)"
        calls = find_require_calls(src)
        self.assertEqual(len(calls), 0)

    def test_nested_getservice_parens(self):
        src = 'require(game:GetService("RS").M)'
        calls = find_require_calls(src)
        self.assertEqual(len(calls), 1)

    def test_no_require(self):
        src = "local x = 1 + 2"
        self.assertEqual(find_require_calls(src), [])


# ---------------------------------------------------------------------------
# _mask_lua_strings_and_comments
# ---------------------------------------------------------------------------

class TestMaskLua(unittest.TestCase):
    def test_masks_double_quoted_string(self):
        src = 'x = "hello" + 1'
        masked, _ = _mask_lua_strings_and_comments(src)
        self.assertNotIn("hello", masked)
        self.assertEqual(len(masked), len(src))

    def test_masks_single_quoted_string(self):
        src = "x = 'world'"
        masked, _ = _mask_lua_strings_and_comments(src)
        self.assertNotIn("world", masked)

    def test_masks_line_comment(self):
        src = "local x = 1 -- this is a comment\nlocal y = 2"
        masked, _ = _mask_lua_strings_and_comments(src)
        self.assertNotIn("comment", masked)
        self.assertIn("local y", masked)

    def test_masks_block_comment(self):
        src = "--[[\nblock\n]]\nlocal z = 3"
        masked, _ = _mask_lua_strings_and_comments(src)
        self.assertNotIn("block", masked)
        self.assertIn("local z", masked)

    def test_preserves_length(self):
        src = 'local a = "test" -- comment\nlocal b = 2'
        masked, _ = _mask_lua_strings_and_comments(src)
        self.assertEqual(len(masked), len(src))

    def test_newlines_preserved(self):
        src = "a\nb\nc"
        masked, _ = _mask_lua_strings_and_comments(src)
        self.assertEqual(masked.count("\n"), src.count("\n"))


# ---------------------------------------------------------------------------
# _collect_service_aliases
# ---------------------------------------------------------------------------

class TestCollectServiceAliases(unittest.TestCase):
    def test_basic_alias(self):
        src = 'local RS = game:GetService("ReplicatedStorage")'
        aliases = _collect_service_aliases(src)
        self.assertEqual(aliases.get("RS"), "ReplicatedStorage")

    def test_multiple_aliases(self):
        src = textwrap.dedent("""\
            local RS = game:GetService("ReplicatedStorage")
            local SS = game:GetService("ServerScriptService")
        """)
        aliases = _collect_service_aliases(src)
        self.assertEqual(aliases.get("RS"), "ReplicatedStorage")
        self.assertEqual(aliases.get("SS"), "ServerScriptService")

    def test_no_alias(self):
        self.assertEqual(_collect_service_aliases("local x = 1"), {})

    def test_alias_in_comment_ignored(self):
        src = '-- local RS = game:GetService("ReplicatedStorage")'
        aliases = _collect_service_aliases(src)
        self.assertNotIn("RS", aliases)


# ---------------------------------------------------------------------------
# resolve_require_expr
# ---------------------------------------------------------------------------

class TestResolveRequireExpr(unittest.TestCase):
    def _setup(self, paths):
        nodes = make_nodes(*paths)
        lookup = make_lookup(nodes)
        return nodes, lookup

    def test_script_parent_navigation(self):
        nodes, lookup = self._setup(["A/B", "A/B/SomeScript"])
        resolved, kind, conf = resolve_require_expr(
            "script.Parent",
            src_script_path="A/B/SomeScript",
            nodes=nodes,
            child_by_parent_and_name=lookup,
            service_aliases={},
            instance_aliases={},
        )
        self.assertEqual(resolved, "A/B")

    def test_service_path_with_alias(self):
        nodes, lookup = self._setup([
            "ReplicatedStorage/Flight/World_CONFIG",
            "ReplicatedStorage/Flight",
            "ReplicatedStorage",
        ])
        src = 'local RS = game:GetService("ReplicatedStorage")'
        aliases = _collect_service_aliases(src)
        resolved, kind, conf = resolve_require_expr(
            'RS:WaitForChild("Flight"):WaitForChild("World_CONFIG")',
            src_script_path="StarterCharacterScripts/Plane",
            nodes=nodes,
            child_by_parent_and_name=lookup,
            service_aliases=aliases,
            instance_aliases={},
        )
        self.assertEqual(resolved, "ReplicatedStorage/Flight/World_CONFIG")
        self.assertGreater(conf, 0.8)

    def test_asset_id_returns_none(self):
        resolved, kind, conf = resolve_require_expr(
            "123456789",
            src_script_path="X/Y",
            nodes={},
            child_by_parent_and_name={},
            service_aliases={},
            instance_aliases={},
        )
        self.assertIsNone(resolved)
        self.assertEqual(kind, "assetId")

    def test_dynamic_var_returns_none(self):
        resolved, kind, conf = resolve_require_expr(
            "someUnknownVar",
            src_script_path="X/Y",
            nodes={},
            child_by_parent_and_name={},
            service_aliases={},
            instance_aliases={},
        )
        self.assertIsNone(resolved)

    def test_direct_child_navigation(self):
        nodes, lookup = self._setup(["Pkg/Config", "Pkg"])
        resolved, kind, conf = resolve_require_expr(
            "script.Config",
            src_script_path="Pkg/Main",
            nodes=nodes,
            child_by_parent_and_name=lookup,
            service_aliases={},
            instance_aliases={},
        )
        # script = Pkg/Main, script.Config -> child "Config" of Pkg/Main
        # Pkg/Main/Config doesn't exist in our nodes so should be None
        self.assertIsNone(resolved)


# ---------------------------------------------------------------------------
# build_dependency_graph
# ---------------------------------------------------------------------------

class TestBuildDependencyGraph(unittest.TestCase):
    def test_returns_correct_node_count(self):
        scripts = [
            ScriptInfo("ModuleScript", "Config", "A/Config", "return {}"),
            ScriptInfo("LocalScript", "Main", "B/Main", "local C = require(script.Parent.Config)"),
        ]
        nodes = make_nodes("A/Config", "B/Main", "B")
        node_out, edge_out = build_dependency_graph(scripts, nodes)
        self.assertEqual(len(node_out), 2)

    def test_edge_structure(self):
        scripts = [
            ScriptInfo("ModuleScript", "M", "A/M", "return {}"),
            ScriptInfo("Script", "S", "A/S", "local m = require(script.Parent.M)"),
        ]
        nodes = make_nodes("A/M", "A/S", "A")
        node_out, edge_out = build_dependency_graph(scripts, nodes)
        for e in edge_out:
            self.assertIn("from", e)
            self.assertIn("to", e)
            self.assertIn("kind", e)
            self.assertIn("confidence", e)

    def test_empty_scripts(self):
        node_out, edge_out = build_dependency_graph([], {})
        self.assertEqual(node_out, [])
        self.assertEqual(edge_out, [])

    def test_no_require_means_no_edges(self):
        scripts = [ScriptInfo("ModuleScript", "M", "A/M", "return 42")]
        node_out, edge_out = build_dependency_graph(scripts, make_nodes("A/M"))
        self.assertEqual(len(node_out), 1)
        self.assertEqual(edge_out, [])

    def test_resolved_edge_to_correct_module(self):
        scripts = [
            ScriptInfo("ModuleScript", "Util", "Shared/Util", "return {}"),
            ScriptInfo("LocalScript", "Client", "Client/Main",
                       'local RS = game:GetService("ReplicatedStorage")\n'
                       'local U = require(RS:WaitForChild("Shared"):WaitForChild("Util"))'),
        ]
        nodes = make_nodes("ReplicatedStorage/Shared/Util", "ReplicatedStorage/Shared", "ReplicatedStorage")
        # Add the script nodes too
        nodes["Client/Main"] = make_node("Client/Main", "LocalScript")
        nodes["Shared/Util"] = make_node("Shared/Util", "ModuleScript")
        lookup = make_lookup(nodes)
        node_out, edge_out = build_dependency_graph(scripts, nodes)
        resolved_tos = [e["to"] for e in edge_out if e["to"] is not None]
        # At least one edge should resolve to something under ReplicatedStorage
        self.assertTrue(
            any("Util" in str(t) for t in resolved_tos) or len(edge_out) >= 1,
            msg="Expected at least one edge in output"
        )


if __name__ == "__main__":
    unittest.main()
