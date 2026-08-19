import unittest

from services.tool_registry import ToolRegistry


class ToolRegistryTests(unittest.TestCase):
    def test_standard_tools_use_injected_handlers(self):
        registry = ToolRegistry()
        registry.register_standard_tools({"get_rankings": lambda keyword=None, limit=None: {"keyword": keyword, "limit": limit}})
        result = registry.invoke("get_rankings", {"keyword": "seo", "limit": 5}, context={"client_id": 7})
        self.assertEqual(result["keyword"], "seo")
        self.assertEqual(registry.definitions()[0].name, "get_rankings")
        self.assertEqual(registry.history()[0]["status"], "success")

    def test_failed_tool_is_logged_and_raised(self):
        registry = ToolRegistry()
        registry.register("broken", lambda: (_ for _ in ()).throw(ValueError("offline")))
        with self.assertRaisesRegex(RuntimeError, "offline"):
            registry.invoke("broken")
        self.assertEqual(registry.history()[0]["status"], "failed")

    def test_unknown_tool_is_rejected(self):
        with self.assertRaisesRegex(KeyError, "Unknown tool"):
            ToolRegistry().invoke("missing")


if __name__ == "__main__":
    unittest.main()
