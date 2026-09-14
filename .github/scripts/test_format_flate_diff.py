import unittest

from format_flate_diff import format_diff, summarize_diff


class FormatFlateDiffTests(unittest.TestCase):
    def test_modified_added_and_removed_resources(self):
        diff = """--- ConfigMap default/modified
+++ ConfigMap default/modified
@@ -1,2 +1,2 @@
 kind: ConfigMap
-  value: old
+  value: new
@@ -10 +10,2 @@
   second: value
+  third: value
--- ConfigMap default/added
+++ ConfigMap default/added
@@ -1 +1,3 @@
+kind: ConfigMap
+data: {}
 
--- ConfigMap default/removed
+++ ConfigMap default/removed
@@ -1,3 +1 @@
-kind: ConfigMap
-data: {}
 
"""
        self.assertEqual(summarize_diff(diff), {
            "ConfigMap default/modified": [2, 1],
            "ConfigMap default/added": [2, 0],
            "ConfigMap default/removed": [0, 2],
        })
        message = format_diff(diff)
        self.assertIn("| ConfigMap default/modified | +2 | −1 |", message)
        self.assertIn("| **Total (3 resources)** | **+4** | **−3** |", message)
        self.assertIn(f"<summary>Show full diff</summary>\n\n```diff\n{diff}```", message)
        self.assertTrue(message.endswith("\n</details>\n"))

    def test_header_like_content_is_counted_inside_hunks(self):
        diff = """--- ConfigMap default/sample
+++ ConfigMap default/sample
@@ -1 +1 @@
--- old content
+++ new content
"""
        self.assertEqual(summarize_diff(diff), {"ConfigMap default/sample": [1, 1]})

    def test_zero_length_ranges_and_no_newline_markers(self):
        diff = r"""--- /dev/null
+++ ConfigMap default/added
@@ -0,0 +1 @@
+new
\ No newline at end of file
--- ConfigMap default/removed
+++ /dev/null
@@ -1 +0,0 @@
-old
\ No newline at end of file
"""
        self.assertEqual(summarize_diff(diff), {
            "ConfigMap default/added": [1, 0],
            "ConfigMap default/removed": [0, 1],
        })

    def test_embedded_code_fences_stay_inside_full_diff(self):
        diff = "--- ConfigMap default/sample\n+++ ConfigMap default/sample\n@@ -0,0 +1 @@\n+```\n"
        self.assertIn(f"\n````diff\n{diff}````\n", format_diff(diff))

    def test_no_changes(self):
        self.assertEqual(format_diff(""), "### apollo changes\n\nNo rendered resource changes.\n")

    def test_malformed_diff_fails_instead_of_reporting_incorrect_totals(self):
        for diff in [
            "--- ConfigMap default/sample\n",
            "@@ -1 +1 @@\n-old\n+new\n",
            "--- ConfigMap default/sample\n+++ ConfigMap default/sample\n@@ -2 +2 @@\n-old\n",
        ]:
            with self.subTest(diff=diff), self.assertRaises(ValueError):
                summarize_diff(diff)


if __name__ == "__main__":
    unittest.main()
