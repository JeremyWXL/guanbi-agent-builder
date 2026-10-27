#!/usr/bin/env python3
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import preview_card


class PreviewCardTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.scope = {
            "cdIds": {"c1"},
            "cardsById": {
                "c1": {"cdId": "c1", "name": "参数卡", "dynamicParams": [
                    {"dpId": "dp1", "name": "月份", "defaultValue": "9月"}
                ]},
            },
        }

    def run_main(self, *args):
        old = sys.argv
        sys.argv = ["preview_card.py", *args]
        with mock.patch.object(preview_card.scope_mod, "load_scope", return_value=self.scope), \
             mock.patch.object(preview_card.subprocess, "run") as proc:
            proc.return_value.returncode = 0
            try:
                preview_card.main()
            except SystemExit as exc:
                return exc.code, proc
            finally:
                sys.argv = old
            return 0, proc

    def test_out_of_scope_rejected_before_cli(self):
        code, proc = self.run_main("c9")
        self.assertEqual(code, 3)
        proc.assert_not_called()

    def test_declared_dynamic_param_forwarded(self):
        code, proc = self.run_main("c1", "--dynamic-param", "月份=10月")
        self.assertEqual(code, 0)
        command = proc.call_args[0][0]
        self.assertEqual(command[:4], ["guancli", "card", "preview", "c1"])
        self.assertIn("月份=10月", command)

    def test_undeclared_dynamic_param_rejected(self):
        code, proc = self.run_main("c1", "--dynamic-param", "年份=2026")
        self.assertEqual(code, 3)
        proc.assert_not_called()

    def test_explicit_scope_path(self):
        path = os.path.join(self.dir, "cards-raw.json")
        with mock.patch.object(preview_card.scope_mod, "load_scope", return_value=self.scope) as loader, \
             mock.patch.object(preview_card.subprocess, "run") as proc:
            proc.return_value.returncode = 0
            old = sys.argv
            sys.argv = ["preview_card.py", "c1", "--scope", path]
            try:
                preview_card.main()
            except SystemExit as exc:
                self.assertEqual(exc.code, 0)
            finally:
                sys.argv = old
        loader.assert_called_once_with(candidates=[path])


if __name__ == "__main__":
    unittest.main()
