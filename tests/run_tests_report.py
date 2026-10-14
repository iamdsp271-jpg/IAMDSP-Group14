"""Runs all tests and saves a readable result list in tests/test_results.json (used in the project report)."""
import json
import os
import sys
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import test_iamdsp  # noqa: E402


class Collect(unittest.TextTestResult):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.rows = []

    def _add(self, test, outcome):
        doc = (test._testMethodDoc or "").split("|")
        self.rows.append({"id": doc[0].strip(), "action": doc[1].strip() if len(doc) > 1 else test._testMethodName,
                          "expected": doc[2].strip() if len(doc) > 2 else "", "result": outcome})

    def addSuccess(self, test):
        super().addSuccess(test); self._add(test, "Pass")

    def addFailure(self, test, err):
        super().addFailure(test, err); self._add(test, "Fail")

    def addError(self, test, err):
        super().addError(test, err); self._add(test, "Fail")


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromModule(test_iamdsp)
    t0 = time.time()
    res = unittest.TextTestRunner(resultclass=Collect, verbosity=1).run(suite)
    out = {"total": res.testsRun, "passed": res.testsRun - len(res.failures) - len(res.errors), "seconds": round(time.time() - t0, 2),
           "rows": sorted(res.rows, key=lambda r: r["id"])}
    with open(os.path.join(HERE, "test_results.json"), "w") as f:
        json.dump(out, f, indent=2)
    print(f"\nSaved tests/test_results.json  -  {out['passed']} of {out['total']} tests passed")
